"""Preparation must not silently turn sparse QA supervision into final qrels."""
import csv
import importlib
import json

import pytest


def api():
    spec = importlib.util.find_spec('searchclinic.research_v5.dataset')
    assert spec is not None, 'independent dataset preparation is not implemented'
    return importlib.import_module('searchclinic.research_v5.dataset')


def source():
    rows = []
    for i in range(20):
        impossible = i >= 12
        rows.append({'title': f'문서 {i}', 'source': 'fixture', 'paragraphs': [{
            'context': f'정답 {i} 문서 본문', 'qas': [{
                'guid': f'q{i}', 'question': f'질문 {i}', 'is_impossible': impossible,
                'answers': [] if impossible else [{'text': f'정답 {i}', 'answer_start': 0}],
                'question_type': 3 if impossible else 1}]}]})
    return {'version': 'v1.1', 'data': rows}


def test_source_order_does_not_change_sample_and_unknown_pairs_stay_unknown():
    module = api()
    first = module.build_dataset(source(), answerable=4, unanswerable=2, calibration=2, distractors=2)
    other = source(); other['data'].reverse()
    second = module.build_dataset(other, answerable=4, unanswerable=2, calibration=2, distractors=2)
    assert first == second
    assert len(first['queries']) == 6 and len(first['documents']) == 8
    assert sum(next(iter(q.values())) == 1 for q in first['proxy_qrels'].values()) == 4
    assert sum(next(iter(q.values())) == 0 for q in first['proxy_qrels'].values()) == 2
    assert all(len(q) == 1 for q in first['proxy_qrels'].values())
    assert first['audit']['split_audit']['valid']
    assert first['audit']['study_status'] == 'candidate_review_pending'
    assert first['audit']['final_evaluation_ready'] is False


def test_bad_answer_offsets_duplicate_ids_and_insufficient_groups_fail_closed():
    module = api()
    bad = source(); bad['data'][0]['paragraphs'][0]['qas'][0]['answers'][0]['answer_start'] = 2
    with pytest.raises(ValueError, match='answer span'):
        module.build_dataset(bad, answerable=4, unanswerable=2, calibration=2, distractors=2)
    bad = source(); bad['data'][1]['paragraphs'][0]['qas'][0]['guid'] = 'q0'
    with pytest.raises(ValueError, match='duplicate query'):
        module.build_dataset(bad, answerable=4, unanswerable=2, calibration=2, distractors=2)
    bad = source()
    for row in bad['data']:
        row['title'] = 'shared article'
    with pytest.raises(ValueError, match='groups'):
        module.build_dataset(bad, answerable=4, unanswerable=2, calibration=2, distractors=2)


def test_exposure_overlap_blocks_but_does_not_replace_selected_queries():
    module = api()
    data = module.build_dataset(source(), answerable=4, unanswerable=2, calibration=2, distractors=2)
    query = data['queries'][0]['query']
    exposed = [{'query_id': 'historical', 'query': '  '+query+'  ', 'document_texts': [], 'concept_ids': []}]
    audited = module.build_dataset(source(), answerable=4, unanswerable=2, calibration=2, distractors=2,
                                   exposure=exposed)
    assert audited['queries'] == data['queries']
    assert audited['audit']['known_exposure_overlaps']['query_count'] == 1
    assert not audited['audit']['complete_historical_exposure_audited']


def test_preparation_is_write_once_keeps_review_blank_and_verifies_source(tmp_path):
    module = api()
    raw = tmp_path/'source.json'; raw.write_text(json.dumps(source()), encoding='utf-8')
    with pytest.raises(ValueError, match='checksum'):
        module.prepare(raw, tmp_path/'bad', expected_sha256='0'*64,
                       answerable=4, unanswerable=2, calibration=2, distractors=2)
    assert not (tmp_path/'bad').exists()
    out = tmp_path/'prepared'
    module.prepare(raw, out, expected_sha256=module.file_hash(raw),
                   answerable=4, unanswerable=2, calibration=2, distractors=2)
    inputs = json.loads((out/'inputs.json').read_text(encoding="utf-8"))
    assert 'qrels' not in inputs and 'proxy_qrels' not in inputs
    assert all('source_doc_id' not in q and 'is_impossible' not in q for q in inputs['queries'])
    a = list(csv.DictReader((out/'review/reviewer-a-pairs.csv').open(encoding="utf-8")))
    b = list(csv.DictReader((out/'review/reviewer-b-pairs.csv').open(encoding="utf-8")))
    assert len(a) > 6 and len(a) == len(b)
    assert all(r['grade'] == r['reviewer_id'] == r['evidence'] == '' for r in a+b)
    assert {(r['query_id'],r['doc_id']) for r in a} == {(r['query_id'],r['doc_id']) for r in b}
    with pytest.raises(FileExistsError):
        module.prepare(raw, out, expected_sha256=module.file_hash(raw),
                       answerable=4, unanswerable=2, calibration=2, distractors=2)


def test_missing_source_titles_use_context_groups_without_merging_unrelated_passages():
    module = api()
    raw = source()
    for article in raw['data']:
        article['title'] = ''
    data = module.build_dataset(raw, answerable=4, unanswerable=2, calibration=2, distractors=2)
    assert len(data['queries']) == 6
    assert len({q['concept_id'] for q in data['queries']}) == 6
    assert data['audit']['split_audit']['valid']


def test_public_review_inputs_cannot_link_queries_to_source_answer_passages(tmp_path):
    module = api()
    raw = tmp_path/'source.json'
    raw.write_text(json.dumps(source()), encoding='utf-8')
    out = tmp_path/'prepared'
    module.prepare(raw, out, expected_sha256=module.file_hash(raw),
                   answerable=4, unanswerable=2, calibration=2, distractors=2)
    inputs = json.loads((out/'inputs.json').read_text(encoding="utf-8"))
    # A source concept/article ID shared between query and document would expose
    # the answer-passage association even though no qrels field was published.
    assert all(set(q) == {'query_id', 'query', 'split'} for q in inputs['queries'])
    assert all(set(d) == {'doc_id', 'name', 'description', 'category', 'split'} for d in inputs['documents'])
    public_qids = {q['query_id'] for q in inputs['queries']}
    public_dids = {d['doc_id'] for d in inputs['documents']}
    assert all(qid.startswith('query:') and len(qid) == 70 for qid in public_qids)
    assert all(did.startswith('document:') and len(did) == 73 for did in public_dids)
    private = json.loads((out/'private/identity-split-audit.json').read_text(encoding="utf-8"))
    assert {r['query_id'] for r in private['queries']} == public_qids
    assert {r['doc_id'] for r in private['documents']} == public_dids
    assert all(r['source_query_id'].startswith('q') for r in private['queries'])
    assert all(r['source_doc_id'].startswith('klue:') for r in private['documents'])
    assert all(r['answer_source_document_id'] in public_dids and r['concept_id'] for r in private['queries'])
    for reviewer in ('a', 'b'):
        pairs = list(csv.DictReader((out/f'review/reviewer-{reviewer}-pairs.csv').open(encoding="utf-8")))
        assert {r['query_id'] for r in pairs} == public_qids
        assert {r['doc_id'] for r in pairs} == public_dids
        assert all(set(r) == {'query_id', 'doc_id', 'split', 'reviewer_id', 'grade', 'evidence', 'ambiguity', 'reviewed_at_utc'} for r in pairs)
