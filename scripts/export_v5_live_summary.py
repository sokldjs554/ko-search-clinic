#!/usr/bin/env python3
"""Export a numeric public summary and a separate ignored local demo record.

No query, document, candidate, response text or per-query metric is copied into
public output. The original experiment and post-hoc derivation stay separate.
"""
import argparse
from collections import Counter
import hashlib
import json
import math
from pathlib import Path
from statistics import mean
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'src'))
METRICS = ('ndcg10', 'recall10', 'precision5')
CONDITIONS = ('pair', 'context', 'rubric')
ARMS = ('no_repair', 'rules_plus', 'first_valid', 'pair:1', 'pair:2',
        'context:1', 'context:2', 'rubric:1', 'rubric:2')
COUNTS = ('apply_count', 'hold_count', 'normal_regression_count', 'harmful_accepted_count',
          'useful_candidate_false_hold_count')
REASONS = {'non_equivalent_relation', 'same_referent_not_confirmed', 'scope_not_preserved',
    'low_confidence', 'invalid_citation', 'context_support_not_confirmed', 'invalid_candidate',
    'missing_verdict', 'malformed_verdict', 'model_mismatch', 'binding_mismatch',
    'patch_coverage_mismatch', 'pair_context_claim_forbidden', 'application_error',
    'context_required_for_pair_condition', 'unexpected_verdict_count'}


def number(value):
    if type(value) not in (int, float) or not math.isfinite(value):
        raise ValueError('public metrics must be finite numeric values')
    return value


def interval(row):
    return {m: {'mean_difference':number(row['metrics'][m]['mean_difference']),
                'ci':None if row['metrics'][m]['ci'] is None else
                    [number(x) for x in row['metrics'][m]['ci']]} for m in METRICS}


def aggregate_report(report):
    arms = {}
    for name in ARMS:
        raw, counts = report['scores']['summaries'][name], report['arms'][name]
        arms[name] = {'metrics': {population: {k:(None if k != 'count' and values['count'] == 0 and values[k] is None else number(values[k]))
                for k in ('count', *METRICS)}
            for population,values in raw.items() if population in ('overall','healthy','failure')},
            **{key:(None if key == 'useful_candidate_false_hold_count' and key not in counts else number(counts.get(key, 0))) for key in COUNTS},
            'reason_counts':{key:number(value) for key,value in counts.get('reason_counts',{}).items()
                             if key in REASONS}}
        oracle=counts.get('oracle_diagnostic',{}).get('per_query',{})
        arms[name]['useful_candidates_not_selected']=sum(len(row['useful_rejected']) for row in oracle.values()) if oracle else None
        arms[name]['useful_candidates_selected']=sum(len(row['useful_selected']) for row in oracle.values()) if oracle else None
        arms[name]['selected_below_oracle_or_noop']=sum(row['selected_candidate_id'] is not None and
            row['oracle_score'] > row['selected_score'] + 1e-12 for row in oracle.values()) if oracle else None
    return {'arms':arms, 'primary_rubric_comparisons':{name:interval(report['paired_primary'][name])
        for name in ('vs_no_repair','vs_rules_plus')},
        'primary_ci_level':.975, 'independent_concept_groups':number(report['paired_primary']['vs_no_repair']['independent_groups']),
        'repeat_variability':{c:{k:number(report['repeat_variability'][c][k]) for k in
            ('repeats','mean_ndcg10','population_sd_ndcg10','changed_selection_query_count')} for c in CONDITIONS},
        'threshold_diagnostic':{name:{threshold:{k:number(row[k]) for k in ('apply_count','mean_ndcg10')}
            for threshold,row in report['threshold_diagnostic']['rows'][name].items()
            if threshold in ('0.0','0.5','0.8','0.9','1.0')} for name in ARMS if ':' in name}}


