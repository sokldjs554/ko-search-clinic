"""Measured reports and their displayed summaries must tell the same story."""
import json
from pathlib import Path
import pytest

ROOT=Path(__file__).resolve().parents[1]

@pytest.mark.parametrize('name',['results.json','revalidated.json'])
def test_summary_counts_match_saved_rows(name):
    report=json.loads((ROOT/'docs/verification/alba-20261027/run'/name).read_text(encoding='utf-8'))
    assert report['summary']['invalid']==sum(r.get('answer',{}).get('status')=='invalid' for r in report['rows'])

def test_revalidation_keeps_original_model_outputs_and_counts():
    base=ROOT/'docs/verification/alba-20261027/run'
    original=json.loads((base/'results.json').read_text(encoding='utf-8'))
    revised=json.loads((base/'revalidated.json').read_text(encoding='utf-8'))
    assert revised['original_summary']==original['summary']
    assert len(revised['rows'])==len(original['rows'])
    for before,after in zip(original['rows'],revised['rows']):
        assert before['generation']==after['generation']
        assert before['context']==after['context']
        assert after['original_validation']['answer']==before['answer']

def test_recovered_display_quotes_are_actual_provided_source_substrings():
    report=json.loads((ROOT/'src/searchclinic/web/replay.json').read_text(encoding='utf-8'))
    for row in report['rows']:
        for e in row['answer']['evidence']:
            doc=next(d for d in row['context']['documents'] if d['id']==e['doc_id'])
            assert e['quote'] in doc['body']
        if row['condition']=='no_documents':
            assert row['answer']['prescription'] is None
            assert row.get('gate') is None
