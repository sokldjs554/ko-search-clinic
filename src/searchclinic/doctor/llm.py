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
    """한 턴의 모델 응답.

    content와 raw_content를 나누는 이유가 중요하다. 진료 루프는 정규화된
    블록(content)으로 판단하지만, **대화 히스토리에 되돌려 넣을 때는 SDK가
    준 원본 블록(raw_content)을 그대로 써야 한다.** 우리 dataclass를 그대로
    messages에 넣으면 SDK가 직렬화하지 못하고, thinking 블록도 유실된다
    (Claude Opus 5는 thinking 블록을 변형 없이 되돌려받아야 한다).
    """

    content: list = field(default_factory=list)
    stop_reason: str = "end_turn"
    model: str = ""
    raw_content: list | None = None  # API에 되돌려줄 원본 블록 (없으면 content 사용)

    @property
    def history_content(self) -> list:
        return self.raw_content if self.raw_content is not None else self.content


class LLMClient(Protocol):
    def create(
        self, *, system: str, messages: list[dict], tools: list[dict]
    ) -> LLMResponse: ...


DEFAULT_MODEL = "claude-opus-5"


class AnthropicLLM:
    """Claude Messages API 클라이언트 (수동 tool-use 루프용).

    claude-opus-5 기준 주의점:

    - **thinking이 기본 활성이다.** thinking 파라미터를 보내지 않으면 adaptive
      thinking이 돈다. 그리고 `max_tokens`는 thinking + 응답 텍스트를 **합쳐서**
      제한하므로, 4096처럼 빠듯하게 잡으면 답변이 중간에 잘린다. 기본값을
      넉넉히(16000) 잡되 상한일 뿐이라 실제 사용량만 과금된다.
    - 샘플링 파라미터(temperature/top_p/top_k)는 거부되므로 보내지 않는다.
    - `stop_reason == "refusal"`(안전 분류기 거절)을 명시적으로 처리한다.
      서버측 `fallbacks` 파라미터로 자동 대체 모델을 쓸 수도 있지만, 베타
      헤더 의존이 생기고 이 프로젝트의 질의(한국어 상품 검색)는 거절 위험이
      사실상 없어 넣지 않았다. 거절 시에는 그대로 표면화한다.
    - 응답 블록은 **원본 그대로** 히스토리에 돌려준다(raw_content). thinking
      블록을 변형하면 API가 거부한다.
    """

    def __init__(
        self,
        model: str = DEFAULT_MODEL,
        max_tokens: int = 16000,
        effort: str = "high",
    ) -> None:
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
        self.effort = effort

    def create(
        self, *, system: str, messages: list[dict], tools: list[dict]
    ) -> LLMResponse:
        resp = self._client.messages.create(
            model=self.model,
            max_tokens=self.max_tokens,
            output_config={"effort": self.effort},
            system=system,
            messages=messages,
            tools=tools,
        )
        if resp.stop_reason == "refusal":
            return LLMResponse(
                content=[TextBlock(text="(모델이 응답을 거절했습니다)")],
                stop_reason="refusal",
                model=resp.model,
                raw_content=list(resp.content),
            )
        # 정규화된 뷰(루프 판단용)와 원본(히스토리 반환용)을 따로 만든다
        content: list = []
        for block in resp.content:
            if block.type == "text":
                content.append(TextBlock(text=block.text))
            elif block.type == "tool_use":
                content.append(
                    ToolUseBlock(id=block.id, name=block.name, input=dict(block.input))
                )
        return LLMResponse(
            content=content,
            stop_reason=resp.stop_reason,
            model=resp.model,
            raw_content=list(resp.content),
        )
