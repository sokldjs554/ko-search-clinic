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


def make_doctor(engine: str) -> LLMClient:
    if engine == "scripted":
        return ScriptedDoctor()
    if engine == "claude":
        return AnthropicLLM()
    raise ValueError(f"알 수 없는 의사 엔진: {engine} (사용 가능: scripted, claude)")


__all__ = [
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
