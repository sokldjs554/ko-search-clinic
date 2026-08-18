"""RulesPlusDoctor — 규칙 의사에 **액션 하나와 재시도**만 더한 대조군.

## 왜 이것을 만들었나

`ScriptedDoctor`(자모 규칙)는 16건 중 10건, `ClaudeDoctor`는 16건 전부를
해결한다. 이 프로젝트는 그 차이를 "같은 도구·같은 게이트·같은 평가셋에서
진단기만 바꿨다"로 설명해 왔다. 그런데 외부 검토에서 이런 반론이 나왔다:

    그 차이는 추론 능력이 아니라 **액션 스페이스와 재시도 예산**의
    차이일 수 있다. 규칙 의사는 `user_words`를 낼 수 없고, 기각당해도
    다시 시도하지 않는다.

반론의 절반은 사실이 아니다. 재시도 **예산**은 원래 같다 — `run_doctor_session`
이 모든 엔진에 `MAX_TURNS=16`, `MAX_SUBMITS=3`을 똑같이 준다. 규칙 의사가
그것을 쓰지 않을 뿐이다.

하지만 나머지 절반은 사실이다. `ScriptedDoctor`에는 `user_words` 처방 경로가
아예 없다. 그래서 `아답터`는 R1이 동의어만 제안하고, 사전 등록이 선행돼야
한다는 것을 모른 채 기각당하고 멈춘다.

**그러면 그 둘을 주면 몇 건이 풀리는가.** 재보기 전에는 알 수 없다.
이 파일이 그 실험이다.

## 무엇을 바꿨고 무엇을 안 바꿨나

바꾼 것은 정확히 둘이다.

1. **2단계 처방** — 질의가 한 음절씩 쪼개졌으면 `user_words`와
   `synonym_groups`를 **한 처방에 함께** 담는다 (`_rule_garbage_split`).
2. **기각 후 재처방** — 후보를 사다리로 쌓고, 게이트가 기각하면 다음 후보를
   던진다. 원래도 있던 제출 예산(3회) 안에서만 움직인다.

바꾸지 않은 것: 도구 4종의 호출 순서, 자모 임계값(0.65), R1·R2·R3의 판정
로직, 게이트, 평가셋. `ScriptedDoctor`를 **상속**하는 이유가 그것이다 —
베이스라인 10/16이 그대로 재현돼야 이 비교가 의미를 갖는다.

## 결과를 어떻게 읽어야 하나

- 10~11건에 머물면 → 차이는 액션·재시도가 아니라 **진단**에 있었다.
- 14~15건으로 오르면 → 차이의 대부분은 **액션 스페이스**였고, 그러면
  "LLM이 무엇을 더 푸는가"는 지금까지 적어온 것보다 좁게 말해야 한다.

**어느 쪽이든 적는다.** 재보지 않은 채로 두는 것이 유일하게 나쁜 선택이다.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from searchclinic.doctor.llm import LLMResponse, TextBlock
from searchclinic.doctor.scripted import MAX_LEN_DIFF, SIM_THRESHOLD, ScriptedDoctor
from searchclinic.doctor.tools import SUBMIT_TOOL


@dataclass
class RulesPlusDoctor(ScriptedDoctor):
    """규칙 의사 + 2단계 처방 + 기각 후 재처방. LLM은 호출하지 않는다."""

    # 이번 세션에서 사다리의 몇 번째까지 던졌는가.
    _tried: int = field(default=0)

    @property
    def _model_name(self) -> str:
        return "rules-plus-doctor"

    def _reset(self, brief: str) -> None:
        super()._reset(brief)
        self._tried = 0

    # ----------------------------------------------------------- 추가 규칙

    def _rule_garbage_split(self) -> dict | None:
        """R4: 질의가 한 음절씩 쪼개졌으면 **사전 등록이 선행돼야** 동의어가 산다.

        `아답터`는 분석기가 [아, 답, 터]로 부순다. 이 상태에서 동의어만 걸면
        규칙이 걸릴 토큰 자체가 없어 게이트가 기각한다. 사전에 원자 토큰으로
        등록해 `아답터`를 한 덩어리로 만든 **다음에야** 동의어가 의미를 갖는다.

        발동 조건을 "모든 질의 토큰이 1글자"로 좁힌 것은 의도적이다. 이
        신호가 없는 질의에까지 사전 등록을 뿌리면, 무엇이 이 규칙 덕분에
        풀렸는지 알 수 없게 된다.
        """
        toks = self._query_tokens
        if len(toks) < 2 or not all(len(t) == 1 for t in toks):
            return None

        whole = self._compact_query
        for cand in self._similar:
            token, sim = cand["token"], cand["similarity"]
            if token == whole or sim < SIM_THRESHOLD:
                continue
            if abs(len(token) - len(whole)) > MAX_LEN_DIFF:
                continue
            return {
                "diagnosis_family": "garbage_split",
                "reasoning": (
                    f"질의가 [{', '.join(toks)}]로 한 음절씩 쪼개졌다. 이 상태에서는 "
                    f"동의어를 걸어도 매칭될 토큰이 없다. '{whole}'를 사전에 등록해 "
                    f"한 덩어리로 만든 뒤, 자모 유사도 {sim:.2f}인 색인 토큰 "
                    f"'{token}'과 동의어로 연결한다."
                ),
                "user_words": [{"form": whole, "tag": "NNP"}],
                "synonym_groups": [{"terms": [token, whole]}],
            }
        return None

    # ----------------------------------------------------------- 처방 사다리

    def _ladder(self) -> list[dict]:
        """제출 후보를 순서대로 쌓는다.

        **R1을 R4보다 앞에 둔다.** 순서를 뒤집으면 "2단계를 먼저 시도해서
        풀었다"가 되어, 측정하려는 것(기각 → 재처방이 무엇을 회수하는가)이
        측정되지 않는다. 규칙 의사가 원래 내던 처방을 그대로 먼저 던지고,
        그것이 기각당한 뒤에 무엇이 회수되는지를 본다.
        """
        out: list[dict] = []
        for rx in (
            self._rule_variant(),
            self._rule_garbage_split(),
            self._rule_compound(),
            self._rule_semantic(),
        ):
            if rx is not None:
                out.append(rx)
        return out

    def _submit_next(self, call) -> LLMResponse:
        ladder = self._ladder()
        if self._tried >= len(ladder):
            if self._tried == 0:
                return self._diagnosis_failed()
            return LLMResponse(
                content=[
                    TextBlock(
                        text=(
                            f"후보 {len(ladder)}건을 모두 던졌고 전부 기각됐다. "
                            "규칙으로 만들 수 있는 처방이 더 없어 중단한다."
                        )
                    )
                ],
                stop_reason="end_turn",
                model=self._model_name,
            )
        rx = dict(ladder[self._tried])
        self._tried += 1
        rx["target_query"] = self._query
        note = (
            "규칙에 따라 처방을 제출한다."
            if self._tried == 1
            else f"기각됐다. 사다리의 {self._tried}번째 후보를 제출한다."
        )
        return call(SUBMIT_TOOL, rx, note)

    # ------------------------------------------------------------ 확장점 구현

    def _first_prescription(self, call) -> LLMResponse:
        return self._submit_next(call)

    def _after_verdict(self, call) -> LLMResponse:
        if (self._verdict or {}).get("accepted"):
            return LLMResponse(
                content=[TextBlock(text="치유 완료.")],
                stop_reason="end_turn",
                model=self._model_name,
            )
        return self._submit_next(call)
