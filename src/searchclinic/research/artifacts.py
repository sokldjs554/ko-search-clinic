"""Append-only JSON and reports generated from actual run payloads."""
import json
from pathlib import Path

from searchclinic.research.metrics import paired_bootstrap, summarize


def write_artifact(path, payload):
    path = Path(path)
    serialized = json.dumps(payload, ensure_ascii=False, indent=2, allow_nan=False) + "\n"
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8") as stream:
        stream.write(serialized)


def write_report(path, text):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8") as stream:
        stream.write(text)


def compare_runs(runs):
    if len({r["policy"] for r in runs}) != len(runs):
        raise ValueError("duplicate policy runs: use a separate artifact root per comparison")
    by_policy = {r["policy"]: r for r in runs}
    if not {"always_typed_patch", "selective_rule"} <= by_policy.keys():
        return {"status": "comparison_not_executed"}
    a, s = by_policy["always_typed_patch"], by_policy["selective_rule"]
    for field in ("protocol_hash", "split_hash", "corpus_hash", "evalset_hash", "source_hash", "environment", "seed"):
        if a[field] != s[field]:
            raise ValueError(f"incomparable runs: {field} mismatch")
    if [q["query_id"] for q in a["queries"]] != [q["query_id"] for q in s["queries"]]:
        raise ValueError("incomparable runs: query order mismatch")
    sa, ss = a["summary"], s["summary"]
    h1 = ss["healthy_interventions"] < sa["healthy_interventions"] and s["costs"]["search_calls"] < a["costs"]["search_calls"]
    h2 = ss["recovered_count"] >= sa["recovered_count"] and ss["failing_ndcg_after"] >= sa["failing_ndcg_after"] and ss["healthy_regression_count"] == 0
    h3 = all(q["observation"]["result_count"] == 0 for q in s["queries"] if q["family"] is not None)
    keyed = {q["query_id"]: q for q in a["queries"]}
    deltas = [q["after"]["ndcg"] - keyed[q["query_id"]]["after"]["ndcg"] for q in s["queries"]]
    return {"status": "executed_controlled_dev", "H1": "supported" if h1 else "rejected",
            "H2": "supported" if h2 else "rejected", "H3": "supported" if h3 else "rejected",
            "paired_ndcg": paired_bootstrap(deltas, s["seed"], s["config"]["config"]["bootstrap_samples"])}


def render_report(runs):
    if not runs:
        raise ValueError("no executed runs to report")
    lines = ["# Phase 0–1 실제 실행 결과", "", "데이터: controlled-v1/dev. held-out 미수집; 일반화 결과 없음.",
        "규칙 score는 보정된 확률이 아니다. 단일 wall-clock 실행으로 속도 우위를 주장하지 않는다.", "",
        "| 정책 | 치유/실패 | 실패 nDCG@10 | 건강 회귀 | 건강 개입 | 제출 | 검색 호출 | 재색인 | 외부 모델 호출 | 지연 ms |",
        "|---|---|---|---|---|---|---|---|---|---|"]
    for r in runs:
        s, c = r["summary"], r["costs"]
        actual = summarize(r["queries"], r["config"]["config"]["policy"]["epsilon"],
                           r["config"]["config"]["detector"]["threshold"])
        if actual != s:
            raise ValueError("artifact summary does not match query records")
        lines.append(f"| {r['policy']} | {s['recovered_count']}/{s['failing_count']} | {s['failing_ndcg_after']:.4f} | {s['healthy_regression_count']} | {s['healthy_interventions']} | {s['submissions']} | {c['search_calls']} | {c['reindexes']} | {c['model_calls']} | {c['latency_ms']:.3f} |")
    if any(r.get("protocol_version") == "phase01-v2" for r in runs):
        lines += ["", "phase01-v2는 실측 지연과 예상 행동 비용을 분리한 사후 변경이다.",
            "예상 미래 latency는 null이며 그 미보정 항의 weight만 0이다. 실제 지연은 위 표에 보존한다.",
            "이 결과는 기존 phase01-v1 또는 held-out 성능을 대체하지 않는다."]
    lines += ["", "검색 호출은 초기 관측·전후 평가·전체 회귀 게이트를 모두 포함한다.",
        "건강 개입은 진단 실행도 포함하며 실제 제출과 구분한다.", "",
        "| 정책 | AUROC | AUPRC | Precision | Recall | F1 | Brier | ECE | 건강 FPR | 불필요 개입률 | 첫 제출 채택률 | 기각 후 회복률 | 평균 제출 |",
        "|---|---|---|---|---|---|---|---|---|---|---|---|---|"]
    def fmt(v):
        return "null" if v is None else f"{v:.4f}"
    for r in runs:
        s, d = r["summary"], r["summary"]["detection"]
        values = [d[k] for k in ("auroc", "auprc", "precision", "recall", "f1", "brier", "ece", "healthy_fpr")]
        values += [s[k] for k in ("unnecessary_action_rate", "first_pass_acceptance", "recovery_after_rejection", "mean_submissions")]
        lines.append("| " + r["policy"] + " | " + " | ".join(fmt(v) for v in values) + " |")
    lines += ["", "| 정책 | input tokens | output tokens | API USD |", "|---|---|---|---|"]
    for r in runs:
        c = r["costs"]
        lines.append(f"| {r['policy']} | {c['input_tokens']} | {c['output_tokens']} | {c['api_cost_usd']} |")
    comparison = compare_runs(runs)
    lines += ["", "## 사전 가설 판정", "", "```json", json.dumps(comparison, ensure_ascii=False, indent=2), "```",
        "", "## 실행 provenance", ""]
    for r in runs:
        lines += [f"- {r['policy']}: git `{r['git_sha']}`, source hash `{r['source_hash']}`, dirty={r['git_dirty']};",
                  f"  protocol `{r['protocol_hash']}`, split `{r['split_hash']}`, seed={r['seed']};",
                  "  환경: " + json.dumps(r["environment"], ensure_ascii=False)]
    lines += ["", "## 관측된 기각과 한계", ""]
    rejected = [(r["policy"], q["query"], q["submissions"], q["accepted"])
        for r in runs for q in r["queries"] if any(t["reason"] == "rejected" for t in q["trace"])]
    if rejected:
        lines += [f"- {policy}: `{query}`, 제출 {n}, 최종 채택={accepted}. 원장 trace의 실제 피드백 참조."
                  for policy, query, n, accepted in rejected]
    else:
        lines.append("- 실제 기각→재처방 회복을 이번 실행에서 관측하지 못했다.")
    lines += ["- 기존 v1의 공개 fixture만 평가했다. held-out·외부 도메인·LLM 능력 증거는 없다.",
        "- span/형태 관계는 완전한 의미 타당성 판정이 아니다. Phase 2에서 독립 근거 검증이 필요하다.",
        "- rewrite_query, switch_or_fuse_retriever, rerank 실행과 LLM 비교는 Phase 1에서 미지원/미실행이다.",
        "- λ와 detector 기준은 사전 지정값이다. 비용 차이는 모델 호출 절감의 증거가 아니다.",
        "- gate budget은 제출 횟수 제한이다. 큰 corpus의 전체 재색인 시간 상한을 보장하지 않는다.", ""]
    return "\n".join(lines)