def build_public(report, assembly, queries, run_id, grounded_report, grounded_assembly, derivation, zero_selection, zero_report):
    from searchclinic.research_v5 import pipeline, comparison
    from searchclinic.research_v5.run_evidence import validate_run
    from searchclinic.research_v5.grounding import derive_trials, align_unique_quotes
    from searchclinic.research_v5.evaluation import _percentile
    app = pipeline.verify(assembly)
    evidence = app['transport_evidence']
    bundle = evidence['body']['plan']['body']['bundle']
    source = validate_run(evidence,bundle,require_complete=True)
    if (report['assembly_hash'] != assembly['sha256'] or report['protocol_hash'] != app['protocol']['sha256']
            or report['phase'] != 'development' or report['candidate_source'] != 'historical_scripted'):
        raise ValueError('expected bound historical development report')
    if (derive_trials(bundle,evidence) != derivation or grounded_report['assembly_hash'] != grounded_assembly['sha256']
            or grounded_assembly['body']['protocol'] != app['protocol']):
        raise ValueError('post-hoc derivation binding mismatch')
    for trial in derivation['body']['trials']:
        name=f"{trial['condition']}:{trial['repeat']}"
        if grounded_assembly['body']['applications'][name]['body']['verdict_hash'] != pipeline.freeze(trial['verdicts'])['sha256']:
            raise ValueError('derived application verdict hash mismatch')
    result = {'version':'v5-live-public-summary-1', 'run_id':run_id,
        'run_url':f'https://github.com/sokldjs554/ko-search-clinic/actions/runs/{run_id}',
        'model_id':source['plan']['body']['model_id'], 'plan_hash':source['plan']['sha256'],
        'input_hash':bundle['sha256'], 'protocol_hash':app['protocol']['sha256'],
        'assembly_hash':assembly['sha256'], 'private_report_hash':pipeline.freeze(report)['sha256'],
        'study_status':'retrospective_development_selection_only_not_independent',
        'candidate_source':'historical_scripted_not_GPT_generated', 'candidate_count':source['plan']['body']['candidate_count'],
        'semantic_human_review_complete':False, 'independent_evaluation_complete':False,
        'superiority_claim':False, 'confidence_threshold':bundle['body']['min_confidence'], **aggregate_report(report)}
    result['candidate_pools']={}
    for label,key,arm in [('historical_scripted','diagnostic','first_valid'),('rules_plus','rules_diagnostic','rules_plus')]:
        diagnostic=app[key]['body']
        oracle=report['arms'][arm]['oracle_diagnostic']['per_query']
        result['candidate_pools'][label]={'rankable_candidates':sum(len(v) for v in diagnostic['rankings'].values()),
            'queries_with_rankable_candidates':sum(bool(v) for v in diagnostic['rankings'].values()),
            'queries_with_useful_candidate':sum(v['available_gain']>1e-12 for v in oracle.values()),
            'useful_candidate_count':sum(len(v['useful_selected'])+len(v['useful_rejected']) for v in oracle.values()),
            'generation_error_count':sum(bool(v) for v in diagnostic['generation_errors'].values())}
    contexts={r['context']['query_id']:r['context'] for r in bundle['body']['records']}
    per_condition={}
    all_input=all_output=0
    for condition in CONDITIONS:
        calls=[row for row in source['call_records'] if row['request']['condition']==condition]
        citations, relations, statuses = Counter(),Counter(),Counter()
        for row in calls:
            request,outcome=row['request'],row['outcome'];statuses[outcome['status']]+=1
            if outcome['verdict'] is None:
                continue
            documents={d['doc_id']:d['text'] for d in contexts[request['query_id']]['documents']}
            _, audit=align_unique_quotes(documents,outcome['verdict'])
            citations.update(item['status'] for item in audit)
            relations.update(item['relation'] for item in outcome['verdict']['assessments'])
        input_tokens=sum(row['outcome']['usage']['input_tokens'] for row in calls)
        output_tokens=sum(row['outcome']['usage']['output_tokens'] for row in calls)
        all_input+=input_tokens;all_output+=output_tokens
        latency=sorted(row['outcome']['latency_ms'] for row in calls)
        per_condition[condition]={'calls':len(calls),'statuses':dict(statuses),
            'input_tokens':input_tokens,'output_tokens':output_tokens,
            'cost_estimate_usd':(input_tokens*4+output_tokens*16)/10_000_000,
            'latency_mean_ms':mean(latency),'latency_p95_ms':_percentile(latency,.95),
            'assessment_relations':dict(relations),'citation_checks':dict(citations)}
    estimate=(all_input*4+all_output*16)/10_000_000
    if not math.isclose(estimate,source['summary']['usage_cost_estimate_usd'],abs_tol=1e-12):
        raise ValueError('cost summary disagrees with raw usage')
    result['costs']={'provider_calls':source['summary']['provider_calls_executed'],
        'input_tokens':all_input,'output_tokens':all_output,'usage_cost_estimate_usd':estimate,
        'actual_invoice_usd':None,'reserved_ceiling_usd':source['summary']['reserved_cost_usd'],
        'wall_latency_ms':source['summary']['latency_ms'],'per_condition':per_condition,
        'basis':'standard_uncached_rates_from_usage_not_provider_invoice'}
    result['matched_random']={name:{'repeats':len(rows),'apply_count':rows[0]['apply_count'],
        'mean_ndcg10':mean(row['mean_ndcg10'] for row in rows),
        'sampling_95pct_range':[_percentile(sorted(row['mean_ndcg10'] for row in rows),p) for p in (.025,.975)],
        'selector_minus_random_mean':report['scores']['summaries'][name]['overall']['ndcg10']-mean(row['mean_ndcg10'] for row in rows)}
        for name,rows in report['matched_random'].items() if name in ARMS}
    pair_mean={qid:{m:mean(report['scores']['per_query'][f'pair:{r}'][qid][m] for r in (1,2)) for m in METRICS}
               for qid in report['scores']['per_query']['no_repair']}
    result['exploratory_pair_comparisons']={name:interval(comparison._paired(pair_mean,
        report['scores']['per_query'][name],queries,bootstrap_samples=2000,seed=20261030,ci_level=.95))
        for name in ('no_repair','rules_plus','first_valid')}
    result['exploratory_ci_level']=.95
    result['posthoc_unique_quote_grounding']={'stage':'posthoc_development_only_not_primary',
        'derivation_hash':derivation['sha256'],'algorithm_hash':derivation['body']['implementation_sha256'],
        'additional_provider_calls':0,'citation_counts':derivation['body']['citation_counts'],
        **aggregate_report(grounded_report)}
    from searchclinic.research_v5 import retrieval_aware
    if (retrieval_aware.assemble(assembly) != zero_selection
            or zero_report['selection_hash'] != zero_selection['sha256']
            or zero_report['source_hash'] != assembly['sha256']):
        raise ValueError('zero-hit selection binding mismatch')
    zero_arms = {}
    for name in ARMS:
        if ':' not in name:
            continue
        row = zero_report['arms'][name]
        zero_arms[name] = {'metrics':{p:{k:(None if k != 'count' and values['count'] == 0 and values[k] is None else number(values[k])) for k in ('count', *METRICS)}
                for p,values in zero_report['scores']['summaries'][name].items()
                if p in ('overall','healthy','failure')},
            **{k:number(row[k]) for k in COUNTS},
            'changed_query_count':number(zero_report['changed_query_counts'][name]),
            'useful_candidates_not_selected':sum(len(v['useful_rejected'])
                for v in row['oracle_diagnostic']['per_query'].values())}
    result['posthoc_zero_hit_selection']={'stage':'posthoc_development_only_not_primary',
        'selection_hash':zero_selection['sha256'],
        'algorithm_hash':zero_selection['body']['implementation_sha256'],
        'additional_provider_calls':0,'arms':zero_arms,
        'exploratory_pair_vs_rules':{name:interval(zero_report['exploratory_pair_vs_rules'][name])
                                   for name in ('pair:1','pair:2')}}
    return result


