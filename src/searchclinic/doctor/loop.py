"""진료 루프 — 실패 질의 하나에 대한 의사의 도구 사용 세션.

Messages API 규약을 정확히 따르는 수동 tool-use 루프:
- assistant 응답의 content 전체를 그대로 히스토리에 추가 (thinking 보존)
- 한 턴의 모든 tool_use에 대한 tool_result를 하나의 user 메시지로 반환
- 처방이 채택되면 종료. 기각 피드백은 tool_result로 돌아가 재시도를 유도
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field

from searchclinic.doctor.llm import LLMClient, LLMResponse, ToolUseBlock
from searchclinic.doctor.prompts import SYSTEM_PROMPT, build_brief
from searchclinic.doctor.tools import SUBMIT_TOOL, ClinicExecutor, build_tool_definitions

MAX_TURNS = 16
MAX_SUBMITS = 3


@dataclass
class SessionResult:
    query: str
    healed: bool
    attempts: int  # submit 횟수
    n_turns: int
    diagnosis_family: str | None = None
    patch_kinds: tuple[str, ...] = ()
    final_feedback: str = ""
    transcript: list[str] = field(default_factory=list)  # 사람이 읽는 진료 기록


def run_doctor_session(
    executor: ClinicExecutor,
    llm: LLMClient,
    query: str,
    max_turns: int = MAX_TURNS,
    max_submits: int = MAX_SUBMITS,
) -> SessionResult:
    executor.start_session()
    tools = build_tool_definitions()
    n_before = executor._tool_search_products(query)["total"]
    messages: list[dict] = [
        {"role": "user", "content": build_brief(query, n_before)}
    ]
    result = SessionResult(query=query, healed=False, attempts=0, n_turns=0)

    for _ in range(max_turns):
        result.n_turns += 1
        response: LLMResponse = llm.create(
            system=SYSTEM_PROMPT, messages=messages, tools=tools
        )
        if response.stop_reason == "refusal":
            result.final_feedback = "모델 거절"
            break

        # 히스토리에는 SDK 원본 블록을 그대로 되돌린다 (thinking 블록 보존)
        messages.append({"role": "assistant", "content": response.history_content})
        tool_uses = [b for b in response.content if isinstance(b, ToolUseBlock)]
        for block in response.content:
            if getattr(block, "type", "") == "text" and block.text.strip():
                result.transcript.append(f"[의사] {block.text.strip()}")

        if not tool_uses:
            break  # 도구 없이 끝냄 = 포기 선언

        tool_results = []
        session_done = False
        for tu in tool_uses:
            content, is_error = executor.execute(tu.name, tu.input)
            tool_results.append(
                {
                    "type": "tool_result",
                    "tool_use_id": tu.id,
                    "content": content,
                    "is_error": is_error,
                }
            )
            if tu.name == SUBMIT_TOOL:
                # 처방은 진료의 결론이다 — 잘라서 보여주면 무엇을 처방했는지
                # 확인할 수 없다. 진단·근거·패치를 전부 남긴다.
                result.transcript.append(
                    f"[처방] 계열={tu.input.get('diagnosis_family', '?')}"
                )
                if tu.input.get("reasoning"):
                    result.transcript.append(f"  근거: {tu.input['reasoning']}")
                for w in tu.input.get("user_words") or []:
                    result.transcript.append(f"  · 사전등록: {w.get('form')}")
                for g in tu.input.get("synonym_groups") or []:
                    result.transcript.append(f"  · 동의어: {' = '.join(g.get('terms', []))}")
                for c in tu.input.get("compound_expansions") or []:
                    result.transcript.append(
                        f"  · 분해확장: {c.get('word')} → {'+'.join(c.get('parts', []))}"
                    )
            else:
                result.transcript.append(
                    f"[도구:{tu.name}] {json.dumps(tu.input, ensure_ascii=False)[:200]}"
                )
            if tu.name == SUBMIT_TOOL and not is_error:
                payload = json.loads(content)
                result.attempts += 1
                result.diagnosis_family = tu.input.get("diagnosis_family")
                result.final_feedback = payload["feedback"]
                result.transcript.append(f"[게이트] {payload['feedback']}")
                if payload["accepted"]:
                    result.healed = True
                    result.patch_kinds = executor.accepted[-1].prescription.patch_kinds
                    session_done = True
                elif result.attempts >= max_submits:
                    session_done = True  # 기각 한도 초과

        messages.append({"role": "user", "content": tool_results})
        if session_done:
            break

    return result
