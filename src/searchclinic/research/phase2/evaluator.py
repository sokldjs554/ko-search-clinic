"""Private final scoring process. Verdicts never cross back to generators."""
import hashlib
import json
import random
from dataclasses import asdict
from pathlib import Path
import re
import subprocess
from statistics import mean
from time import perf_counter

from searchclinic.corpus.catalog import Document
from searchclinic.corpus.evalset import EvalQuery
from searchclinic.evaluation.metrics import evaluate_all
from searchclinic.patch.gate import run_gate
from searchclinic.patch.ir import Prescription
from searchclinic.research.actions import ActionKind, Candidate
from searchclinic.research.costs import CostRecord, MeasuredEngine, aggregate_costs
from searchclinic.research.detector import RuleDetector
from searchclinic.research.models import EvidenceSpan
from searchclinic.research.policy import Budget, select_action
from searchclinic.research.splits import normalize_query

from .contracts import Context, ROOT, PROTOCOL_COMMIT, load_protocol, source_provenance
from .generation import MANIFEST_FIELDS, public_input_manifest, seal_bundle, verify_seal


def _preflight(sealed, manifest_path):
    body=verify_seal(sealed)
    if set(body['arms']) != {'rules_plus','llm'}:
        raise ValueError('both candidate arms must be frozen before opening final labels')
    if body['source_hash'] != source_provenance()['source_hash']:
        raise ValueError('generator/evaluator source provenance differs')
    if (not isinstance(body['source_sha'],str) or not re.fullmatch('[0-9a-f]{40}',body['source_sha'])
            or body['protocol_commit']!=PROTOCOL_COMMIT or type(body['source_dirty']) is not bool):
        raise ValueError('invalid source/protocol provenance')
    if subprocess.run(['git','cat-file','-e',body['source_sha']+'^{commit}'],cwd=ROOT,
                      capture_output=True).returncode:
        raise ValueError('recorded source commit provenance unavailable')
    if body['source_dirty']!=source_provenance()['source_dirty']:
        raise ValueError('source dirty provenance differs')
    manifest=json.loads(Path(manifest_path).read_text(encoding='utf-8'))
    if set(manifest)!=MANIFEST_FIELDS:
        raise ValueError('unexpected manifest fields')
    expected=public_input_manifest(sealed)
    if manifest!=expected:
        reason='input' if manifest.get('input_hash')!=expected['input_hash'] else 'provenance'
        raise ValueError(f'frozen manifest {reason} mismatch')
    # Revalidate targets/spans/coverage, even if someone has recomputed the outer hash.
    checked=seal_bundle(body['contexts'],body['arms'],body['documents'],body['dataset_hash'],body['label_commitment'])
    for key in ('contexts','arms','prompt_hash'):
        if checked['body'][key] != body[key]:
            raise ValueError('candidate contract mismatch')
    return body


def _load_labels(path, body, synthetic_only):
    raw=Path(path).read_bytes()
    if hashlib.sha256(raw).hexdigest()!=body['label_commitment']:
        raise ValueError('label commitment changed after generation')
    labels=json.loads(raw)
    if labels.get('synthetic') is not synthetic_only:
        raise ValueError('synthetic fixture and research evaluation must be separate')
    if labels.get('review_status')!='independent_review_complete':
        raise ValueError('independent label review required')
    rows=labels['queries']
    contexts=[Context.model_validate(c) for c in body['contexts']]
    if [r['query_id'] for r in rows]!=[c.query_id for c in contexts]:
        raise ValueError('full evaluator query coverage required in fixed order')
    if len({normalize_query(r['query']) for r in rows})!=len(rows):
        raise ValueError('duplicate evaluator query')
    docs=[Document(**{k:d[k] for k in ('doc_id','name','description','category')}) for d in body['documents']]
    if not docs or len({d.doc_id for d in docs})!=len(docs):
        raise ValueError('nonempty unique corpus required')
    docmap={d.doc_id:d.text for d in docs}
    for c,r in zip(contexts,rows):
        if c.query!=r['query'] or not r.get('group_id') or r.get('stratum') not in ('healthy','challenge'):
            raise ValueError('evaluator target/stratum/group mismatch')
        if (not r['qrels'] or set(r['qrels'])-set(docmap)
                or any(type(g) is not int or not 1<=g<=3 for g in r['qrels'].values())):
            raise ValueError('invalid qrel documents/grades')
        if any(docmap.get(d.doc_id)!=d.text for d in c.documents):
            raise ValueError('context evidence does not match sealed corpus')
    return labels,contexts,docs


