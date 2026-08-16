"""진료 루프 테스트 — 가짜 LLM으로 루프 규약을 검증한다.

Claude 없이도 루프의 계약(재시도, 종료 조건, 히스토리 규약)을 검증할 수
있어야 CI가 API 비용 없이 돈다.
"""

from searchclinic.corpus import load_catalog, load_evalset
from searchclinic.doctor import ClinicExecutor
from searchclinic.doctor.llm import LLMResponse, TextBlock, ToolUseBlock
from searchclinic.doctor.loop import run_doctor_session
from searchclinic.doctor.tools import SUBMIT_TOOL
from searchclinic.index.engine import SearchEngine


def _executor():
    return ClinicExecutor(engine=SearchEngine(load_catalog()), evalset=load_evalset())


class FakeDoctor:
    """정해진 응답 시퀀스를 재생하는 가짜 LLM."""

    def __init__(self, responses):
        self._responses = list(responses)
        self.seen_messages = []

    def create(self, *, system, messages, tools):
        # 루프가 같은 리스트 객체에 append하므로 호출 시점 상태를 복사해 둔다
        self.seen_messages.append(list(messages))
        return self._responses.pop(0)


def _submit(rx_input, block_id="t1"):
    return LLMResponse(
        content=[ToolUseBlock(id=block_id, name=SUBMIT_TOOL, input=rx_input)],
        stop_reason="tool_use",
    )


GOOD_RX = {
    "target_query": "후라이팬",
    "diagnosis_family": "spelling_variant",
    "reasoning": "후라이팬은 프라이팬의 비표준 표기다.",
    "synonym_groups": [{"terms": ["프라이팬", "후라이팬"]}],
}

BAD_RX = {
    "target_query": "후라이팬",
    "diagnosis_family": "spelling_variant",
    "reasoning": "팬까지 묶는 과잉 동의어 (기각 유도).",
    "synonym_groups": [{"terms": ["프라이팬", "후라이팬", "팬"]}],
}


def test_accepted_submit_ends_session():
    doctor = FakeDoctor([_submit(GOOD_RX)])
    result = run_doctor_session(_executor(), doctor, "후라이팬")
    assert result.healed and result.attempts == 1 and result.n_turns == 1


def test_rejected_then_corrected():
    """기각 피드백을 받고 좁힌 처방이 채택되는 재시도 흐름."""
    doctor = FakeDoctor([_submit(BAD_RX, "t1"), _submit(GOOD_RX, "t2")])
    executor = _executor()
    result = run_doctor_session(executor, doctor, "후라이팬")
    assert result.healed and result.attempts == 2
    # 두 번째 호출의 히스토리에 기각 피드백(tool_result)이 들어 있다
    second_messages = doctor.seen_messages[1]
    feedback = str(second_messages[-1])
    assert "기각" in feedback and "회귀" in feedback


def test_max_submits_stops_session():
    doctor = FakeDoctor([_submit(BAD_RX, f"t{i}") for i in range(1, 5)])
    result = run_doctor_session(_executor(), doctor, "후라이팬", max_submits=3)
    assert not result.healed
    assert result.attempts == 3  # 4번째 제출 기회는 오지 않는다


def test_text_only_response_ends_session():
    doctor = FakeDoctor(
        [LLMResponse(content=[TextBlock(text="진단 실패, 포기한다.")], stop_reason="end_turn")]
    )
    result = run_doctor_session(_executor(), doctor, "츄리닝")
    assert not result.healed and result.attempts == 0
    assert any("포기" in t for t in result.transcript)


def test_refusal_ends_session():
    doctor = FakeDoctor([LLMResponse(content=[], stop_reason="refusal")])
    result = run_doctor_session(_executor(), doctor, "후라이팬")
    assert not result.healed and result.final_feedback == "모델 거절"


def test_schema_error_returned_as_tool_error_not_crash():
    """스키마 위반 처방은 is_error tool_result로 돌아가 자가 수정 기회가 된다."""
    invalid = {
        "target_query": "후라이팬",
        "diagnosis_family": "spelling_variant",
        "reasoning": "패치 없는 잘못된 처방 제출.",
    }
    doctor = FakeDoctor([_submit(invalid, "t1"), _submit(GOOD_RX, "t2")])
    result = run_doctor_session(_executor(), doctor, "후라이팬")
    assert result.healed
    assert result.attempts == 1  # 스키마 오류는 게이트까지 못 가므로 시도로 안 센다


def test_accepted_patches_accumulate_across_sessions():
    executor = _executor()
    run_doctor_session(executor, FakeDoctor([_submit(GOOD_RX)]), "후라이팬")
    rx2 = {
        "target_query": "티슈",
        "diagnosis_family": "compound_locked",
        "reasoning": "물티슈 통짜 토큰을 분해 확장한다.",
        "compound_expansions": [{"word": "물티슈", "parts": ["물", "티슈"]}],
    }
    run_doctor_session(executor, FakeDoctor([_submit(rx2)]), "티슈")
    assert len(executor.accepted) == 2
    # 누적: 두 패치가 모두 살아 있는 설정
    assert executor.engine.config.synonym_groups
    assert executor.engine.config.compound_expansions
