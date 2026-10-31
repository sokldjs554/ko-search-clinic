import importlib
from decimal import Decimal

import pytest


def api(name):
    assert importlib.util.find_spec('searchclinic.research.phase2'), 'Phase 2 missing'
    return importlib.import_module('searchclinic.research.phase2.' + name)


def test_budget_approval_required_before_reserving():
    b = api('budget').CallBudget('gpt-4.1-mini-2025-04-14', '0.40', '1.60', 2, '0.01')
    with pytest.raises(PermissionError):
        b.reserve('q1', 6000)
    assert b.calls == 0


def test_budget_reserves_worst_case_and_no_retry():
    b = api('budget').CallBudget('gpt-4.1-mini-2025-04-14', '.4', '1.6', 2, '.0096', approved=True)
    assert b.reserve('q1', 6000) == Decimal('.0048')
    with pytest.raises(ValueError, match='retry'):
        b.reserve('q1', 6000)
    b.settle('q1', 4000, 1000, model='gpt-4.1-mini-2025-04-14')
    assert b.spent == Decimal('.0032')
    b.reserve('q2', 6000)
    with pytest.raises(ValueError, match='calls'):
        b.reserve('q3', 6000)


@pytest.mark.parametrize('args', [(None,100), (100,None), (6001,100), (100,1501),(-1,0),(True,0)])
def test_unknown_or_overcap_usage_halts(args):
    b = api('budget').CallBudget('m', '1', '5', 3, '1', approved=True)
    b.reserve('q1', 6000)
    with pytest.raises(ValueError):
        b.settle('q1', *args, model='m')
    assert b.halted
    with pytest.raises(ValueError, match='halt'):
        b.reserve('q2', 6000)


def test_budget_denies_cost_overshoot_and_model_substitution():
    cls = api('budget').CallBudget
    b = cls('m', '1', '5', 2, '.0134', approved=True)
    with pytest.raises(ValueError, match='USD'):
        b.reserve('q1', 6000)
    b = cls('m', '1', '5', 2, '1', approved=True)
    b.reserve('q1', 6000)
    with pytest.raises(ValueError, match='model'):
        b.settle('q1', 0, 0, model='other')
    assert b.halted


def test_failure_keeps_reserved_cost_and_halts():
    b = api('budget').CallBudget('m', '1', '5', 2, '1', approved=True)
    b.reserve('q1', 6000)
    b.fail('q1', 'transport_error')
    assert b.halted and b.reserved == __import__('decimal').Decimal('.0135')


@pytest.mark.parametrize('dimension', ['normalized_query', 'document_text', 'synonym_term', 'template'])
def test_cross_split_overlap_detected(dimension):
    d = api('data')
    dev = [{'query_id':'d','query':'수문','document_text':'강의 물을 조절',
            'synonym_terms':['수문','물문'],'template':'keyword','concept':'water'}]
    test = [{'query_id':'t','query':'우주','document_text':'행성 관측',
             'synonym_terms':['우주','cosmos'],'template':'explanation','concept':'space'}]
    keys={'normalized_query':'query','document_text':'document_text','synonym_term':'synonym_terms','template':'template'}
    test[0][keys[dimension]] = dev[0][keys[dimension]]
    result=d.audit_overlap(dev,test)
    assert any(x['dimension']==dimension for x in result['overlaps'])
    assert result['independence_certified'] is False


def test_semantic_review_stays_unresolved_even_without_exact_overlap():
    result=api('data').audit_overlap([], [{'query_id':'x','query':'새 개념','document_text':'새 본문',
        'synonym_terms':['새 개념'],'template':'new','concept':'new'}])
    assert result['semantic_review']=='required'
    assert not result['independence_certified']
