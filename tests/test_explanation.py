"""Generated candidates must never bypass evidence or the existing gate."""
import copy
import pytest
from searchclinic.rag.knowledge import KnowledgeDoc
from searchclinic.rag.explanation import validate_explanation

DOC = KnowledgeDoc('K1', '동의어', '표기 변형은 좁은 동의어로 연결한다.', '프로젝트 문서')
GOOD = {'status': 'supported', 'summary': '표기 차이로 검색이 단절될 수 있습니다.',
        'family': 'spelling_variant', 'evidence': [{'doc_id': 'K1', 'quote': '표기 변형은 좁은 동의어로 연결한다.'}],
        'patches': [{'kind': 'synonym', 'terms': ['프라이팬', '후라이팬']}]}

def test_verified_citation_produces_target_bound_prescription():
    result = validate_explanation(GOOD, [DOC], '후라이팬')
    assert result['status'] == 'supported'
    assert result['prescription']['target_query'] == '후라이팬'
    assert result['prescription']['synonym_groups'] == [{'terms': ['프라이팬', '후라이팬']}]

@pytest.mark.parametrize('evidence', [[], [{'doc_id':'missing', 'quote':DOC.body}],
    [{'doc_id':'K1', 'quote':'존재하지 않는 주장입니다.'}], [{'doc_id':'K1', 'quote':''}]])
def test_invalid_or_missing_citation_cannot_supply_prescription(evidence):
    raw = copy.deepcopy(GOOD)
    raw['evidence'] = evidence
    result = validate_explanation(raw, [DOC], '후라이팬')
    assert result['status'] == 'invalid'
    assert result['prescription'] is None

def test_abstention_with_patch_is_invalid():
    raw = {**GOOD, 'status':'abstain'}
    assert validate_explanation(raw, [DOC], '후라이팬')['status'] == 'invalid'

def test_no_evidence_abstention_is_explicit():
    raw = {'status':'abstain','summary':'제공된 문서로는 판단할 수 없습니다.',
           'family':'unknown','evidence':[], 'patches':[]}
    assert validate_explanation(raw, [], '주식')['status'] == 'abstain'

@pytest.mark.parametrize('patch', [{'kind':'synonym','terms':['팬','팬']},
    {'kind':'compound','terms':['물티슈','물','휴지']}, {'kind':'user_word','terms':[]}])
def test_existing_prescription_constraints_still_apply(patch):
    raw = {**GOOD, 'patches':[patch]}
    result = validate_explanation(raw, [DOC], '후라이팬')
    assert result['status'] == 'invalid'
    assert result['prescription'] is None

def test_model_cannot_override_target_or_smuggle_extra_fields():
    assert validate_explanation({**GOOD, 'target_query':'팬'}, [DOC], '후라이팬')['status'] == 'invalid'

def test_malformed_output_is_visible_not_a_fake_abstention():
    assert validate_explanation({'oops':True}, [DOC], '후라이팬')['status'] == 'invalid'