def local_details(report, assembly):
    from searchclinic.research_v5.pipeline import verify
    app=verify(assembly);source=app['transport_evidence']['body'];queries=[]
    trials={(t['condition'],t['repeat']):t['verdicts'] for t in source['trials']}
    for record in source['plan']['body']['bundle']['body']['records']:
        context=record['context'];qid=context['query_id']
        queries.append({'query_id':qid,'query':context['query'],'documents':context['documents'],
            'candidates':record['candidates'],
            'before':{'ranking':app['applications']['first_valid']['body']['baseline_rankings'][qid],
                      'metrics':report['scores']['per_query']['no_repair'][qid]},
            'trials':{f'{c}:{r}':{'decision':app['applications'][f'{c}:{r}']['body']['decisions'][qid],
                'verdicts':trials[c,r][qid], 'ranking':app['applications'][f'{c}:{r}']['body']['rankings'][qid],
                'metrics':report['scores']['per_query'][f'{c}:{r}'][qid]} for c in CONDITIONS for r in (1,2)}})
    return {'version':'v5-live-private-demo-1','queries':queries,'assembly_hash':assembly['sha256']}


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root',type=Path,required=True)
    parser.add_argument('--run-id',type=int,required=True)
    parser.add_argument('--out',type=Path)
    parser.add_argument('--zero-root',type=Path,help='Optional newer write-once zero-hit derivation directory')
    args=parser.parse_args(argv)
    from searchclinic.research_v5.transport import private_path
    from searchclinic.research_v5.__main__ import read,write_once
    root=private_path(args.root)
    report,assembly=read(root/'private/report.json'),read(root/'assembly.json')
    zero_root=private_path(args.zero_root) if args.zero_root else root/'zero-hit'
    result=build_public(report,assembly,read(root/'recovered/prepared/private/labels.json')['queries'],args.run_id,
        read(root/'grounding/private/report.json'),read(root/'grounding/assembly.json'),read(root/'grounding/derivation.json'),
        read(zero_root/'selection.json'),read(zero_root/'private/report.json'))
    receipt=read(root/'download/receipt.json')
    if str(args.run_id) != receipt['run_id'] or result['plan_hash'] != receipt['plan_hash']:
        raise ValueError('artifact receipt identity mismatch')
    if hashlib.sha256((root/'download/evidence.enc.json').read_bytes()).hexdigest() != receipt['envelope_sha256']:
        raise ValueError('artifact envelope checksum mismatch')
    output=private_path(args.out) if args.out else root
    output.mkdir(parents=True,exist_ok=True)
    write_once(output/'public-summary.json',result)
    write_once(output/'demo-details.json',local_details(report,assembly))
    print(json.dumps({'public_summary_hash':hashlib.sha256((output/'public-summary.json').read_bytes()).hexdigest(),
                      'additional_provider_calls':0,'superiority_claim':False}))


if __name__=='__main__':
    main()
