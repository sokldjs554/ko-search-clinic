"""One frozen 12-case paired run. No retries; every attempted call is retained.

Run locally without --live to inspect requests without spending money.
"""
from __future__ import annotations
import argparse
import hashlib
import importlib.metadata
import json
import os
from pathlib import Path
import subprocess
import sys
from datetime import datetime, timezone
from searchclinic.rag.explanation import validate_explanation
from searchclinic.rag.explanation_service import ExplanationService
from searchclinic.rag.openai_provider import Budget, OpenAIExplainer, ProviderError, MODEL
from searchclinic.service import ClinicService, ToolFailed

ROOT=Path(__file__).resolve().parents[1]

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--live',action='store_true')
    parser.add_argument('--output',type=Path,default=ROOT/'docs/verification/alba-20261027/run')
    args=parser.parse_args()
    args.output.mkdir(parents=True,exist_ok=True)
    cases_path=ROOT/'docs/verification/alba-20261027/cases.json'
    cases=json.loads(cases_path.read_text(encoding='utf-8'))
    svc=ExplanationService(ClinicService())
    provider=OpenAIExplainer(os.environ.get('OPENAI_API_KEY',''),budget=Budget(path=args.output/'budget.json')) if args.live else None
    report={'model':MODEL,'created_at':datetime.now(timezone.utc).isoformat(),
        'commit':subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip(),
        'cases_sha256':hashlib.sha256(cases_path.read_bytes()).hexdigest(),
        'environment':{'python':sys.version,'kiwipiepy':importlib.metadata.version('kiwipiepy')},
        'scope':'12 authored cases, paired supplied-documents / removed-documents; not a held-out benchmark or customer outcome',
        'rows':[]}
    try:
        for case in cases:
            context,docs=svc.context(case['query'],case['problem'])
            for condition in ['retrieved','no_documents']:
                current={**context,'documents':context['documents'] if condition=='retrieved' else []}
                row={'case_id':case['id'],'category':case['category'],'condition':condition,'context':current}
                if provider:
                    try:
                        generated=provider.generate(current)
                        answer=validate_explanation(generated['raw'],docs if condition=='retrieved' else [],case['query'])
                        row.update(generation=generated,answer=answer,gate=None)
                        if answer['prescription']:
                            sid=svc.clinic.create_session(label=case['id'])['session_id']
                            try:
                                try:
                                    svc.clinic.open_query(sid,case['query'])
                                except ToolFailed:
                                    row['gate_error']='query_not_evaluable'
                                else:
                                    try:
                                        row['gate']=svc.clinic.submit_prescription(sid,answer['prescription'])
                                    except ToolFailed:
                                        row['gate_error']='candidate_rejected_before_evaluation'
                            finally:
                                svc.clinic.delete_session(sid)
                    except ProviderError as exc:
                        row['error']=str(exc)
                else:
                    row['dry_run']=True
                report['rows'].append(row)
                (args.output/'results.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
                print(case['id'],condition,row.get('answer',{}).get('status',row.get('error','dry_run')),flush=True)
                if row.get('error') in ('budget_exhausted','upstream_http_401','upstream_http_403','upstream_http_404'):
                    return 2
    finally:
        rows=report['rows']
        report['summary']={
            'attempted_calls':provider.budget.calls if provider else 0,
            'successful_responses':sum('generation' in r for r in rows),
            'errors':sum('error' in r for r in rows),
            'invalid':sum(r.get('answer',{}).get('status')=='invalid' for r in rows),
            'estimated_usd_success_only':round(sum(r.get('generation',{}).get('estimated_usd',0) for r in rows),8),
            'reserved_usd':round(provider.budget.calls*.0125,6) if provider else 0}
        (args.output/'results.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    return 0

if __name__=='__main__': raise SystemExit(main())
