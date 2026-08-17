"""검색 품질 회귀를 **CI가** 잡게 한다 — 게이트를 커밋 단위로.

진료 중의 회귀 게이트(`patch/gate.py`)는 **처방 하나**를 판정한다. 그런데
이 저장소에는 처방을 거치지 않고 검색 품질을 바꿀 수 있는 것들이 있다:

    코퍼스 문서를 고친다          → 정답이 있던 문서가 사라지거나 표기가 바뀐다
    분석기 기본 설정을 손댄다      → 모든 질의의 토큰이 달라진다
    BM25 상수를 조정한다          → 순위가 통째로 흔들린다
    사전·동의어를 손으로 추가한다  → 게이트를 우회한 그 수정이 정확히 현업의 사고다

이것들은 처방이 아니므로 게이트가 보지 않는다. **게이트가 지키는 것과
저장소가 바뀌는 경로가 어긋나 있다.** 그 틈을 CI로 메운다: 기준선을 저장소에
커밋해 두고, 매 푸시마다 평가셋을 재실행해 질의별로 대조한다.

전수 재실행이 처방을 판정하는 것과 **같은 기준(ε=0.02)**을 커밋에 적용하는
것이므로, 새 개념이 아니라 같은 원리를 한 층 위에 올린 것이다.

## 왜 평균이 아니라 질의별인가

평균만 보면 한 질의가 무너지고 다른 질의가 좋아졌을 때 상쇄돼 보이지 않는다.
회귀 게이트가 질의별로 보는 것과 같은 이유이고, 실제로 이 프로젝트에서
`팬` 동의어가 `팬미팅 굿즈`를 망가뜨린 것도 평균으로는 안 보였다.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from searchclinic.corpus.evalset import EvalQuery
from searchclinic.evaluation.metrics import evaluate_all, mean_ndcg
from searchclinic.index.engine import SearchEngine

# 진료 게이트와 같은 허용치. 서로 다른 값을 쓰면 "게이트는 통과했는데 CI가
# 막는" 상태가 생기고, 그 순간 둘 중 하나는 아무도 안 믿게 된다.
EPSILON = 0.02

# 대조하는 지표. nDCG만 보면 정답 아래에 쌓이는 쓰레기를 놓친다 —
# precision5가 그것을 잡는다.
METRICS = ("ndcg", "recall", "precision5")

BASELINE_PATH = Path("docs/BASELINE.json")


@dataclass(frozen=True)
class Drift:
    """기준선과 어긋난 한 건."""

    query: str
    metric: str
    baseline: float
    current: float

    @property
    def delta(self) -> float:
        return round(self.current - self.baseline, 4)

    def describe(self) -> str:
        arrow = "↓" if self.delta < 0 else "↑"
        return f"'{self.query}' {self.metric} {self.baseline:.2f} → {self.current:.2f} ({arrow}{abs(self.delta):.2f})"


@dataclass
class BaselineReport:
    regressions: list[Drift]
    improvements: list[Drift]
    missing: list[str]  # 기준선에 있는데 평가셋에서 사라진 질의
    added: list[str]  # 평가셋에 새로 생겼는데 기준선에 없는 질의
    mean_baseline: float
    mean_current: float

    @property
    def ok(self) -> bool:
        """회귀도 없고 사라진 질의도 없어야 통과.

        **사라진 질의를 통과시키면 안 된다.** 실패하는 질의를 평가셋에서
        지우는 것으로 CI를 초록불로 만들 수 있게 되고, 그러면 이 검사가
        막으려던 바로 그 일이 가능해진다.
        """
        return not self.regressions and not self.missing

    def summary(self) -> str:
        if self.ok:
            head = f"검색 품질 유지 — 평균 nDCG {self.mean_current:.4f}"
            if self.improvements:
                head += f", 개선 {len(self.improvements)}건"
            if self.added:
                head += f", 신규 질의 {len(self.added)}건(기준선 갱신 필요)"
            return head
        lines = [f"검색 품질 회귀 — 평균 nDCG {self.mean_baseline:.4f} → {self.mean_current:.4f}"]
        for d in self.regressions:
            lines.append(f"  - 회귀: {d.describe()}")
        for q in self.missing:
            lines.append(f"  - 사라진 질의: '{q}' (평가셋에서 빠졌다)")
        return "\n".join(lines)

    def markdown(self) -> str:
        """CI 요약에 붙일 표. 로그를 스크롤하지 않고 결과를 보게 한다."""
        status = "✅ 통과" if self.ok else "❌ 회귀"
        lines = [
            f"### 검색 품질 게이트 — {status}",
            "",
            f"- 평균 nDCG@10: **{self.mean_baseline:.4f} → {self.mean_current:.4f}**",
            f"- 회귀 {len(self.regressions)}건 · 개선 {len(self.improvements)}건",
        ]
        if self.missing:
            lines.append(f"- **사라진 질의 {len(self.missing)}건** — 평가셋에서 빠졌다")
        if self.added:
            lines.append(f"- 신규 질의 {len(self.added)}건 — `clinic baseline --write`로 기준선을 갱신하라")

        rows = [("❌", d) for d in self.regressions] + [("✅", d) for d in self.improvements]
        if rows:
            lines += ["", "| | 질의 | 지표 | 기준선 | 현재 | 변화 |", "|---|---|---|---|---|---|"]
            for mark, d in rows:
                lines.append(
                    f"| {mark} | {d.query} | {d.metric} | {d.baseline:.2f} | "
                    f"{d.current:.2f} | {d.delta:+.2f} |"
                )
        return "\n".join(lines)


def measure(engine: SearchEngine, evalset: list[EvalQuery]) -> dict:
    """지금 상태의 기준선 값을 만든다."""
    metrics = evaluate_all(engine, evalset)
    return {
        "epsilon": EPSILON,
        "mean_ndcg": mean_ndcg(metrics),
        "queries": {
            q: {m: getattr(metrics[q], m) for m in METRICS} | {"n_results": metrics[q].n_results}
            for q in sorted(metrics)
        },
    }


def write_baseline(
    engine: SearchEngine, evalset: list[EvalQuery], path: Path | str = BASELINE_PATH
) -> dict:
    payload = measure(engine, evalset)
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return payload


def load_baseline(path: Path | str = BASELINE_PATH) -> dict:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def compare(
    engine: SearchEngine,
    evalset: list[EvalQuery],
    baseline: dict,
    epsilon: float = EPSILON,
) -> BaselineReport:
    """현재 상태를 기준선과 질의별로 대조한다."""
    current = measure(engine, evalset)
    base_q, cur_q = baseline["queries"], current["queries"]

    regressions: list[Drift] = []
    improvements: list[Drift] = []
    for query in sorted(set(base_q) & set(cur_q)):
        for metric in METRICS:
            bv = base_q[query].get(metric)
            cv = cur_q[query].get(metric)
            if bv is None or cv is None:
                continue
            if cv < bv - epsilon:
                regressions.append(Drift(query, metric, bv, cv))
            elif cv > bv + epsilon:
                improvements.append(Drift(query, metric, bv, cv))

    return BaselineReport(
        regressions=regressions,
        improvements=improvements,
        missing=sorted(set(base_q) - set(cur_q)),
        added=sorted(set(cur_q) - set(base_q)),
        mean_baseline=baseline.get("mean_ndcg", 0.0),
        mean_current=current["mean_ndcg"],
    )
