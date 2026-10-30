"""Same finite diagnostics for both generators; never reads final labels."""
import json
import os
import subprocess
import sys
from dataclasses import asdict
from pathlib import Path
from tempfile import TemporaryDirectory
from time import perf_counter

from searchclinic.doctor.rules_plus import RulesPlusDoctor
from searchclinic.doctor.tools import ClinicExecutor
from searchclinic.patch.ir import Prescription
from searchclinic.research.actions import prescription_terms
from searchclinic.research.costs import CostRecord
from searchclinic.research.detector import RuleDetector
from searchclinic.research.models import EvidenceSpan
from searchclinic.research.observations import observe
from searchclinic.research.splits import digest

from .contracts import Context, ROOT, load_protocol, source_provenance

RECORD_FIELDS = {'query_id','context_hash','arm','model','detection','candidates','error','worker_pid','costs'}
BODY_FIELDS = {'schema_version','dataset','dataset_hash','input_hash','label_commitment','contexts',
    'documents','arms','prompt_hash','source_sha','source_hash','source_dirty','protocol_commit','protocol_hash'}
MANIFEST_FIELDS = {'input_hash','dataset_hash','label_commitment','source_sha','source_hash',
                   'source_dirty','protocol_commit','protocol_hash'}

PROMPT = ('Generate an ordered list of at most three typed retrieval analyzer repairs '
          'using only the provided query and document evidence. Return JSON {"candidates": [...]} '
          'using the supplied Prescription schema. Empty list means abstain. Do not request tools, '
          'labels, feedback, or additional queries. Every patch term must occur literally in '
          'the provided query or documents. This is one-shot generation, without evaluation feedback.')


def build_llm_request(context):
    """Prepare a request without transport or approval. Same context as RulesPlus."""
    return {'prompt':PROMPT,'context':Context.model_validate(context).model_dump(),
            'prescription_schema':Prescription.model_json_schema(),
            'max_output_tokens':1500,'automatic_retries':0}


def build_context(engine, query_id, query):
    p = load_protocol()
    tools = ClinicExecutor(engine, [])
    obs = observe(engine, query, query_id, 'test').policy_view()
    tokens = engine.analyzer.tokens(query)
    doctor = RulesPlusDoctor()
    doctor._query, doctor._query_tokens = query, tokens
    similar = tools._tool_find_similar_tokens(doctor._probe)['similar'][:p['context_similar_tokens']]
    hits = engine.search(query, k=p['context_search_k'])
    grep = engine.grep_raw(query)
    ids = [h.doc_id for h in hits]
    ids += [d.doc_id for d in grep]
    for item in similar:
        ids += [d.doc_id for d in engine.docs.values()
                if item['token'] in d.text]
    ids = list(dict.fromkeys(ids))[:p['context_documents']]
    return Context(query_id=query_id, query=query, observation=obs,
        query_tokens=tokens, search_total=obs.result_count, grep_total=len(grep),
        similar=[{'token':s['token'], 'similarity':s['similarity']} for s in similar],
        documents=[{'doc_id':i,'text':engine.docs[i].text,'tokens':engine.doc_tokens(i)} for i in ids])


def _strict_prescription(raw):
    allowed = set(Prescription.model_fields)
    if set(raw) - allowed:
        raise ValueError('unexpected prescription fields')
    for key, fields in [('user_words', {'form','tag','score'}),
                        ('synonym_groups', {'terms'}), ('compound_expansions', {'word','parts'})]:
        if any(set(x)-fields for x in raw.get(key, [])):
            raise ValueError('unexpected nested prescription fields')
    return Prescription.model_validate(raw)


def validate_candidates(context, candidates):
    context = Context.model_validate(context)
    if not isinstance(candidates, list) or len(candidates) > 3:
        raise ValueError('maximum three ordered candidates')
    out = []
    for raw in candidates:
        rx = _strict_prescription(raw)
        if rx.target_query != context.query:
            raise ValueError('candidate target mismatch')
        spans = []
        for term in prescription_terms(rx):
            sources = [('query', context.query, context.query)]
            sources += [('document', d.doc_id, d.text) for d in context.documents]
            found = next(((kind, sid, text, text.find(term)) for kind,sid,text in sources if term in text), None)
            if found is None:
                raise ValueError('candidate term has no literal evidence')
            kind, sid, text, start = found
            spans.append(EvidenceSpan(source_type=kind, source_id=sid,
                start=start,end=start+len(term),text=term).model_dump())
        out.append({'prescription':rx.model_dump(), 'evidence':spans})
    return out


