"""진료 계층 — 도구, 진료 루프, 의사 엔진들."""

from searchclinic.doctor.llm import AnthropicLLM, LLMClient, LLMResponse
from searchclinic.doctor.loop import SessionResult, run_doctor_session
from searchclinic.doctor.rules_plus import RulesPlusDoctor
from searchclinic.doctor.scripted import ScriptedDoctor
from searchclinic.doctor.tools import (
    SUBMIT_TOOL,
    AcceptedRecord,
    ClinicExecutor,
    build_tool_definitions,
)


#: 의사 엔진 네 지점. 같은 상태 기계에 자를 하나씩 더 주는 구성이라,
#: 넷의 차이가 곧 "그 자가 무엇을 더 푸는가"가 된다.
#:
#: `rules+`만 성격이 다르다. 자를 더한 것이 아니라 **액션 하나(user_words)와
#: 기각 후 재처방**을 더한 것이고, "LLM이 이긴 것이 추론인가 액션인가"를
#: 가르기 위한 대조군이다 (`rules_plus.py` 참조).
ENGINES = ("scripted", "rules+", "vector", "vector+", "claude")

#: 임베딩 캐시가 필요한 엔진. **엔진 이름으로 판단하지 말 것.**
#: `vector+`를 추가했을 때 세 곳에 흩어져 있던 `engine == "vector"` 검사가
#: 조용히 빗나가, 캐시 없이 돈 결과가 "벡터를 켜고 잰 값"으로 기록될 뻔했다.
#: 실측으로 겪었고 `test_vector_engines_is_the_single_source`가 이 줄을 지킨다.
VECTOR_ENGINES = ("vector", "vector+")


def make_doctor(engine: str) -> LLMClient:
    if engine == "scripted":
        return ScriptedDoctor()
    if engine == "rules+":
        return RulesPlusDoctor()
    if engine == "vector":
        return ScriptedDoctor(use_vectors=True)
    if engine == "vector+":
        # 비-LLM으로 만들 수 있는 가장 강한 팔 — 자모 + 임베딩 + 2단계 + 재시도.
        # 이것과 claude의 격차가 곧 "규칙으로는 도달할 수 없는 부분"이다.
        return RulesPlusDoctor(use_vectors=True)
    if engine == "claude":
        return AnthropicLLM()
    raise ValueError(
        f"알 수 없는 의사 엔진: {engine} (사용 가능: {', '.join(ENGINES)})"
    )


__all__ = [
    "ENGINES",
    "VECTOR_ENGINES",
    "LLMClient",
    "LLMResponse",
    "AnthropicLLM",
    "ScriptedDoctor",
    "RulesPlusDoctor",
    "ClinicExecutor",
    "AcceptedRecord",
    "build_tool_definitions",
    "SUBMIT_TOOL",
    "run_doctor_session",
    "SessionResult",
    "make_doctor",
]
