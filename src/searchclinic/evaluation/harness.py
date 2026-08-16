"""평가 하니스 — 의사를 전체 실패 질의에 투입하고 정량 채점한다.

채점 항목:

| 항목          | 방식                                | 잡아내는 실패                  |
|---------------|-------------------------------------|--------------------------------|
| 치유율        | 게이트 채택 여부                    | 못 고침                        |
| 진단 정확도   | 진단 계열 vs 정답 계열 라벨         | 고쳤지만 이유를 잘못 앎        |
| 처방 적합성   | 패치 유형 vs 정답 처방 유형         | 우연히 맞는 엉뚱한 처방        |
| 제로결과율    | 실패셋 0건 질의 비율 전/후          | 아예 못 찾는 질의              |
| 실패셋 nDCG   | 실패 질의 평균 nDCG 전/후           | 순위 품질                      |
| 건강셋 회귀   | 건강 질의 지표 하락 여부            | 게이트가 놓친 부작용 (0이어야) |

치유율만 보면 "우연히 고침"과 "이해하고 고침"이 구분되지 않는다.
진단 정확도와 처방 적합성이 그 구분을 만든다.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from searchclinic.corpus.catalog import load_catalog
from searchclinic.corpus.evalset import failing_queries, healthy_queries, load_evalset
from searchclinic.evaluation.metrics import (
    QueryMetrics,
    evaluate_all,
    mean_ndcg,
    zero_result_rate,
)
from searchclinic.index.engine import SearchEngine

if TYPE_CHECKING:  # 순환 임포트 방지: doctor 계층은 실행 시점에만 불러온다
    from searchclinic.doctor.llm import LLMClient
    from searchclinic.doctor.tools import ClinicExecutor


@dataclass
class CaseResult:
    query: str
    family_truth: str
    family_stated: str | None
    expected_patch_kinds: tuple[str, ...]
    patch_kinds: tuple[str, ...]
    healed: bool
    attempts: int
    n_turns: int
    ndcg_before: float
    ndcg_after: float
    feedback: str

    @property
    def diagnosis_correct(self) -> bool:
        return self.family_stated == self.family_truth

    @property
    def patch_kind_match(self) -> bool:
        """처방 유형이 정답 유형을 전부 포함하는가."""
        return self.healed and set(self.expected_patch_kinds) <= set(self.patch_kinds)


@dataclass
class ClinicReport:
    doctor: str
    cases: list[CaseResult] = field(default_factory=list)
    failing_before: dict[str, QueryMetrics] = field(default_factory=dict)
    failing_after: dict[str, QueryMetrics] = field(default_factory=dict)
    healthy_before: dict[str, QueryMetrics] = field(default_factory=dict)
    healthy_after: dict[str, QueryMetrics] = field(default_factory=dict)
    accepted_patches: int = 0
    final_executor: ClinicExecutor | None = None  # 원장/ES 내보내기용

    @property
    def heal_rate(self) -> float:
        return sum(c.healed for c in self.cases) / len(self.cases) if self.cases else 0.0

    @property
    def diagnosis_accuracy(self) -> float:
        return (
            sum(c.diagnosis_correct for c in self.cases) / len(self.cases)
            if self.cases
            else 0.0
        )

    @property
    def patch_match_rate(self) -> float:
        return (
            sum(c.patch_kind_match for c in self.cases) / len(self.cases)
            if self.cases
            else 0.0
        )

    @property
    def healthy_regressions(self) -> list[str]:
        out = []
        for q, b in self.healthy_before.items():
            a = self.healthy_after[q]
            if a.ndcg < b.ndcg - 0.02 or a.recall < b.recall - 0.02:
                out.append(q)
        return out


def run_clinic(
    doctor_name: str = "scripted",
    doctor: LLMClient | None = None,
    doctor_factory=None,
) -> ClinicReport:
    """의사 하나를 전체 실패 질의에 투입한다.

    doctor_factory가 있으면 진료마다 새 인스턴스를 만든다 (상태 격리).
    채택된 처방은 누적되므로 뒤 진료는 앞 진료의 설정 위에서 돈다.
    """
    from searchclinic.doctor import ClinicExecutor, make_doctor
    from searchclinic.doctor.loop import run_doctor_session

    executor = ClinicExecutor(
        engine=SearchEngine(load_catalog()), evalset=load_evalset()
    )
    report = ClinicReport(doctor=doctor_name)
    report.failing_before = evaluate_all(executor.engine, failing_queries())
    report.healthy_before = evaluate_all(executor.engine, healthy_queries())

    for eq in failing_queries():
        if doctor_factory is not None:
            session_doctor = doctor_factory()
        elif doctor is not None:
            session_doctor = doctor
        else:
            session_doctor = make_doctor(doctor_name)
        session = run_doctor_session(executor, session_doctor, eq.query)
        before = report.failing_before[eq.query]
        after_metrics = evaluate_all(executor.engine, [eq])[eq.query]
        report.cases.append(
            CaseResult(
                query=eq.query,
                family_truth=eq.family or "",
                family_stated=session.diagnosis_family,
                expected_patch_kinds=eq.expected_patch_kinds,
                patch_kinds=session.patch_kinds,
                healed=session.healed,
                attempts=session.attempts,
                n_turns=session.n_turns,
                ndcg_before=before.ndcg,
                ndcg_after=after_metrics.ndcg,
                feedback=session.final_feedback,
            )
        )

    report.failing_after = evaluate_all(executor.engine, failing_queries())
    report.healthy_after = evaluate_all(executor.engine, healthy_queries())
    report.accepted_patches = len(executor.accepted)
    report.final_executor = executor  # 원장/ES 내보내기용
    return report


def render_report(report: ClinicReport) -> str:
    lines = [
        f"### 진료 결과 — 의사: `{report.doctor}`",
        "",
        "| 질의 | 정답 계열 | 진단 | 처방 유형 | 치유 | nDCG 전→후 | 시도 |",
        "|---|---|---|---|---|---|---|",
    ]
    for c in report.cases:
        diag = c.family_stated or "—"
        if c.family_stated and not c.diagnosis_correct:
            diag += " ⚠️오진"
        kinds = "+".join(c.patch_kinds) if c.patch_kinds else "—"
        lines.append(
            f"| {c.query} | {c.family_truth} | {diag} | {kinds} "
            f"| {'✅' if c.healed else '❌'} "
            f"| {c.ndcg_before:.2f} → {c.ndcg_after:.2f} | {c.attempts} |"
        )

    fb, fa = report.failing_before, report.failing_after
    hb, ha = report.healthy_before, report.healthy_after
    regressions = report.healthy_regressions
    lines += [
        "",
        f"- 치유율: **{report.heal_rate:.0%}** ({sum(c.healed for c in report.cases)}/{len(report.cases)})",
        f"- 진단 정확도: **{report.diagnosis_accuracy:.0%}**"
        " — 계열 라벨과 일치 (고쳤어도 이유가 틀리면 오진)",
        f"- 처방 적합성: **{report.patch_match_rate:.0%}** — 정답 처방 유형을 전부 포함",
        f"- 실패셋 평균 nDCG: **{mean_ndcg(fb):.3f} → {mean_ndcg(fa):.3f}**",
        f"- 실패셋 제로결과율: **{zero_result_rate(fb):.0%} → {zero_result_rate(fa):.0%}**",
        f"- 건강셋 평균 nDCG: {mean_ndcg(hb):.3f} → {mean_ndcg(ha):.3f}"
        f" · 회귀 질의: **{len(regressions)}건**"
        + (f" ⚠️ {regressions}" if regressions else " (게이트 보증)"),
        f"- 채택된 처방: {report.accepted_patches}건",
    ]
    return "\n".join(lines)
