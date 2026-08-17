"""진료 계층 — 도구, 진료 루프, 의사 엔진들."""

from searchclinic.doctor.llm import AnthropicLLM, LLMClient, LLMResponse
from searchclinic.doctor.loop import SessionResult, run_doctor_session
from searchclinic.doctor.scripted import ScriptedDoctor
from searchclinic.doctor.tools import (
    SUBMIT_TOOL,
    AcceptedRecord,
    ClinicExecutor,
    build_tool_definitions,
)


#: 의사 엔진 세 지점. 같은 상태 기계에 자를 하나씩 더 주는 구성이라,
#: 셋의 차이가 곧 "그 자가 무엇을 더 푸는가"가 된다.
ENGINES = ("scripted", "vector", "claude")


def make_doctor(engine: str) -> LLMClient:
    if engine == "scripted":
        return ScriptedDoctor()
    if engine == "vector":
        return ScriptedDoctor(use_vectors=True)
    if engine == "claude":
        return AnthropicLLM()
    raise ValueError(
        f"알 수 없는 의사 엔진: {engine} (사용 가능: {', '.join(ENGINES)})"
    )


__all__ = [
    "ENGINES",
    "LLMClient",
    "LLMResponse",
    "AnthropicLLM",
    "ScriptedDoctor",
    "ClinicExecutor",
    "AcceptedRecord",
    "build_tool_definitions",
    "SUBMIT_TOOL",
    "run_doctor_session",
    "SessionResult",
    "make_doctor",
]