def generate_rules(context):
    context = Context.model_validate(context)
    start = perf_counter()
    detector = RuleDetector(load_protocol()['detector']).detect(context.observation)
    candidates, error = [], None
    if detector.predicted_failure is True:
        doctor = RulesPlusDoctor()
        doctor._query, doctor._query_tokens = context.query, context.query_tokens
        doctor._search_total, doctor._grep_total = context.search_total, context.grep_total
        doctor._similar = [x.model_dump() for x in context.similar]
        for raw in doctor._ladder()[:3]:
            try:
                candidates += validate_candidates(context, [dict(raw, target_query=context.query)])
            except ValueError as exc:
                error = {'type':type(exc).__name__, 'message':str(exc)}
    return {'query_id':context.query_id, 'context_hash':digest(context.model_dump()),
        'arm':'rules_plus', 'model':None, 'detection':detector.model_dump(mode='json'),
        'candidates':candidates, 'error':error, 'worker_pid':os.getpid(),
        'costs':asdict(CostRecord(latency_ms=(perf_counter()-start)*1000))}


def _worker(payload):
    src = str(ROOT / 'src')
    code = f"import sys; sys.path.insert(0,{src!r}); from searchclinic.research.phase2.worker import main; main()"
    # Only explicit JSON crosses the process boundary. No key/label environment.
    env = {k:os.environ[k] for k in ('SYSTEMROOT','WINDIR','PATH','LANG') if k in os.environ}
    env['PYTHONIOENCODING']='utf-8'
    with TemporaryDirectory() as cwd:
        r = subprocess.run([sys.executable,'-I','-c',code], input=json.dumps(payload,ensure_ascii=False),
            text=True, encoding='utf-8', capture_output=True, cwd=cwd,env=env, timeout=60,check=True)
    return json.loads(r.stdout)


def generate_in_process(context):
    return _worker({'context':Context.model_validate(context).model_dump()})


def probe_boundary(private_path):
    return _worker({'probe':str(Path(private_path).resolve())})


def seal_bundle(contexts, arms, documents, dataset_hash, label_commitment):
    contexts = [Context.model_validate(c) for c in contexts]
    ids = [c.query_id for c in contexts]
    if len(set(ids)) != len(ids):
        raise ValueError('duplicate query IDs')
    if not set(arms) <= {'rules_plus','llm'}:
        raise ValueError('unknown generator arm')
    for arm, records in arms.items():
        if [r['query_id'] for r in records] != ids:
            raise ValueError('missing, reordered or duplicate candidate query')
        for c,r in zip(contexts,records):
            if set(r) != RECORD_FIELDS:
                raise ValueError('unexpected candidate record fields')
            if r['context_hash'] != digest(c.model_dump()) or r['arm'] != arm:
                raise ValueError('candidate context/arm mismatch')
            if r['detection'] != RuleDetector(load_protocol()['detector']).detect(c.observation).model_dump(mode='json'):
                raise ValueError('candidate detector mismatch')
            expected = validate_candidates(c, [x['prescription'] for x in r['candidates']])
            if expected != r['candidates']:
                raise ValueError('candidate evidence mismatch')
            CostRecord(**r['costs'])
            if arm=='rules_plus' and (r['model'] is not None or r['costs']['model_calls'] != 0):
                raise ValueError('rules model provenance mismatch')
    body = {'schema_version':1, 'dataset':'source-grounded-authored-pilot',
            'dataset_hash':dataset_hash, 'label_commitment':label_commitment,
            'contexts':[c.model_dump() for c in contexts], 'documents':documents, 'arms':arms,
            'input_hash':digest({'contexts':[c.model_dump() for c in contexts],'documents':documents}),
            'prompt_hash':digest({'prompt':PROMPT,'schema':Prescription.model_json_schema()}),
            **source_provenance()}
    return {'seal_hash':digest(body),'body':body}


def verify_seal(sealed):
    if set(sealed) != {'body','seal_hash'} or sealed['seal_hash'] != digest(sealed['body']):
        raise ValueError('candidate seal mismatch')
    if set(sealed['body']) != BODY_FIELDS:
        raise ValueError('unexpected sealed body fields')
    if sealed['body']['input_hash'] != digest({'contexts':sealed['body']['contexts'],
                                             'documents':sealed['body']['documents']}):
        raise ValueError('public input hash mismatch')
    if sealed['body']['protocol_hash'] != digest(load_protocol()):
        raise ValueError('protocol provenance mismatch')
    return sealed['body']


def public_input_manifest(sealed):
    body=verify_seal(sealed)
    return {k:body[k] for k in MANIFEST_FIELDS}


def write_once(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('x', encoding='utf-8') as f:
        json.dump(value,f,ensure_ascii=False,sort_keys=True,indent=2,allow_nan=False)
        f.write('\n')