def _run_arm(name, records, contexts, docs, rows, protocol):
    start=perf_counter()
    engine=MeasuredEngine(docs)
    evalset=[EvalQuery(r['query'],r['qrels']) for r in rows]
    before=evaluate_all(engine,evalset)
    policy=protocol['policy']
    expected=CostRecord(**policy['expected_action_cost'])
    # Protocol action penalty is mapped to the legacy utility's argument name.
    weights={k:v for k,v in policy['weights'].items() if k!='actions'}
    weights['unnecessary_actions']=policy['weights']['actions']
    queries,ledger=[],[]
    for i,(c,row) in enumerate(zip(contexts,rows)):
        detection=RuleDetector(protocol['detector']).detect(c.observation)
        record=records[i] if records else None
        budget=Budget(max_actions=3,max_submits=3)
        trace=[]
        decision='no_op'
        intervened=name!='no_repair' and detection.predicted_failure is True
        raws=record['candidates'] if record else []
        for raw in raws:
            rx=Prescription.model_validate(raw['prescription'])
            candidate=Candidate(ActionKind.TYPED_PATCH,rx,
                tuple(EvidenceSpan(**e) for e in raw['evidence']),
                CostRecord(**record['costs']),expected)
            selected=select_action(detection,[candidate],budget,weights=weights,
                min_gain=policy['min_gain'],cost_semantics='expected-v2')
            decision=selected.action.value
            if selected.candidate is None:
                break
            budget.used_actions+=1
            budget.used_submits+=1
            try:
                verdict,sandbox=run_gate(engine,evalset,rx,min_gain=policy['min_gain'],epsilon=policy['epsilon'])
                event={'attempt':budget.used_submits,'accepted':verdict.accepted,
                    'reason':'accepted' if verdict.accepted else 'rejected',
                    'verdict':asdict(verdict),**raw}
                trace.append(event)
                if verdict.accepted:
                    engine=sandbox
                    ledger.append({'query_id':c.query_id,**event})
                    break
            except Exception as exc:
                trace.append({'attempt':budget.used_submits,'accepted':False,'reason':'gate_error',
                    'error':{'type':type(exc).__name__,'message':str(exc)},**raw})
                break
        if name!='no_repair' and not raws:
            decision=select_action(detection,[],budget).action.value
        queries.append({'query_id':c.query_id,'query':c.query,'stratum':row['stratum'],
            'group_id':row['group_id'],'detection':detection.model_dump(),'decision':decision,
            'diagnosis_attempted':intervened,'submissions':budget.used_submits,
            'accepted':any(t['accepted'] for t in trace),'trace':trace,
            'generation_error':record['error'] if record else None,
            'before':asdict(before[c.query])})
    after=evaluate_all(engine,evalset)
    for q in queries:
        q['after']=asdict(after[q['query']])
    healthy=[q for q in queries if q['stratum']=='healthy']
    challenge=[q for q in queries if q['stratum']=='challenge']
    def reg(q):
        return any(q['after'][m]<q['before'][m]-policy['epsilon'] for m in ('ndcg','recall','precision5'))
    costs=aggregate_costs([CostRecord(**r['costs']) for r in records]) if records else CostRecord()
    # Preparation search counts are a common separate artifact, not concealed in arm costs.
    evaluation_cost=CostRecord(search_calls=engine.meter.search_calls,reindexes=engine.meter.reindexes,
                              latency_ms=(perf_counter()-start)*1000)
    return {'queries':queries,'ledger':ledger,
        'healthy_regressions':sum(reg(q) for q in healthy),'healthy_count':len(healthy),
        'healthy_diagnosis_attempts':sum(q['diagnosis_attempted'] for q in healthy),
        'healthy_submissions':sum(q['submissions'] for q in healthy),
        'healthy_accepted':sum(q['accepted'] for q in healthy),
        'challenge_count':len(challenge),
        'challenge_improved':sum(q['after']['ndcg']>=q['before']['ndcg']+policy['min_gain'] for q in challenge),
        'mean_challenge_ndcg':mean(q['after']['ndcg'] for q in challenge) if challenge else None,
        'generation_costs':asdict(costs),'evaluation_costs':asdict(evaluation_cost),
        'costs':asdict(aggregate_costs([costs,evaluation_cost]))}


