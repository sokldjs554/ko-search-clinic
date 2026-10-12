"""Synthetic boundary tests; none are independent-data quality results."""
import copy
import importlib
import json

import pytest
from pydantic import ValidationError

from searchclinic.corpus.catalog import Document
from searchclinic.index.engine import SearchEngine


def api():
    assert importlib.util.find_spec('searchclinic.research.phase2'), 'Phase 2 missing'
    return importlib.import_module('searchclinic.research.phase2.generation')


@pytest.fixture
def context():
    g = api()
    engine = SearchEngine([Document('S1', '수문', '강의 물을 조절하는 시설', 'fixture')])
    return g.build_context(engine, 'synthetic-1', '수믄')


@pytest.mark.parametrize('forbidden', ['qrels', 'family', 'baseline_ndcg', 'expected_patch_kinds', 'feedback'])
def test_context_rejects_evaluator_fields(context, forbidden):
    c = importlib.import_module('searchclinic.research.phase2.contracts')
    with pytest.raises(ValidationError):
        c.Context.model_validate(dict(context.model_dump(), **{forbidden: {}}))


def test_same_context_no_labels_and_isolated_worker(context):
    g = api()
    local = g.generate_rules(context)
    process = g.generate_in_process(context)
    assert process['worker_pid'] != __import__('os').getpid()
    assert process['context_hash'] == local['context_hash']
    assert process['candidates'] == local['candidates']
    assert 'qrels' not in json.dumps(context.model_dump())
    assert process['costs']['model_calls'] == 0


def test_worker_denies_private_labels_and_evaluator_import(context, tmp_path):
    g = api()
    hidden = tmp_path / 'labels.json'
    hidden.write_text('{"SECRET_QREL":1}', encoding='utf-8')
    report = g.probe_boundary(hidden)
    assert report['label_read'] == 'denied'
    assert report['evaluator_import'] == 'denied'


def test_ordered_candidate_cap_and_wrong_target(context):
    g = api()
    rx = dict(target_query='수믄', diagnosis_family='spelling_variant',
              reasoning='합성 단위 시험의 표기 변형 근거입니다.',
              synonym_groups=[{'terms':['수문', '수믄']}])
    with pytest.raises(ValueError, match='three'):
        g.validate_candidates(context, [rx] * 4)
    with pytest.raises(ValueError, match='target'):
        g.validate_candidates(context, [dict(rx, target_query='다른 질의')])
    with pytest.raises(ValueError, match='evidence'):
        g.validate_candidates(context, [dict(rx, synonym_groups=[{'terms':['위조', '수믄']}])])


def test_seal_detects_tampering_and_never_overwrites(context, tmp_path):
    g = api()
    record = g.generate_rules(context)
    sealed = g.seal_bundle([context], {'rules_plus':[record]}, [], 'a'*64, 'b'*64)
    p = tmp_path / 'sealed.json'
    g.write_once(p, sealed)
    with pytest.raises(FileExistsError):
        g.write_once(p, sealed)
    tampered = copy.deepcopy(sealed)
    tampered['body']['contexts'][0]['query'] = '변경'
    with pytest.raises(ValueError, match='seal'):
        g.verify_seal(tampered)


def test_mismatched_context_and_duplicate_query_rejected(context):
    g = api()
    record = g.generate_rules(context)
    bad = dict(record, context_hash='0'*64)
    with pytest.raises(ValueError, match='context'):
        g.seal_bundle([context], {'rules_plus':[bad]}, [], 'a'*64, 'b'*64)
    with pytest.raises(ValueError, match='duplicate'):
        g.seal_bundle([context,context], {'rules_plus':[record,record]}, [], 'a'*64, 'b'*64)
