#!/usr/bin/env python3
"""Verify the new generated run and export aggregates, never private query text."""
import argparse
from collections import Counter
import hashlib
import json
import math
from pathlib import Path
from statistics import mean
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src'))
sys.path.insert(0,str(Path(__file__).resolve().parent))
from export_v5_live_summary import aggregate_report, interval, local_details, number, METRICS, CONDITIONS


def usage_summary(rows,summary):
    inputs=sum(number(r['usage']['input_tokens']) for r in rows)
    outputs=sum(number(r['usage']['output_tokens']) for r in rows)
    cost=(inputs*4+outputs*16)/10_000_000
    if (len(rows)!=summary['provider_calls_executed'] or
            not math.isclose(cost,summary['usage_cost_estimate_usd'],abs_tol=1e-12)):
        raise ValueError('raw usage does not match transport summary')
    return dict(provider_calls=len(rows),input_tokens=inputs,output_tokens=outputs,
        usage_cost_estimate_usd=cost,actual_invoice_usd=None,wall_latency_ms=number(summary['latency_ms']),
        api_error_count=sum(r['status'] in ('http_error','transport_error','api_error') for r in rows))


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--root',type=Path,required=True)
    p.add_argument('--labels',type=Path,required=True)
    p.add_argument('--run-id',type=int,required=True)
    p.add_argument('--out',type=Path,required=True)
    args=p.parse_args()
    from searchclinic.research_v5 import generation,pipeline,comparison,retrieval_aware
    from searchclinic.research_v5.run_evidence import load_run
    from searchclinic.research_v5.grounding import derive_trials,align_unique_quotes
    from searchclinic.research_v5.transport import private_path
    from searchclinic.research_v5.__main__ import read,write_once
    from searchclinic.research_v5.evaluation import _percentile
    from searchclinic.research.phase2.generation import validate_candidates
    root=private_path(args.root);output=private_path(args.out)
    run=root/'recovered/run';study=read(run/'study.json');summary=read(run/'study-summary.json')
    if summary['status']!='completed':
        raise ValueError('this export requires a completed run')
    bundle,diagnostics=generation.recover_candidates(study,run/'generation',with_diagnostics=True)
    if bundle!=read(run/'candidates.json') or diagnostics!=summary['generation_diagnostics']:
        raise ValueError('generation reconstruction mismatch')
    evidence=load_run(run/'judges',bundle,require_complete=True)
    assembly=read(root/'assembly.json');app=pipeline.verify(assembly);report=read(root/'report.json')
    if (app['transport_evidence']!=evidence or report['assembly_hash']!=assembly['sha256']
            or report['candidate_source']!='gpt_generated' or report['phase']!='development'
            or app['protocol']!=read(run/'analysis.json')):
        raise ValueError('generated comparison binding mismatch')
    receipt=read(root/'download/receipt.json')
    if (receipt['plan_hash']!=study['sha256'] or receipt['run_id']!=str(args.run_id)
            or hashlib.sha256((root/'download/evidence.enc.json').read_bytes()).hexdigest()!=receipt['envelope_sha256']):
        raise ValueError('download receipt mismatch')
    grounded=read(root/'grounding/report.json');ground_app=read(root/'grounding/assembly.json')
    derivation=read(root/'grounding/derivation.json')
    if (derive_trials(bundle,evidence)!=derivation or grounded['assembly_hash']!=ground_app['sha256']):
        raise ValueError('grounding derivation mismatch')
    for trial in derivation['body']['trials']:
        name=f"{trial['condition']}:{trial['repeat']}"
        if ground_app['body']['applications'][name]['body']['verdict_hash']!=pipeline.freeze(trial['verdicts'])['sha256']:
            raise ValueError('grounded application mismatch')
    zero=read(root/'zero-hit-report.json');selection=read(root/'zero-hit-selection.json')
    if retrieval_aware.assemble(assembly)!=selection or zero['selection_hash']!=selection['sha256']:
        raise ValueError('zero-hit derivation mismatch')
    result=dict(version='v5-live-public-summary-1',candidate_source='gpt_generated',
        study_status='generated_development_comparison_not_independent_final',run_id=args.run_id,
        run_url=f'https://github.com/sokldjs554/ko-search-clinic/actions/runs/{args.run_id}',
        model_id=study['body']['model_id'],plan_hash=study['sha256'],input_hash=bundle['sha256'],
        protocol_hash=app['protocol']['sha256'],assembly_hash=assembly['sha256'],
        private_report_hash=pipeline.freeze(report)['sha256'],candidate_count=summary['candidate_count'],
        semantic_human_review_complete=False,independent_evaluation_complete=False,superiority_claim=False,
        numerical_primary_criteria_met=report['numerical_criteria_met'],confidence_threshold=.8,
        concept_group_independence_verified=False,**aggregate_report(report))
    rows=[read(f/'outcome.json') for f in sorted((run/'generation/calls').iterdir())]
    gen=usage_summary(rows,summary['generation'])
    judge=usage_summary([x['outcome'] for x in evidence['body']['call_records']],summary['judges'])
    result['costs']={k:gen[k]+judge[k] for k in ('provider_calls','input_tokens','output_tokens','usage_cost_estimate_usd','wall_latency_ms','api_error_count')}
    result['costs'].update(actual_invoice_usd=None,generation=gen,judges=judge,approved_maximum_usd=5.4432,
                           basis='standard_uncached_usage_estimate_not_invoice')
    result['generation']={k:number(diagnostics[k]) for k in ('submitted_candidates','accepted_candidates',
        'rejected_candidates','voluntary_abstention_queries','all_rejected_queries','response_error_queries',
        'withheld_queries','unattempted_queries')}
    rejected=Counter();errors=Counter()
    for f in sorted((run/'generation/calls').iterdir()):
        call=read(f/'request.json');raw=json.loads(read(f/'raw-response.json')['body'])
        text=next(x['text'] for m in raw['output'] if m['type']=='message' for x in m['content'] if x['type']=='output_text')
        for candidate in json.loads(text)['candidates']:
            try:validate_candidates(call['context'],[candidate])
            except ValueError as exc:
                if hasattr(exc,'errors'):
                    rejected['prescription_validation']+=1
                    for error in exc.errors():
                        message=error['msg']
                        category=next((key for token,key in [('이어 붙','compound_reconstruction'),('하나도 없다','empty_patch'),
                            ('빈 부분어','empty_compound_part'),('공백 없는 단일','synonym_whitespace'),
                            ('사용자 사전 항목','user_word_whitespace')] if token in message),'other_validation')
                        errors[category]+=1
                else:
                    rejected['target_mismatch' if str(exc)=='candidate target mismatch' else 'literal_evidence_missing']+=1
    result['generation']['first_rejection_stage_counts']=dict(rejected)
    result['generation']['structural_error_occurrences']=dict(errors)
    oracle=report['arms']['first_valid']['oracle_diagnostic']
    result['generation']['valid_pool_oracle_ndcg10']=report['scores']['summaries']['no_repair']['overall']['ndcg10']+oracle['available_gain_mean']
    result['generation']['queries_with_valid_candidates']=sum(bool(r['candidates']) for r in bundle['body']['records'])
    result['generation']['useful_valid_candidates']=sum(len(v['useful_selected'])+len(v['useful_rejected']) for v in oracle['per_query'].values())
    result['generation']['max_valid_candidates_per_query']=max(len(r['candidates']) for r in bundle['body']['records'])
    contexts={r['context']['query_id']:r['context'] for r in bundle['body']['records']}
    result['judgment_diagnostics']={}
    for condition in CONDITIONS:
        records=[x for x in evidence['body']['call_records'] if x['request']['condition']==condition]
        relations=Counter();citations=Counter()
        for row in records:
            verdict=row['outcome']['verdict']
            if verdict is None:continue
            relations.update(a['relation'] for a in verdict['assessments'])
            documents={d['doc_id']:d['text'] for d in contexts[row['request']['query_id']]['documents']}
            _,audit=align_unique_quotes(documents,verdict);citations.update(x['status'] for x in audit)
        result['judgment_diagnostics'][condition]=dict(calls=len(records),relations=dict(relations),citations=dict(citations))
    result['matched_random']={name:dict(repeats=len(rows),apply_count=rows[0]['apply_count'],
        mean_ndcg10=mean(r['mean_ndcg10'] for r in rows),
        sampling_95pct_range=[_percentile(sorted(r['mean_ndcg10'] for r in rows),v) for v in (.025,.975)])
        for name,rows in report['matched_random'].items()}
    labels=read(args.labels)['queries']
    for arm in result['arms']:
        result['arms'][arm]['failure_improved_queries']=sum(q['stratum']=='failure' and
            report['scores']['per_query'][arm][q['query_id']]['ndcg10']>report['scores']['per_query']['no_repair'][q['query_id']]['ndcg10']+1e-12 for q in labels)
    pair={q:{m:mean(report['scores']['per_query'][f'pair:{r}'][q][m] for r in (1,2)) for m in METRICS}
          for q in report['scores']['per_query']['no_repair']}
    result['exploratory_pair_comparisons']={name:interval(comparison._paired(pair,report['scores']['per_query'][name],labels,
        bootstrap_samples=2000,seed=20261030,ci_level=.95)) for name in ('no_repair','rules_plus','first_valid')}
    result['posthoc_unique_quote_grounding']=dict(stage='secondary_development_not_primary',additional_provider_calls=0,
        citation_counts=derivation['body']['citation_counts'],**aggregate_report(grounded))
    result['posthoc_zero_hit_selection']=dict(stage='secondary_development_not_primary',additional_provider_calls=0,
        arms={name:dict(metrics=zero['scores']['summaries'][name],normal_regression_count=number(row['normal_regression_count']),
                       apply_count=number(row['apply_count']),changed_query_count=number(zero['changed_query_counts'][name]))
              for name,row in zero['arms'].items()})
    output.mkdir(parents=True,exist_ok=False)
    write_once(output/'public-summary.json',result)
    write_once(output/'demo-details.json',local_details(report,assembly))
    print(json.dumps(dict(output=str(output),provider_calls_added=0,superiority_claim=False,
                          public_summary_sha256=hashlib.sha256((output/'public-summary.json').read_bytes()).hexdigest())))


if __name__=='__main__':main()
