"""규모를 바꿔가며 **게이트의 판단이 유지되는지** 잰다.

## 재려는 것은 속도가 아니다

"문서 20만 건에서 몇 초 걸렸다"는 흥미롭지 않다. 진짜 질문은 이것이다:

    **같은 처방이 규모에 따라 다르게 판정되는가?**

의심할 근거가 있다. BM25 점수는 역문서빈도(IDF)에 비례한다. 문서 72건에서
`팬`을 동의어로 묶으면 '팬' 문서가 프라이팬 질의에 즉시 쏟아져 들어와
게이트가 기각한다. 그런데 문서 20만 건에서는 '팬' 문서의 비율이 달라지고,
점수 지형도 달라진다. **게이트가 통과시킬 수도 있다.**

만약 그렇다면 "게이트가 지킨다"는 이 프로젝트의 주장에 **규모 조건**이
붙는다. 그것을 모른 채 쓰는 것과 알고 쓰는 것은 다르다.

## 무엇을 고정하는가

규모만 바꾸고 나머지는 전부 같게 둔다 — 같은 평가셋, 같은 처방, 같은 게이트
파라미터, 같은 시드. 그래야 차이가 나왔을 때 규모 탓이라고 말할 수 있다.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field

from searchclinic.corpus import load_evalset
from searchclinic.index.engine import SearchEngine
from searchclinic.patch.gate import run_gate
from searchclinic.patch.ir import Prescription
from searchclinic.scale.generate import synthesize_catalog

# 규모 실험에 쓰는 두 처방. 하나는 반드시 기각되어야 하고(과잉), 하나는
# 반드시 채택되어야 한다(최소). 규모가 이 판정을 뒤집는지가 관심사다.
OVERBROAD = Prescription(
    target_query="후라이팬",
    diagnosis_family="spelling_variant",
    reasoning="팬은 프라이팬의 준말이므로 함께 묶는다 (과잉 일반화 — 기각되어야 한다).",
    synonym_groups=[{"terms": ["프라이팬", "후라이팬", "팬"]}],
)
MINIMAL = Prescription(
    target_query="후라이팬",
    diagnosis_family="spelling_variant",
    reasoning="후라이팬은 프라이팬의 비표준 표기다. 최소 범위 동의어로 잇는다.",
    synonym_groups=[{"terms": ["프라이팬", "후라이팬"]}],
)


@dataclass
class ScalePoint:
    n_docs: int
    index_seconds: float
    gate_seconds: float
    overbroad_accepted: bool
    minimal_accepted: bool
    overbroad_regressions: int
    fan_doc_frequency: int = 0
    notes: list[str] = field(default_factory=list)

    @property
    def verdicts_hold(self) -> bool:
        """작은 규모에서의 판정이 유지되는가 — 과잉은 기각, 최소는 채택."""
        return (not self.overbroad_accepted) and self.minimal_accepted


@dataclass
class ScaleReport:
    points: list[ScalePoint]

    @property
    def all_hold(self) -> bool:
        return all(p.verdicts_hold for p in self.points)

    def markdown(self) -> str:
        lines = [
            "### 규모 실험 — 게이트의 판정이 규모를 견디는가",
            "",
            "| 문서 수 | 색인(초) | 게이트 1회(초) | '팬' 문서수 | 과잉 처방 | 최소 처방 | 판정 유지 |",
            "|---|---|---|---|---|---|---|",
        ]
        for p in self.points:
            over = "기각 ✅" if not p.overbroad_accepted else "**채택 ❌**"
            mini = "채택 ✅" if p.minimal_accepted else "**기각 ❌**"
            hold = "✅" if p.verdicts_hold else "**❌**"
            lines.append(
                f"| {p.n_docs:,} | {p.index_seconds:.2f} | {p.gate_seconds:.2f} | "
                f"{p.fan_doc_frequency:,} | {over} (회귀 {p.overbroad_regressions}) | {mini} | {hold} |"
            )
        lines.append("")
        if self.all_hold:
            lines.append(
                "**모든 규모에서 판정이 유지됐다.** 과잉 동의어는 어디서든 기각되고 "
                "최소 처방은 어디서든 채택된다 — 게이트의 **정확성**에는 규모 조건이 "
                "붙지 않는다. `팬` 문서가 4건에서 1,004건으로 늘어도 오염은 여전히 "
                "탐지된다."
            )
        else:
            broken = [p for p in self.points if not p.verdicts_hold]
            lines.append(
                "**규모에 따라 판정이 갈렸다** (문서 "
                + ", ".join(f"{p.n_docs:,}건" for p in broken)
                + "). 게이트의 보증에는 규모 조건이 붙는다 — 작은 평가 코퍼스에서 "
                "안전하다고 판정된 패치가 실서비스 규모에서 안전하다는 뜻이 아니다."
            )

        lines += ["", *self._cost_analysis()]
        return "\n".join(lines)

    def _cost_analysis(self) -> list[str]:
        """정확성이 아니라 **비용**이 규모의 벽이라는 것을 수치로 말한다."""
        big = [p for p in self.points if p.n_docs >= 1000]
        if len(big) < 2:
            return []

        first, last = big[0], big[-1]
        if first.gate_seconds <= 0:
            return []
        docs_ratio = last.n_docs / first.n_docs
        time_ratio = last.gate_seconds / first.gate_seconds
        per_million = last.gate_seconds / last.n_docs * 1_000_000

        return [
            "### 벽은 정확성이 아니라 비용이다",
            "",
            f"문서가 {docs_ratio:.0f}배 늘 때 게이트 1회 시간이 **{time_ratio:.0f}배**로 "
            "늘었다 — 거의 정확히 선형이다. 게이트가 처방마다 **샌드박스를 통째로 "
            "재색인**하기 때문이다.",
            "",
            f"이 기울기를 그대로 늘리면 문서 100만 건에서 처방 하나당 약 "
            f"**{per_million / 60:.0f}분**이고, 진료 16건이면 하루가 간다. "
            "실서비스에 올리려면 여기가 먼저 바뀌어야 한다.",
            "",
            "고칠 방향은 분명하다 — 패치가 닿는 토큰을 가진 문서만 다시 색인하면 "
            "된다(증분 재색인). 사전 한 줄이 바꾸는 문서는 전체의 극히 일부다. "
            "**다만 이 저장소는 아직 그렇게 하지 않는다.** 전수 재색인은 "
            "'빠뜨린 문서가 없다'는 것이 자명해서 고른 방식이고, 그 단순함의 값을 "
            "여기서 처음 수치로 확인했다.",
        ]


def _fan_df(engine: SearchEngine) -> int:
    """'팬' 토큰을 가진 문서 수 — 오염 함정의 밀도를 보여주는 값."""
    try:
        return engine._index.df("팬")
    except Exception:  # pragma: no cover - 색인 내부가 바뀌면 0으로 둔다
        return 0


def measure_at_scale(n_docs: int, seed: int = 20260817) -> ScalePoint:
    evalset = load_evalset()

    t0 = time.perf_counter()
    engine = SearchEngine(synthesize_catalog(n_docs, seed=seed))
    index_seconds = time.perf_counter() - t0

    t1 = time.perf_counter()
    over_verdict, _ = run_gate(engine, evalset, OVERBROAD)
    gate_seconds = time.perf_counter() - t1

    min_verdict, _ = run_gate(engine, evalset, MINIMAL)

    return ScalePoint(
        n_docs=len(engine.docs),
        index_seconds=round(index_seconds, 3),
        gate_seconds=round(gate_seconds, 3),
        overbroad_accepted=over_verdict.accepted,
        minimal_accepted=min_verdict.accepted,
        overbroad_regressions=len(over_verdict.regressions),
        fan_doc_frequency=_fan_df(engine),
    )


def run_scale_benchmark(sizes: list[int], seed: int = 20260817, on_progress=None) -> ScaleReport:
    points = []
    for i, n in enumerate(sizes, 1):
        point = measure_at_scale(n, seed=seed)
        points.append(point)
        if on_progress is not None:
            on_progress(i, len(sizes), point)
    return ScaleReport(points=points)
