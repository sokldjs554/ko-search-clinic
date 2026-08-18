"""공정성 실험 — 규칙 의사에 액션과 재시도를 준 대조군.

여기서 지켜야 할 것은 "11/16이 나오는가"가 아니라 **"그 11이 정직한 11인가"**다.
베이스라인이 그대로 재현되지 않으면 비교가 성립하지 않고, `vector+`가 캐시
없이 돌면 "벡터를 켜고 잰 값"이라는 기록이 거짓이 된다. 둘 다 실제로 겪었다.
"""

import pytest

from searchclinic.analysis.vectors import load_vectors_if_available
from searchclinic.corpus import load_catalog, load_evalset
from searchclinic.doctor import (
    ENGINES,
    VECTOR_ENGINES,
    ClinicExecutor,
    RulesPlusDoctor,
    ScriptedDoctor,
    make_doctor,
)
from searchclinic.doctor.loop import MAX_SUBMITS, MAX_TURNS, run_doctor_session
from searchclinic.index.engine import SearchEngine


def _executor(vectors=None):
    return ClinicExecutor(
        engine=SearchEngine(load_catalog()), evalset=load_evalset(), vectors=vectors
    )


# --------------------------------------------------------------- 엔진 등록

def test_rules_plus_is_registered():
    assert "rules+" in ENGINES and "vector+" in ENGINES
    assert isinstance(make_doctor("rules+"), RulesPlusDoctor)


def test_rules_plus_inherits_the_baseline():
    """상속이어야 한다 — 규칙을 베껴 쓰면 '같은 규칙'이라는 주장이 검증 불가다."""
    assert isinstance(make_doctor("rules+"), ScriptedDoctor)


def test_vector_engines_is_the_single_source():
    """벡터가 필요한 엔진 목록과 실제 의사 설정이 어긋나면 안 된다.

    실측 실패: `vector+`를 추가했을 때 세 곳에 흩어진 `engine == "vector"`
    검사가 이 엔진을 걸러내, **캐시 없이 돈 11/16이 '벡터를 켜고 잰 값'으로
    기록될 뻔했다.** 문자열 분기는 항목이 늘 때 조용히 틀린다.
    """
    for name in ENGINES:
        if name == "claude":
            continue  # 외부 SDK — 여기서 만들지 않는다
        doctor = make_doctor(name)
        assert getattr(doctor, "use_vectors", False) == (name in VECTOR_ENGINES), name


# ----------------------------------------------------------- 예산은 원래 같다

def test_every_engine_gets_the_same_budget():
    """재시도 예산은 진단기가 아니라 **하니스**가 준다.

    "규칙기는 1회, LLM은 13턴"이라는 비대칭은 존재하지 않는다. 규칙기가
    예산을 안 쓸 뿐이고, 이 테스트가 그 사실을 문서 대신 고정한다.
    """
    assert MAX_TURNS == 16 and MAX_SUBMITS == 3


def test_baseline_doctor_still_stops_after_one_submit():
    """베이스라인은 여전히 한 번 제출하고 멈춰야 한다.

    이게 무너지면 10/16이라는 기준점이 사라져 이 실험 전체가 무의미해진다.
    """
    executor = _executor()
    result = run_doctor_session(executor, ScriptedDoctor(), "아답터")
    assert result.attempts == 1 and result.healed is False


# ------------------------------------------------------------- 회수한 것 1건

def test_two_step_prescription_heals_the_garbage_split():
    """`아답터`는 사전 등록이 선행돼야 동의어가 산다 — 그 순서를 규칙이 배웠다."""
    executor = _executor()
    result = run_doctor_session(executor, RulesPlusDoctor(), "아답터")
    assert result.healed is True
    assert result.attempts == 2, "1차 기각 → 2차 채택이라는 경로 자체가 측정 대상이다"
    assert result.diagnosis_family == "garbage_split"
    assert set(result.patch_kinds) == {"user_word", "synonym"}


def test_the_retry_is_what_recovers_it():
    """사다리 첫 후보는 여전히 기각돼야 한다.

    R4를 R1보다 앞에 두면 "2단계를 먼저 던져서 풀었다"가 되어, 재려던 것
    (기각 → 재처방이 무엇을 회수하는가)이 측정되지 않는다.
    """
    doctor = RulesPlusDoctor()
    executor = _executor()
    run_doctor_session(executor, doctor, "아답터")
    first = doctor._ladder()[0]
    assert first["diagnosis_family"] == "spelling_variant"
    assert "user_words" not in first


def test_two_step_rule_does_not_fire_on_intact_queries():
    """멀쩡한 질의에까지 사전 등록을 뿌리면 무엇 덕분에 풀렸는지 알 수 없게 된다."""
    doctor = RulesPlusDoctor()
    executor = _executor()
    run_doctor_session(executor, doctor, "후라이팬")
    assert doctor._rule_garbage_split() is None


# --------------------------------------------------------- 남은 것은 남는다

@pytest.mark.parametrize("query", ["블루투스 스피커", "텀블러", "츄리닝", "백팩"])
def test_rules_cannot_reach_the_semantic_four(query):
    """형태로 설명되지 않는 관계는 액션을 더해도 안 풀린다.

    이 네 건이 풀리기 시작하면 "LLM이 더 푸는 4건"이라는 서술이 거짓이 되므로,
    숫자가 아니라 **이 목록**을 테스트가 들고 있어야 한다.
    """
    vectors = load_vectors_if_available()
    executor = _executor(vectors)
    result = run_doctor_session(executor, RulesPlusDoctor(use_vectors=bool(vectors)), query)
    assert result.healed is False