def _compare(arms, protocol, synthetic_only):
    groups={}
    for l,r in zip(arms['llm']['queries'],arms['rules_plus']['queries']):
        if l['stratum']=='challenge':
            groups.setdefault(l['group_id'],[]).append(l['after']['ndcg']-r['after']['ndcg'])
    deltas=[mean(v) for v in groups.values()]
    cfg=protocol['bootstrap']
    rng=random.Random(cfg['seed'])
    draws=sorted(mean(rng.choices(deltas,k=len(deltas))) for _ in range(cfg['resamples'])) if deltas else []
    interval=[draws[int(.025*len(draws))],draws[min(len(draws)-1,int(.975*len(draws)))]] if draws else None
    enough=len(deltas)>=cfg['minimum_groups_for_claim']
    return {'group_count':len(deltas),'mean_group_delta_llm_minus_rules':mean(deltas) if deltas else None,
        'group_bootstrap_95':interval,'superiority_claim':False,
        'quality_safety_criteria_met':bool(enough and not synthetic_only and interval and interval[0]>0
            and arms['llm']['healthy_regressions']==0),
        'reason':'Synthetic fixtures or small authored pilot cannot establish generalization; paid-budget and independent data review are separate prerequisites.'}


def evaluate_bundle(sealed, labels_path, synthetic_only=False, manifest_path=None):
    manifest_path=manifest_path or Path(labels_path).parent/'public-input-manifest.json'
    body=_preflight(sealed,manifest_path)
    labels,contexts,docs=_load_labels(labels_path,body,synthetic_only)
    if not synthetic_only:
        for record in body['arms']['llm']:
            triggered=record['detection']['predicted_failure'] is True
            cost=CostRecord(**record['costs'])
            if triggered and (not record['model'] or record['model'].startswith('offline-')
                or cost.model_calls!=1 or any(x is None for x in (cost.input_tokens,cost.output_tokens,cost.api_cost_usd))):
                raise ValueError('actual approved LLM model/usage provenance required')
        # Live approval and selected-model/price freeze are deliberately not configured yet.
        raise PermissionError('final paid comparison requires separately approved model and execution manifest')
    protocol=load_protocol()
    arms={name:_run_arm(name,body['arms'].get(name),contexts,docs,labels['queries'],protocol)
          for name in ('no_repair','rules_plus','llm')}
    return {'schema_version':1,'synthetic_only':synthetic_only,'candidate_seal_hash':sealed['seal_hash'],
        'dataset':body['dataset'],'dataset_hash':body['dataset_hash'],'label_commitment':body['label_commitment'],
        **source_provenance(),'arms':arms,'comparison':_compare(arms,protocol,synthetic_only),
        'cost_scope':'generation excludes shared observation preparation; full gate evaluation costs separate; no latency superiority claim'}


def main():
    import argparse
    from .generation import write_once
    parser=argparse.ArgumentParser(description='Separate evaluator: all candidates sealed before labels')
    parser.add_argument('--bundle',required=True)
    parser.add_argument('--labels',required=True)
    parser.add_argument('--out',required=True)
    parser.add_argument('--manifest',required=True,help='Trusted pre-generation input/provenance commitment')
    parser.add_argument('--synthetic-only',action='store_true')
    args=parser.parse_args()
    result=evaluate_bundle(json.loads(Path(args.bundle).read_text(encoding='utf-8')),
                           args.labels,args.synthetic_only,args.manifest)
    write_once(args.out,result)


if __name__=='__main__':
    main()
