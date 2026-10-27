"""Revalidate saved responses offline. No provider import, key or API call."""
import copy
import hashlib
import json
from pathlib import Path
from collections import Counter
from searchclinic.rag.explanation import validate_explanation
from searchclinic.rag.knowledge import KnowledgeDoc
from searchclinic.service import ClinicService, ToolFailed

ROOT=Path(__file__).resolve().parents[1]

def main():
    original=ROOT/'docs/verification/alba-20261027/run/results.json'
    report=json.loads(original.read_text(encoding='utf-8'))
    clinic=ClinicService()
    report['original_summary']=copy.deepcopy(report['summary'])
    report['revalidation']={'source_results_sha256':hashlib.sha256(original.read_bytes()).hexdigest(),
        'validator_sha256':hashlib.sha256((ROOT/'src/searchclinic/rag/explanation.py').read_bytes()).hexdigest(),
        'method':'same saved model outputs; whitespace and paired bold markers mapped back to exact source substrings',
        'new_api_calls':0,'posthoc':True}
    for row in report['rows']:
        row['original_validation']={'answer':copy.deepcopy(row.get('answer')),'gate':copy.deepcopy(row.get('gate'))}
        docs=[KnowledgeDoc(d['id'],d['title'],d['body'],d['source']) for d in row['context']['documents']]
        if 'generation' not in row:continue
        answer=validate_explanation(row['generation']['raw'],docs,row['context']['query'])
        row.update(answer=answer,gate=None)
        row.pop('gate_error',None)
        row['revalidated_offline']=True
        if answer['prescription']:
            sid=clinic.create_session(label='offline-revalidation')['session_id']
            try:
                try:clinic.open_query(sid,row['context']['query'])
                except ToolFailed:row['gate_error']='query_not_evaluable'
                else:
                    try:row['gate']=clinic.submit_prescription(sid,answer['prescription'])
                    except ToolFailed:row['gate_error']='candidate_rejected_before_evaluation'
            finally:clinic.delete_session(sid)
    report['revalidation']['statuses']=dict(Counter(row.get('answer',{}).get('status','error') for row in report['rows']))
    report['revalidation']['gate_accepted']=sum(bool(row.get('gate',{}).get('accepted')) for row in report['rows'] if row.get('gate'))
    report['revalidation']['gate_rejected']=sum(not row['gate']['accepted'] for row in report['rows'] if row.get('gate'))
    report['summary']={'source_api_run':report['original_summary'],
        'new_api_calls':0, 'invalid':report['revalidation']['statuses'].get('invalid',0),
        'statuses':report['revalidation']['statuses'],
        'gate_accepted':report['revalidation']['gate_accepted'],
        'gate_rejected':report['revalidation']['gate_rejected']}
    text=json.dumps(report,ensure_ascii=False,indent=2)
    (original.parent/'revalidated.json').write_text(text,encoding='utf-8')
    (ROOT/'src/searchclinic/web/replay.json').write_text(text,encoding='utf-8')
    print(json.dumps(report['revalidation'],ensure_ascii=False))

if __name__=='__main__': main()
