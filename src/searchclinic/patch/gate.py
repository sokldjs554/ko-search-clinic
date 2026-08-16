"""회귀 게이트 — 처방은 검증을 통과해야만 채택된다.

이 프로젝트의 핵심 주장이 이 파일에 있다. 검색 품질 패치의 무서운 점은
**한 질의를 고치면서 다른 질의를 조용히 망가뜨린다**는 것이다. 동의어
하나가 무관한 문서를 쏟아지게 하고, 사전 항목 하나가 부분어 검색을 끊는다.
사람도 LLM도 이 부작용을 머리로는 다 예측하지 못한다 — 그래서 예측 대신
**전수 재실행**으로 검증한다.

판정 규칙 (전부 만족해야 채택):

1. 표적 개선   : 표적 질의의 nDCG가 min_gain 이상 오른다
2. 무회귀      : 다른 모든 질의에서 nDCG·recall·precision@5 하락이
                 epsilon 이내다 (BM25는 문서빈도 변화로 점수가 미세하게
                 흔들리므로 0이 아니라 epsilon으로 둔다)
3. 전체 보존   : 평가셋 전체 평균 nDCG가 떨어지지 않는다

기각은 실패가 아니라 정보다: 무엇이 얼마나 나빠졌는지(RegressionRecord)를
그대로 돌려줘서 의사가 처방을 좁혀 재시도할 수 있게 한다.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from searchclinic.corpus.evalset import EvalQuery
from searchclinic.evaluation.metrics import (
    QueryMetrics,
    evaluate_all,
    mean_ndcg,
)
from searchclinic.index.engine import SearchEngine
from searchclinic.patch.ir import Prescription

MIN_TARGET_GAIN = 0.05  # 표적 질의가 최소 이만큼은 좋아져야 한다
EPSILON = 0.02  # 문서빈도 변화에 의한 점수 흔들림 허용치


@dataclass(frozen=True)
class RegressionRecord:
    query: str
    metric: str  # "ndcg" | "recall" | "precision5"
    before: float
    after: float

    @property
    def delta(self) -> float:
        return round(self.after - self.before, 4)

    def describe(self) -> str:
        return f"'{self.query}' {self.metric} {self.before:.2f} → {self.after:.2f}"


@dataclass
class GateVerdict:
    accepted: bool
    reason: str
    target_query: str
    target_before: QueryMetrics
    target_after: QueryMetrics
    mean_before: float
    mean_after: float
    regressions: list[RegressionRecord] = field(default_factory=list)

    def feedback(self) -> str:
        """기각 시 의사에게 돌려줄 교정 정보."""
        if self.accepted:
            return (
                f"채택. 표적 '{self.target_query}' nDCG "
                f"{self.target_before.ndcg:.2f} → {self.target_after.ndcg:.2f}, "
                f"회귀 없음."
            )
        lines = [f"기각: {self.reason}"]
        for r in self.regressions[:5]:
            lines.append(f"  - 회귀: {r.describe()}")
        lines.append("처방을 더 좁히거나(대상 항목 축소) 다른 패치 유형을 검토하라.")
        return "\n".join(lines)


def run_gate(
    engine: SearchEngine,
    evalset: list[EvalQuery],
    prescription: Prescription,
    min_gain: float = MIN_TARGET_GAIN,
    epsilon: float = EPSILON,
) -> tuple[GateVerdict, SearchEngine]:
    """처방을 샌드박스에 적용해 전수 검증한다.

    반환: (판정, 샌드박스 엔진). 채택 시 호출자가 샌드박스를 새 현역으로
    승격하면 되고, 기각 시 버리면 그것이 롤백이다 — 별도의 되돌리기가 없다.
    """
    target = next(
        (q for q in evalset if q.query == prescription.target_query), None
    )
    if target is None:
        raise ValueError(f"평가셋에 없는 표적 질의: {prescription.target_query}")

    before = evaluate_all(engine, evalset)
    sandbox = engine.with_config(prescription.apply_to(engine.config))
    after = evaluate_all(sandbox, evalset)

    t_before, t_after = before[target.query], after[target.query]

    # 규칙 2: 무회귀 검사 (표적 제외 전 질의)
    regressions: list[RegressionRecord] = []
    for q in evalset:
        if q.query == target.query:
            continue
        b, a = before[q.query], after[q.query]
        for metric in ("ndcg", "recall", "precision5"):
            bv, av = getattr(b, metric), getattr(a, metric)
            if av < bv - epsilon:
                regressions.append(RegressionRecord(q.query, metric, bv, av))

    mean_b, mean_a = mean_ndcg(before), mean_ndcg(after)

    # 판정
    if t_after.ndcg < t_before.ndcg + min_gain:
        verdict = GateVerdict(
            accepted=False,
            reason=(
                f"표적 질의가 충분히 개선되지 않음 "
                f"(nDCG {t_before.ndcg:.2f} → {t_after.ndcg:.2f}, "
                f"요구 이득 +{min_gain})"
            ),
            target_query=target.query,
            target_before=t_before,
            target_after=t_after,
            mean_before=mean_b,
            mean_after=mean_a,
            regressions=regressions,
        )
    elif regressions:
        verdict = GateVerdict(
            accepted=False,
            reason=f"다른 질의 {len(set(r.query for r in regressions))}건에 회귀 발생",
            target_query=target.query,
            target_before=t_before,
            target_after=t_after,
            mean_before=mean_b,
            mean_after=mean_a,
            regressions=regressions,
        )
    elif mean_a < mean_b - epsilon:
        verdict = GateVerdict(
            accepted=False,
            reason=f"전체 평균 nDCG 하락 ({mean_b:.3f} → {mean_a:.3f})",
            target_query=target.query,
            target_before=t_before,
            target_after=t_after,
            mean_before=mean_b,
            mean_after=mean_a,
            regressions=regressions,
        )
    else:
        verdict = GateVerdict(
            accepted=True,
            reason="표적 개선 + 무회귀 + 전체 보존",
            target_query=target.query,
            target_before=t_before,
            target_after=t_after,
            mean_before=mean_b,
            mean_after=mean_a,
        )
    return verdict, sandbox
