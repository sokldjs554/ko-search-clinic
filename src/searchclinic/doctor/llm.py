"""LLM 추상화 — 진료 루프는 이 프로토콜에만 의존한다.

구현체가 둘이다:
- AnthropicLLM  : Claude Messages API (수동 tool-use 루프)
- ScriptedDoctor: 결정적 휴리스틱 상태 기계 (오프라인 베이스라인)

루프가 같은 인터페이스로 둘을 돌리므로 "에이전트 루프의 정확성"과
"진단 능력"을 분리해서 평가할 수 있다.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Protocol


@dataclass
class TextBlock:
    text: str
    type: str = "text"


@dataclass
class ToolUseBlock:
    id: str
    name: str
    input: dict
    type: str = "tool_use"


@dataclass
class LLMResponse:
    content: list = field(default_factory=list)
    stop_reason: str = "end_turn"
    model: str = ""


class LLMClient(Protocol):
    def create(
        self, *, system: str, messages: list[dict], tools: list[dict]
    ) -> LLMResponse: ...


DEFAULT_MODEL = "claude-opus-5"


class AnthropicLLM:
    """Claude Messages API 클라이언트.

    - claude-opus-5는 adaptive thinking이 기본이라 thinking 파라미터를 보내지
      않고, 샘플링 파라미터도 쓰지 않는다.
    - stop_reason == "refusal"(안전 분류기 거절)을 명시적으로 처리한다.
    """

    def __init__(self, model: str = DEFAULT_MODEL, max_tokens: int = 4096) -> None:
        try:
            import anthropic
        except ImportError as e:
            raise RuntimeError(
                "anthropic 패키지가 필요합니다: pip install 'ko-search-clinic[llm]'"
            ) from e
        if not os.environ.get("ANTHROPIC_API_KEY"):
            raise RuntimeError("ANTHROPIC_API_KEY 환경변수가 설정되지 않았습니다.")
        self._client = anthropic.Anthropic()
        self.model = model
        self.max_tokens = max_tokens

    def create(
        self, *, system: str, messages: list[dict], tools: list[dict]
    ) -> LLMResponse:
        resp = self._client.messages.create(
            model=self.model,
            max_tokens=self.max_tokens,
            system=system,
            messages=messages,
            tools=tools,
        )
        if resp.stop_reason == "refusal":
            return LLMResponse(
                content=[TextBlock(text="(모델이 응답을 거절했습니다)")],
                stop_reason="refusal",
                model=resp.model,
            )
        content: list = []
        for block in resp.content:
            if block.type == "text":
                content.append(TextBlock(text=block.text))
            elif block.type == "tool_use":
                content.append(
                    ToolUseBlock(id=block.id, name=block.name, input=dict(block.input))
                )
            else:  # thinking 블록 등은 히스토리 보존을 위해 원본 유지
                content.append(block)
        return LLMResponse(
            content=content, stop_reason=resp.stop_reason, model=resp.model
        )
