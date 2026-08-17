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
from searchclinic.doctor.prompts import PROMPT_VARIANTS, SYSTEM_PROMPT, build_brief
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
    # RAG로 돌렸을 때 이 진료에 붙은 지식 문서. 진단이 틀렸을 때 "못 찾은
    # 것"과 "찾았는데 못 쓴 것"을 가르려면 무엇이 붙었는지 남아 있어야 한다.
    retrieved_docs: tuple[str, ...] = ()


def run_doctor_session(
    executor: ClinicExecutor,
    llm: LLMClient,
    query: str,
    max_turns: int = MAX_TURNS,
    max_submits: int = MAX_SUBMITS,
    prompt_variant: str = "full",
    retriever=None,
    top_k: int = 3,
) -> SessionResult:
    """실패 질의 하나를 진료한다.

    `prompt_variant`와 `retriever`가 지식을 어디서 얻을지를 정한다:

        full,    retriever=None  → 지식이 시스템 프롬프트에 박혀 있다 (기본)
        minimal, retriever=None  → 지식이 없다 (대조군)
        minimal, retriever=있음  → 지식을 **검색해서** 브리핑에 붙인다 (RAG)

    셋을 같은 도구·같은 게이트·같은 평가셋에서 돌려야 "검색이 프롬프트를
    대체하는가"에 답할 수 있다.
    """
    if not any(q.query == query for q in executor.evalset):
        raise ValueError(
            f"평가셋에 없는 질의: '{query}'. 채점할 정답이 없으므로 진료할 수 없다. "
            f"사용 가능: {', '.join(q.query for q in executor.evalset)}"
        )
    if prompt_variant not in PROMPT_VARIANTS:
        raise ValueError(
            f"알 수 없는 프롬프트: {prompt_variant} (가능: {', '.join(PROMPT_VARIANTS)})"
        )

    executor.start_session(query)
    tools = build_tool_definitions()
    n_before = executor._tool_search_products(query)["total"]
    system = PROMPT_VARIANTS[prompt_variant]

    knowledge = ""
    if retriever is not None:
        # 검색은 **증상**으로 한다. 정답 계열을 질의로 쓰면 답을 흘리는 것이다.
        from searchclinic.rag.evaluate import build_retrieval_query
        from searchclinic.rag.retriever import render_context

        hits = retriever.retrieve(build_retrieval_query(query, executor.engine), k=top_k)
        knowledge = render_context(hits)
        result_docs = [h.doc.doc_id for h in hits]
    else:
        result_docs = []

    messages: list[dict] = [
        {"role": "user", "content": build_brief(query, n_before, knowledge=knowledge)}
    ]
    result = SessionResult(query=query, healed=False, attempts=0, n_turns=0)
    result.retrieved_docs = tuple(result_docs)
    if result_docs:
        result.transcript.append(f"[검색] 참고 문서 {', '.join(result_docs)}")

    for _ in range(max_turns):
        result.n_turns += 1
        response: LLMResponse = llm.create(
            system=system, messages=messages, tools=tools
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
            if is_error:
                # 도구 오류를 기록에 남기지 않으면, 제출이 증발한 것처럼 보여
                # 의사가 원인을 못 찾고 헤맨다 (실측으로 확인된 실패 모드).
                result.transcript.append(f"[오류] {content}")
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
