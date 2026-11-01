"""Grounding repairs location metadata only; fixtures are not human judgments."""
import copy
import importlib


def api():
    return importlib.import_module('searchclinic.research_v5.grounding')


def verdict(quote, start, end, doc_id='d'):
    return {'assessments':[{'patch_id':'synonym:0', 'relation':'equivalent',
        'same_referent':True, 'scope_preserved':True, 'context_supported':True,
        'confidence':.93, 'reasoning':'unchanged synthetic rationale',
        'citations':[{'doc_id':doc_id,'quote':quote,'start':start,'end':end}]}]}


def test_unique_korean_quote_is_located_without_changing_semantic_judgment_or_source():
    raw=verdict('정확한 인용',0,3);before=copy.deepcopy(raw)
    out,audit=api().align_unique_quotes({'d':'앞 문장. 정확한 인용. 뒤 문장.'},raw)
    assert raw==before
    cite=out['assessments'][0]['citations'][0]
    assert cite=={'doc_id':'d','quote':'정확한 인용','start':6,'end':12}
    lhs=copy.deepcopy(out);lhs['assessments'][0]['citations']=before['assessments'][0]['citations']
    assert lhs==before
    assert audit[0]['status']=='unique_offset_recovered'


def test_ambiguous_absent_and_unknown_document_quotes_remain_rejected():
    for text,raw,status in [
        ('반복 / 반복',verdict('반복',1,3),'ambiguous_quote'),
        ('실제 원문',verdict('지어낸 인용',0,4),'quote_not_found'),
        ('원문',verdict('원문',1,3,doc_id='unknown'),'unknown_document')]:
        out,audit=api().align_unique_quotes({'d':text},raw)
        assert out==raw
        assert audit[0]['status']==status


def test_existing_correct_offset_is_kept_even_if_quote_repeats():
    raw=verdict('반복',5,7)
    out,audit=api().align_unique_quotes({'d':'반복 / 반복'},raw)
    assert out==raw
    assert audit[0]['status']=='already_valid'


def test_overlapping_matches_are_ambiguous_and_fuzzy_matching_is_never_used():
    for text,quote,status in [('aaa','aa','ambiguous_quote'),('두 단어','두단어','quote_not_found')]:
        raw=verdict(quote,2,4)
        out,audit=api().align_unique_quotes({'d':text},raw)
        assert out==raw
        assert audit[0]['status']==status


def test_derivation_is_bound_to_verified_source_and_does_not_mutate_it(tmp_path, monkeypatch):
    from test_v5_review_regressions import run_fixture
    from searchclinic.research_v5.run_evidence import load_run
    bundle,folder=run_fixture(tmp_path,monkeypatch)
    source=load_run(folder,bundle);before=copy.deepcopy(source)
    result=api().derive_trials(bundle,source)
    assert source==before
    assert result['body']['source_evidence_hash']==source['sha256']
    assert result['body']['input_hash']==bundle['sha256']
    assert result['body']['additional_provider_calls']==0
    assert result['body']['stage']=='posthoc_development_only_not_preregistered_primary'
    assert result['body']['trials']==source['body']['trials']


def test_partial_provider_run_cannot_be_promoted_to_grounding_experiment(tmp_path, monkeypatch):
    import pytest
    from test_v5_review_regressions import run_fixture
    from searchclinic.research_v5.run_evidence import load_run
    bundle,folder=run_fixture(tmp_path,monkeypatch,stopped=True)
    with pytest.raises(ValueError,match='complete'):
        api().derive_trials(bundle,load_run(folder,bundle))
