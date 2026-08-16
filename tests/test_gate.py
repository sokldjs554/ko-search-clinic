"""회귀 게이트 테스트 — 이 프로젝트의 핵심 계약.

계약: 표적을 고치고 아무것도 망가뜨리지 않는 처방만 채택된다.
"""

import pytest

from searchclinic.corpus import load_catalog, load_evalset
from searchclinic.index.engine import SearchEngine
from searchclinic.patch.gate import run_gate
from searchclinic.patch.ir import Prescription


@pytest.fixture()
def setup():
    return SearchEngine(load_catalog()), load_evalset()


def test_correct_synonym_accepted(setup):
    engine, evalset = setup
    verdict, sandbox = run_gate(engine, evalset, Prescription(
        target_query="후라이팬", diagnosis_family="spelling_variant",
        reasoning="후라이팬은 프라이팬의 비표준 표기다.",
        synonym_groups=[{"terms": ["프라이팬", "후라이팬"]}],
    ))
    assert verdict.accepted
    assert verdict.target_after.ndcg == 1.0
    assert not verdict.regressions


def test_overbroad_synonym_rejected_with_evidence(setup):
    """함정: '팬'을 포함한 과잉 동의어는 다른 질의를 오염시켜 기각된다."""
    engine, evalset = setup
    verdict, _ = run_gate(engine, evalset, Prescription(
        target_query="후라이팬", diagnosis_family="spelling_variant",
        reasoning="팬은 프라이팬의 준말이므로 함께 묶는다 (과잉 일반화).",
        synonym_groups=[{"terms": ["프라이팬", "후라이팬", "팬"]}],
    ))
    assert not verdict.accepted
    regressed = {r.query for r in verdict.regressions}
    assert "프라이팬" in regressed  # 건강 질의가 오염됐다
    # nDCG만이 아니라 precision@5로도 잡힌다 (쓰레기 유입 탐지)
    assert any(r.metric == "precision5" for r in verdict.regressions)
    # 기각 피드백에 회귀 내역이 담긴다 (의사의 재시도 근거)
    assert "회귀" in verdict.feedback()


def test_incomplete_composite_rejected(setup):
    """아답터: 사전 등록 없는 동의어는 무효 — 표적 미개선으로 기각."""
    engine, evalset = setup
    verdict, _ = run_gate(engine, evalset, Prescription(
        target_query="아답터", diagnosis_family="garbage_split",
        reasoning="아답터는 어댑터의 표기 변형이므로 동의어로 연결한다.",
        synonym_groups=[{"terms": ["어댑터", "아답터"]}],
    ))
    assert not verdict.accepted
    assert "개선되지 않음" in verdict.reason


def test_composite_prescription_accepted(setup):
    """사전 등록 + 동의어의 2단계 복합 처방은 통과한다."""
    engine, evalset = setup
    verdict, _ = run_gate(engine, evalset, Prescription(
        target_query="아답터", diagnosis_family="garbage_split",
        reasoning="아답터가 [아,답,터]로 쪼개지므로 사전 등록 후 동의어 연결.",
        user_words=[{"form": "아답터"}],
        synonym_groups=[{"terms": ["어댑터", "아답터"]}],
    ))
    assert verdict.accepted
    assert verdict.target_after.ndcg == 1.0


def test_compound_expansion_accepted(setup):
    engine, evalset = setup
    verdict, _ = run_gate(engine, evalset, Prescription(
        target_query="티슈", diagnosis_family="compound_locked",
        reasoning="물티슈가 한 토큰으로 색인돼 부분어로 못 찾는다.",
        compound_expansions=[{"word": "물티슈", "parts": ["물", "티슈"]}],
    ))
    assert verdict.accepted


def test_rejection_leaves_engine_untouched(setup):
    """기각 = 롤백: 원본 엔진의 검색 결과가 변하지 않는다."""
    engine, evalset = setup
    before = [h.doc_id for h in engine.search("프라이팬")]
    run_gate(engine, evalset, Prescription(
        target_query="후라이팬", diagnosis_family="spelling_variant",
        reasoning="과잉 동의어로 기각될 처방.",
        synonym_groups=[{"terms": ["프라이팬", "후라이팬", "팬"]}],
    ))
    assert [h.doc_id for h in engine.search("프라이팬")] == before
    assert not engine.config.synonym_groups  # 설정도 그대로


def test_unknown_target_query_raises(setup):
    engine, evalset = setup
    with pytest.raises(ValueError, match="평가셋에 없는"):
        run_gate(engine, evalset, Prescription(
            target_query="없는질의", diagnosis_family="spelling_variant",
            reasoning="평가셋에 없는 질의를 표적으로 삼는다.",
            synonym_groups=[{"terms": ["가", "나"]}],
        ))


def test_gate_is_deterministic(setup):
    engine, evalset = setup
    rx = Prescription(
        target_query="티슈", diagnosis_family="compound_locked",
        reasoning="결정성 검증용 동일 처방 반복 제출.",
        compound_expansions=[{"word": "물티슈", "parts": ["물", "티슈"]}],
    )
    v1, _ = run_gate(engine, evalset, rx)
    v2, _ = run_gate(engine, evalset, rx)
    assert v1.accepted == v2.accepted
    assert v1.target_after.ndcg == v2.target_after.ndcg
