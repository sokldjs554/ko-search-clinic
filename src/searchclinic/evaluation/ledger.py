"""패치 원장(ledger) — 채택된 모든 처방과 그 증거.

운영 검색의 사전·동의어는 시간이 지나면 "왜 넣었는지 아무도 모르는" 항목이
쌓여 부채가 된다. 원장은 그것을 막는다: 모든 항목에 표적 질의, 진단 근거,
채택 당시의 전/후 지표가 붙어 있어서, 나중에 항목을 의심할 때 근거를
재검증할 수 있다.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

if TYPE_CHECKING:  # 순환 임포트 방지: 실행 시점에는 타입만 필요하다
    from searchclinic.doctor.tools import AcceptedRecord


def ledger_entries(accepted: "list[AcceptedRecord]") -> list[dict]:
    out = []
    for i, rec in enumerate(accepted, 1):
        v = rec.verdict
        out.append(
            {
                "no": i,
                "target_query": rec.prescription.target_query,
                "diagnosis_family": rec.prescription.diagnosis_family,
                "patch": rec.prescription.summary(),
                "reasoning": rec.prescription.reasoning,
                "evidence": {
                    "target_ndcg": [v.target_before.ndcg, v.target_after.ndcg],
                    "target_results": [v.target_before.n_results, v.target_after.n_results],
                    "evalset_mean_ndcg": [v.mean_before, v.mean_after],
                },
                "attempts": rec.attempts,
            }
        )
    return out


def render_ledger_json(accepted: "list[AcceptedRecord]") -> str:
    return json.dumps(ledger_entries(accepted), ensure_ascii=False, indent=2)


def render_ledger_markdown(accepted: "list[AcceptedRecord]") -> str:
    lines = [
        "### 패치 원장 — 모든 항목에 채택 증거가 붙어 있다",
        "",
        "| # | 표적 질의 | 계열 | 패치 | 표적 nDCG | 결과 수 | 시도 |",
        "|---|---|---|---|---|---|---|",
    ]
    for e in ledger_entries(accepted):
        ev = e["evidence"]
        lines.append(
            f"| {e['no']} | {e['target_query']} | {e['diagnosis_family']} "
            f"| {e['patch']} "
            f"| {ev['target_ndcg'][0]:.2f} → {ev['target_ndcg'][1]:.2f} "
            f"| {ev['target_results'][0]} → {ev['target_results'][1]} "
            f"| {e['attempts']} |"
        )
    return "\n".join(lines)
