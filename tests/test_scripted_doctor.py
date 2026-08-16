"""ScriptedDoctor 전체 순회 테스트 — 베이스라인의 실력과 한계를 고정한다.

베이스라인이 "잘하는 것"과 "원리적으로 못 하는 것"의 경계선이 곧 LLM
의사의 존재 이유다. 이 경계가 흔들리면(예: 임계값 변경으로 유의어까지
잡거나, 표기 변형을 놓치거나) 평가의 변별력이 사라지므로 테스트로 박는다.
"""

import pytest

from searchclinic.corpus import failing_queries, load_catalog, load_evalset
from searchclinic.doctor import ClinicExecutor, ScriptedDoctor
from searchclinic.doctor.loop import run_doctor_session
from searchclinic.evaluation.harness import run_clinic
from searchclinic.index.engine import SearchEngine

# (질의, 치유 여부, 진단 계열)
EXPECTED = {
    "후라이팬": (True, "spelling_variant"),
    "케잌 주문": (True, "spelling_variant"),
    "도너츠": (True, "spelling_variant"),
    "쥬스": (True, "spelling_variant"),
    "소세지": (True, "spelling_variant"),
    "카페트": (True, "spelling_variant"),
    "초콜렛": (True, "spelling_variant"),
    "리모콘": (True, "spelling_variant"),
    "블루투스 스피커": (False, None),  # 영한 혼용 — 자모 규칙 밖
    "텀블러": (False, None),  # 영한 혼용
    "핸드폰": (False, None),  # 유의어 — 형태 규칙 밖
    "츄리닝": (False, None),  # 유의어
    "티슈": (True, "compound_locked"),
    "머스캣": (True, "compound_locked"),
    "아답터": (False, "spelling_variant"),  # 오진: 동의어만 제출 → 기각
    "백팩": (False, None),  # 자모 유사 상대도 포함 복합어도 없다 — 규칙 밖
}


@pytest.fixture(scope="module")
def report():
    return run_clinic(doctor_name="scripted")


def test_baseline_heals_exactly_the_designed_set(report):
    for case in report.cases:
        expect_healed, expect_family = EXPECTED[case.query]
        assert case.healed == expect_healed, (
            f"{case.query}: 치유={case.healed}, 기대={expect_healed}"
        )
        assert case.family_stated == expect_family, (
            f"{case.query}: 진단={case.family_stated}, 기대={expect_family}"
        )


def test_baseline_rates(report):
    assert report.heal_rate == pytest.approx(10 / 16)
    assert report.diagnosis_accuracy == pytest.approx(10 / 16)


def test_no_healthy_regressions(report):
    """게이트 보증: 치유 후 건강 질의는 하나도 나빠지지 않는다."""
    assert report.healthy_regressions == []


def test_adapter_case_is_the_designed_failure(report):
    """아답터: R1이 동의어를 제출하지만 사전 등록이 없어 기각 — 설계된 한계."""
    case = next(c for c in report.cases if c.query == "아답터")
    assert case.attempts == 1
    assert not case.healed
    assert "개선되지 않음" in case.feedback


def test_session_transcript_records_evidence_and_verdict():
    executor = ClinicExecutor(engine=SearchEngine(load_catalog()), evalset=load_evalset())
    result = run_doctor_session(executor, ScriptedDoctor(), "후라이팬")
    text = "\n".join(result.transcript)
    assert "[도구:search_products]" in text
    assert "[도구:find_similar_tokens]" in text
    assert "[게이트]" in text
    assert result.healed and result.attempts == 1


def test_doctor_instance_reusable_across_sessions():
    """같은 인스턴스로 연속 진료해도 상태가 섞이지 않는다 (세션별 리셋)."""
    executor = ClinicExecutor(engine=SearchEngine(load_catalog()), evalset=load_evalset())
    doctor = ScriptedDoctor()
    r1 = run_doctor_session(executor, doctor, "후라이팬")
    r2 = run_doctor_session(executor, doctor, "티슈")
    assert r1.healed and r2.healed
    assert r2.diagnosis_family == "compound_locked"


def test_failing_query_count_matches_expected_table():
    assert {eq.query for eq in failing_queries()} == set(EXPECTED)
