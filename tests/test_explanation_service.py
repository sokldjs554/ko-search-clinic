import pytest
from searchclinic.rag.explanation_service import ExplanationService
from searchclinic.rag.knowledge import KnowledgeDoc
from searchclinic.rag.retriever import Retrieved
from searchclinic.service import ClinicService, ToolFailed

class FixedRetriever:
    def retrieve(self, query, k=3):
        return [Retrieved(KnowledgeDoc('K1','동의어','표기 변형은 좁은 동의어로 연결한다.','프로젝트 문서'),1.0)]

class FixedProvider:
    def __init__(self, terms): self.terms=terms
    def generate(self, context):
        assert 'qrels' not in str(context)
        assert 'is_healthy' not in str(context)
        return {'raw':{'status':'supported','summary':'표기 변형을 최소한의 동의어로 연결합니다.',
            'family':'spelling_variant','evidence':[{'doc_id':'K1','quote':'표기 변형은 좁은 동의어로 연결한다.'}],
            'patches':[{'kind':'synonym','terms':self.terms}]},
            'usage':{},'model':'test-double','latency_ms':0,'estimated_usd':0}

@pytest.fixture(scope='module')
def clinic(): return ClinicService()

def test_generated_candidate_is_not_applied_until_gate_requested(clinic):
    svc=ExplanationService(clinic,FixedProvider(['프라이팬','후라이팬']),FixedRetriever())
    report=svc.explain('후라이팬','표기 변형 검색 누락')
    assert report['gate'] is None
    assert clinic.search('후라이팬')['total'] == 0
    applied=svc.apply(report['id'])
    assert applied['gate']['accepted'] is True
    assert svc.apply(report['id'])['gate'] == applied['gate']
    assert clinic.search('후라이팬')['total'] == 0

def test_overbroad_generated_patch_is_rejected_by_real_gate(clinic):
    svc=ExplanationService(clinic,FixedProvider(['프라이팬','후라이팬','팬']),FixedRetriever())
    report=svc.explain('후라이팬','표기 변형')
    applied=svc.apply(report['id'])
    assert applied['gate']['accepted'] is False
    assert clinic.describe_session(applied['session_id'])['accepted_count'] == 0

def test_outside_evalset_cannot_claim_a_validated_patch(clinic):
    svc=ExplanationService(clinic,FixedProvider(['프라이팬','후라이팬']),FixedRetriever())
    report=svc.explain('없는질의','표기 변형')
    with pytest.raises(ToolFailed): svc.apply(report['id'])

def test_caller_cannot_mutate_stored_prescription(clinic):
    svc=ExplanationService(clinic,FixedProvider(['프라이팬','후라이팬']),FixedRetriever())
    report=svc.explain('후라이팬','표기 변형')
    report['answer']['prescription']['synonym_groups'][0]['terms'].append('팬')
    assert svc.apply(report['id'])['gate']['accepted'] is True
