"""ScriptedDoctor — 결정적 휴리스틱 의사 (오프라인 베이스라인).

사람 검색 운영자가 반쯤 기계적으로 하던 두 가지 규칙을 코드로 옮겼다:

  R1 (표기 변형): 질의와 자모 유사도가 높은 색인 토큰이 있으면 동의어로 연결
  R2 (복합어)   : 색인 토큰 중 질의 토큰을 접두/접미로 포함하는 것이 있으면
                  분해 확장

이 두 규칙이 못 푸는 것이 곧 이 베이스라인의 한계이며, 그 한계가 LLM
의사의 존재 이유를 측정 가능하게 만든다:

- 영한 혼용(블루투스↔Bluetooth): 자모 유사도가 문자 체계를 넘지 못한다
- 유의어(츄리닝↔트레이닝복): 형태가 다른 같은 뜻은 형태 규칙으로 못 잇는다
- 쓰레기 분해(아답터→[아,답,터]): R1이 동의어를 제안하지만, 사전 등록이
  선행돼야 한다는 것을 모른다 → 게이트가 기각하고, 재진단 능력이 없다

LLMClient 프로토콜을 구현하므로 진료 루프는 이 엔진과 Claude를 같은
코드로 돌린다.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field

from searchclinic.doctor.llm import LLMResponse, TextBlock, ToolUseBlock
from searchclinic.doctor.tools import SUBMIT_TOOL

SIM_THRESHOLD = 0.65  # 자모 유사도 하한 (실측: 케잌↔케이크 0.67, 도너츠↔도넛 0.67)
MAX_LEN_DIFF = 2


@dataclass
class ScriptedDoctor:
    """상태 기계 의사. 세션(첫 user 메시지 하나)마다 상태를 초기화한다."""

    _step: int = 0
    _query: str = ""
    _search_total: int = -1
    _query_tokens: list[str] = field(default_factory=list)
    _grep_total: int = -1
    _similar: list[dict] = field(default_factory=list)
    _verdict: dict | None = None

    def _reset(self, brief: str) -> None:
        self._step = 0
        m = re.search(r'실패 질의: "(.+?)"', brief)
        self._query = m.group(1) if m else brief.strip()
        self._search_total = -1
        self._query_tokens = []
        self._grep_total = -1
        self._similar = []
        self._verdict = None

    # ------------------------------------------------------------ 결과 흡수

    def _absorb(self, content: str) -> None:
        try:
            data = json.loads(content)
        except (json.JSONDecodeError, TypeError):
            return
        if not isinstance(data, dict):
            return
        if "results" in data:
            self._search_total = data.get("total", 0)
        elif "tokens" in data:
            self._query_tokens = [
                t["token"] for t in data["tokens"] if t.get("origin") == "kiwi"
            ]
        elif "documents" in data:
            self._grep_total = data.get("total", 0)
        elif "similar" in data:
            self._similar = data["similar"]
        elif "accepted" in data:
            self._verdict = data

    # ------------------------------------------------------------ 휴리스틱

    @property
    def _compact_query(self) -> str:
        return self._query.replace(" ", "")

    @property
    def _probe(self) -> str:
        """유사 토큰 탐색 기준어.

        다단어 질의면 첫 내용어 토큰(예: '케잌 주문' → '케잌'), 아니면 질의
        전체. 쓰레기 분해된 질의(아답터→[아,답,터])는 토큰이 전부 1글자라
        걸러지고 질의 전체로 되돌아간다.
        """
        candidates = [t for t in self._query_tokens if len(t) >= 2]
        if len(self._query_tokens) >= 2 and candidates:
            return candidates[0]
        return self._compact_query

    def _rule_variant(self) -> dict | None:
        """R1: 자모 유사 색인 토큰 → 동의어 (색인 토큰이 대표형)."""
        for cand in self._similar:
            token, sim = cand["token"], cand["similarity"]
            if (
                sim >= SIM_THRESHOLD
                and abs(len(token) - len(self._probe)) <= MAX_LEN_DIFF
                and token != self._probe
            ):
                return {
                    "diagnosis_family": "spelling_variant",
                    "reasoning": (
                        f"'{self._probe}'와 자모 유사도 {sim:.2f}인 색인 토큰 "
                        f"'{token}'이 존재한다. 표기 변형으로 판단해 동의어로 연결한다."
                    ),
                    "synonym_groups": [{"terms": [token, self._probe]}],
                }
        return None

    def _rule_compound(self) -> dict | None:
        """R2: 질의 토큰을 접두/접미로 포함하는 색인 토큰 → 분해 확장."""
        probes = [t for t in self._query_tokens if len(t) >= 2] or [self._compact_query]
        for cand in self._similar:
            token = cand["token"]
            for part in probes:
                if token == part or len(token) <= len(part):
                    continue
                if token.endswith(part):
                    parts = [token[: -len(part)], part]
                elif token.startswith(part):
                    parts = [part, token[len(part):]]
                else:
                    continue
                return {
                    "diagnosis_family": "compound_locked",
                    "reasoning": (
                        f"색인 토큰 '{token}'이 질의 토큰 '{part}'를 포함하는 "
                        f"복합어다. 통짜 색인이라 부분어로 못 찾으므로 분해 확장한다."
                    ),
                    "compound_expansions": [{"word": token, "parts": parts}],
                }
        return None

    # ------------------------------------------------------------ LLMClient

    def create(
        self, *, system: str, messages: list[dict], tools: list[dict]
    ) -> LLMResponse:
        if len(messages) == 1:
            self._reset(messages[0]["content"])
        last = messages[-1] if messages else {}
        content = last.get("content")
        if isinstance(content, list):
            for tr in content:
                if isinstance(tr, dict) and tr.get("type") == "tool_result" and not tr.get("is_error"):
                    self._absorb(tr.get("content", ""))

        self._step += 1
        step = self._step

        def call(name: str, tool_input: dict, note: str) -> LLMResponse:
            return LLMResponse(
                content=[
                    TextBlock(text=note),
                    ToolUseBlock(id=f"scripted-{step}", name=name, input=tool_input),
                ],
                stop_reason="tool_use",
                model="scripted-doctor",
            )

        if step == 1:
            return call("search_products", {"query": self._query}, "현재 검색 상태를 확인한다.")
        if step == 2:
            return call("analyze_text", {"text": self._query}, "질의 토큰 분해를 확인한다.")
        if step == 3:
            return call("grep_documents", {"text": self._compact_query}, "원문에 존재하는지 대조한다.")
        if step == 4:
            return call(
                "find_similar_tokens",
                {"term": self._probe, "k": 8},
                "색인 어휘에서 유사 토큰을 찾는다.",
            )
        if step == 5:
            rx = self._rule_variant() or self._rule_compound()
            if rx is None:
                return LLMResponse(
                    content=[
                        TextBlock(
                            text=(
                                "진단 실패: 자모 유사 토큰도, 포함 관계 복합어도 없다. "
                                "이 계열(영한 혼용·유의어 등)은 형태 규칙으로 풀 수 없다."
                            )
                        )
                    ],
                    stop_reason="end_turn",
                    model="scripted-doctor",
                )
            rx["target_query"] = self._query
            return call(SUBMIT_TOOL, rx, "규칙에 따라 처방을 제출한다.")

        # step 6: 판정 확인 후 종료 (기각돼도 재진단 능력이 없다 — 설계된 한계)
        text = "치유 완료." if (self._verdict or {}).get("accepted") else "처방이 기각됐다. 규칙 기반으로는 더 좁힐 수 없어 중단한다."
        return LLMResponse(content=[TextBlock(text=text)], stop_reason="end_turn", model="scripted-doctor")
