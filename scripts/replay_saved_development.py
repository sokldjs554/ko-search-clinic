#!/usr/bin/env python3
"""Replay saved PR1 submitted prescriptions, without generation or paid APIs.

This is a NEW retrospective development run using the CURRENT engine. It is not
an exact reproduction of Kiwi 0.23.2 historical evidence, a full generator run,
or an independent evaluation. Unsubmitted historical candidates are unavailable.
The saved subset is itself selected by historical diagnosis and qrels-assisted
gate stopping; its oracle is conditional on that biased observed subset.
"""
from __future__ import annotations

import argparse
from collections import Counter
from dataclasses import asdict
from datetime import datetime, timezone
import csv
import hashlib
from importlib.metadata import version
import json
from pathlib import Path
import subprocess
import sys
from time import perf_counter

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from searchclinic.corpus import load_catalog, load_evalset
from searchclinic.index.engine import SearchEngine
from searchclinic.patch.ir import Prescription
from searchclinic.research_v5.evaluation import (
    METRICS, _metrics, matched_random_selection, oracle_analysis, score_runs,
)

SAVED = ROOT / "artifacts/research/versions/phase01-v2/evaluation-final/runs"
SOURCES = [SAVED / "always_typed_patch-20261012T062838-51deca4a.json",
           SAVED / "selective_rule-20261012T062839-7de30bb4.json"]
SEED = 20261030


def digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                    separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def collect_candidates(runs):
    """Union exact saved prescriptions in source/trace order, retaining origins."""
    result, identities = {}, {}
    for path, run in runs.items():
        seen = set()
        for row in run["queries"]:
            qid, query = row["query_id"], row["query"]
            if qid in seen or (qid in identities and identities[qid] != query):
                raise ValueError("duplicate or conflicting saved query identity")
            seen.add(qid)
            identities[qid] = query
            candidates = result.setdefault(qid, [])
            for index, event in enumerate(row["trace"]):
                if "prescription" not in event:
                    raise ValueError("saved trace lacks prescription")
                rx = event["prescription"]
                if rx.get("target_query") != query:
                    raise ValueError("saved prescription target identity mismatch")
                sha = digest(rx)
                existing = next((c for c in candidates if c["prescription_sha256"] == sha), None)
                if existing is None:
                    existing = {"candidate_id": sha, "prescription_sha256": sha,
                                "prescription": rx, "sources": []}
                    candidates.append(existing)
                existing["sources"].append({"path": path, "trace_index": index,
                                            "historical_accepted": event.get("accepted"),
                                            "saved_evidence": event.get("evidence")})
        if seen != set(result):
            raise ValueError("saved sources require identical query coverage")
    return result


def overlap_groups(qrels):
    """Posthoc diagnostic clusters: transitive overlap of judged document IDs."""
    parent = {qid: qid for qid in qrels}
    def find(qid):
        while parent[qid] != qid:
            parent[qid] = parent[parent[qid]]
            qid = parent[qid]
        return qid
    owners = {}
    for qid in sorted(qrels):
        for doc in qrels[qid]:
            if doc in owners:
                a, b = find(qid), find(owners[doc])
                parent[max(a, b)] = min(a, b)
            owners[doc] = qid
    return {qid: "posthoc-qrel-overlap:" + find(qid) for qid in qrels}


def diagnose_gate(before, after, target, *, mean_tolerance):
    """Full-precision analogue of historical gate, changing only mean tolerance."""
    if set(before) != set(after) or target not in before:
        raise ValueError("full gate query coverage required")
    regressions = [{"query_id": qid, "metric": metric,
                    "before": before[qid][metric], "after": after[qid][metric]}
                   for qid in before if qid != target for metric in METRICS
                   if before[qid][metric] - after[qid][metric] > .02 + 1e-12]
    gain = after[target]["ndcg10"] - before[target]["ndcg10"]
    mean_delta = sum(after[q]["ndcg10"] - before[q]["ndcg10"] for q in before) / len(before)
    reasons = []
    if gain < .05 - 1e-12:
        reasons.append("insufficient_target_gain")
    if regressions:
        reasons.append("other_query_regression")
    if mean_delta < -mean_tolerance:
        reasons.append("mean_ndcg_decline")
    return {"accepted": not reasons, "reason_codes": reasons or ["accepted"],
            "target_gain": gain, "mean_ndcg_delta": mean_delta,
            "mean_tolerance": mean_tolerance, "individual_tolerance": .02,
            "regression_query_ids": sorted({r["query_id"] for r in regressions}),
            "regressions": regressions,
            "diagnostic_only": True, "uses_development_qrels": True}


def source_identity():
    paths = sorted((ROOT / "src").rglob("*.py")) + [Path(__file__).resolve()]
    files = {str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}
    git = lambda *a: subprocess.check_output(["git", *a], cwd=ROOT, text=True).strip()
    return {"git_sha": git("rev-parse", "HEAD"), "git_dirty": bool(git("status", "--porcelain")),
            "source_files_sha256": digest(files), "source_files": files,
            "environment": {"python": sys.version, "kiwipiepy": version("kiwipiepy"),
                            "kiwipiepy_model": version("kiwipiepy_model"),
                            "pydantic": version("pydantic"), "kiwi_model_type": "cong-global"}}


def run_replay(*, seed=SEED, bootstrap_samples=2000):
    start = perf_counter()
    if version("kiwipiepy") != "0.24.1" or version("kiwipiepy_model") != "0.24.0":
        raise ValueError("this development replay requires pinned Kiwi 0.24.1 / model 0.24.0")
    runs = {str(p.relative_to(ROOT)): json.loads(p.read_text(encoding="utf-8")) for p in SOURCES}
    candidates = collect_candidates(runs)
    rows = next(iter(runs.values()))["queries"]
    eqs, docs = load_evalset(), load_catalog()
    by_query = {q.query: q for q in eqs}
    if len(rows) != len(eqs) or {r["query"] for r in rows} != set(by_query):
        raise ValueError("current data and saved evidence have different query coverage")
    qrels = {r["query_id"]: by_query[r["query"]].qrels for r in rows}
    groups = overlap_groups(qrels)
    metadata = [{"query_id": r["query_id"], "query": r["query"],
                 "stratum": "healthy" if by_query[r["query"]].is_healthy else "failure",
                 "concept_id": groups[r["query_id"]]} for r in rows]
    baseline = SearchEngine(docs)
    if baseline.analyzer._kiwi.model_type != "cong-global":
        raise ValueError("unexpected Kiwi model type")
    search_calls, reindexes = 0, 1
    def rankings(engine):
        nonlocal search_calls
        search_calls += len(rows)
        return {r["query_id"]: [h.doc_id for h in engine.search(r["query"], k=10)] for r in rows}
    def metrics(ranking):
        return {qid: _metrics(ids, qrels[qid]) for qid, ids in ranking.items()}
    base_rankings = rankings(baseline)
    base_scores = metrics(base_rankings)
    query_rows = []
    first_rankings, oracle_rankings = dict(base_rankings), dict(base_rankings)
    selected, scores_for_oracle, candidate_rankings = {}, {}, {}
    healthy = {q["query_id"] for q in metadata if q["stratum"] == "healthy"}
    known_strata = {q["query_id"]: q["stratum"] for q in metadata}
    for row in rows:
        qid = row["query_id"]
        available = candidates[qid]
        scores_for_oracle[qid], candidate_rankings[qid] = {}, {}
        for c in available:
            candidate_start = perf_counter()
            try:
                prescription = Prescription.model_validate(c["prescription"])
                engine = baseline.with_config(prescription.apply_to(baseline.config))
                reindexes += 1
            except ValueError as exc:
                c.update(structural_status="rejected", structural_error={"type": type(exc).__name__, "message": str(exc)},
                         latency_ms=(perf_counter() - candidate_start) * 1000,
                         semantic_verdict="unavailable_not_judged")
                continue
            result = rankings(engine)
            after = metrics(result)
            candidate_rankings[qid][c["candidate_id"]] = result[qid]
            scores_for_oracle[qid][c["candidate_id"]] = after[qid]["ndcg10"]
            changed = [k for k in base_scores if result[k] != base_rankings[k]]
            changed_healthy = [k for k in changed if k in healthy]
            healthy_regressed = [k for k in healthy if any(base_scores[k][m] - after[k][m] > .02 + 1e-12 for m in METRICS)]
            c.update(structural_status="applied_to_pristine_base", target_before=base_scores[qid],
                     target_after=after[qid], target_rankings=result[qid],
                     target_ranking_changed=result[qid] != base_rankings[qid],
                     target_gain=after[qid]["ndcg10"] - base_scores[qid]["ndcg10"],
                     all_query_rankings=result, all_query_metrics=after,
                     changed_query_ids=changed, changed_healthy_query_ids=changed_healthy,
                     changed_healthy_count=len(changed_healthy),
                     healthy_regressed_query_ids=healthy_regressed,
                     legacy_mean_gate=diagnose_gate(base_scores, after, qid, mean_tolerance=.02),
                     strict_mean_gate=diagnose_gate(base_scores, after, qid, mean_tolerance=1e-12),
                     latency_ms=(perf_counter() - candidate_start) * 1000,
                     semantic_verdict="unavailable_not_judged")
        first = available[0] if available else None
        selected[qid] = first["candidate_id"] if first and first["candidate_id"] in candidate_rankings[qid] else None
        if selected[qid] is not None:
            first_rankings[qid] = candidate_rankings[qid][selected[qid]]
        best = max(scores_for_oracle[qid], key=scores_for_oracle[qid].get, default=None)
        # No-op wins every tie: the oracle cannot invent gain or force harm.
        oracle_id = best if best and scores_for_oracle[qid][best] > base_scores[qid]["ndcg10"] + 1e-12 else None
        if oracle_id:
            oracle_rankings[qid] = candidate_rankings[qid][oracle_id]
        query_rows.append({"query_id": qid, "query": row["query"], "stratum": known_strata[qid],
                           "concept_group": groups[qid], "saved_candidates_count": len(available),
                           "baseline_ranking": base_rankings[qid], "baseline_metrics": base_scores[qid],
                           "selected_candidate_id": selected[qid], "oracle_candidate_id": oracle_id,
                           "candidates": available, "semantic_pair_labels": None,
                           "semantic_context_labels": None, "semantic_rubric": None,
                           "gpt_candidates": None, "missing_component_status": "unavailable_not_in_saved_PR1"})
    arms = {"no_repair": base_rankings, "saved_first_candidate": first_rankings,
            "oracle_submitted_candidates_with_noop": oracle_rankings}
    scored = score_runs(metadata, qrels, arms, groups=groups,
                        bootstrap_samples=bootstrap_samples, seed=seed)
    oracle = oracle_analysis({k: v["ndcg10"] for k, v in base_scores.items()}, scores_for_oracle, selected)
    eligible = {qid: list(values) for qid, values in candidate_rankings.items()}
    apply_count = sum(value is not None for value in selected.values())
    random_runs = []
    for offset in range(100):
        chosen = matched_random_selection(eligible, apply_count, seed + offset)
        random_scores = {qid: _metrics(candidate_rankings[qid][cid], qrels[qid]) if (cid := chosen.get(qid)) else base_scores[qid]
                         for qid in base_scores}
        random_runs.append({"seed": seed + offset, "selected": chosen, "apply_count": len(chosen),
                            "mean_ndcg10": sum(s["ndcg10"] for s in random_scores.values()) / len(rows),
                            "mean_delta_ndcg10": sum(random_scores[k]["ndcg10"] - base_scores[k]["ndcg10"] for k in base_scores) / len(rows),
                            "failure_improved_count": sum(random_scores[k]["ndcg10"] - base_scores[k]["ndcg10"] >= .05 - 1e-12 for k in base_scores if k not in healthy),
                            "healthy_regression_count": sum(any(base_scores[k][m] - random_scores[k][m] > .02 + 1e-12 for m in METRICS) for k in healthy)})
    valid = [c for q in query_rows for c in q["candidates"] if c["structural_status"] == "applied_to_pristine_base"]
    gate_summary = {}
    for gate in ("legacy_mean_gate", "strict_mean_gate"):
        useful = [c for c in valid if c["target_gain"] >= .05 - 1e-12]
        gate_summary[gate] = {"accepted_candidates": sum(c[gate]["accepted"] for c in valid),
                              "useful_candidates": len(useful),
                              "useful_rejected_candidates": [c["candidate_id"] for c in useful if not c[gate]["accepted"]],
                              "reason_counts": dict(Counter(reason for c in valid for reason in c[gate]["reason_codes"]))}
    data = {"documents": [asdict(d) for d in docs], "queries": [asdict(q) for q in eqs]}
    return {"schema_version": 1, "created_at": datetime.now(timezone.utc).isoformat(),
            "study_status": "new_retrospective_development_run_not_original_reproduction",
            "data_status": "controlled_authored_dev_reused_no_new_independent_data",
            "candidate_scope": "union_of_saved_submitted_prescriptions_only; unsubmitted_suffix_unavailable",
            "candidate_selection_bias": "The observed submitted set was filtered by historical diagnosis/policy and qrels-assisted gate stopping. It is not an unselected sample of generated candidates. Oracle gains and candidate success rates are conditional on this biased saved subset; they cannot estimate full generator capability.",
            "arm_policy": "first unique saved prescription in always then selective source/trace order; no quality gate; exact-query isolated application",
            "oracle_policy": "retrospective qrels-assisted target nDCG maximum including no-op; not an executable selection policy",
            "gate_policy": "each candidate globally evaluated on all 36 from pristine engine; same full-precision metrics and individual .02 tolerance; mean .02 versus 1e-12; diagnostics only",
            "semantic_status": "pair/context/rubric/GPT unavailable; no semantic judgments invented",
            "superiority_claim": False, "source": source_identity(),
            "source_json": [{"path": str(p.relative_to(ROOT)), "sha256": hashlib.sha256(p.read_bytes()).hexdigest(),
                             "historical_source_hash": runs[str(p.relative_to(ROOT))]["source_hash"],
                             "historical_environment": runs[str(p.relative_to(ROOT))]["environment"]} for p in SOURCES],
            "data_sha256": digest(data), "corpus_sha256": digest(data["documents"]), "evalset_sha256": digest(data["queries"]),
            "base_config": baseline.config.model_dump(mode="json"),
            "bootstrap_grouping": {"method": "posthoc_union_find_shared_qrel_document_transitive_overlap",
                                   "independence_certified": False, "groups": groups,
                                   "count": len(set(groups.values()))},
            "queries": query_rows, "score_report": scored, "oracle_diagnostic": oracle,
            "gate_diagnostics": gate_summary,
            "matched_random": {"runs": random_runs, "seed": seed, "runs_count": 100,
                               "apply_count": apply_count, "eligible_query_count": sum(bool(v) for v in eligible.values()),
                               "scope": "matches apply count, random eligible query and candidate; no new proposals or calls",
                               "trivial_selection_warning": "when apply_count equals eligible query count only candidate choice varies; singleton queries are deterministic",
                               "mean_delta_ndcg10": sum(r["mean_delta_ndcg10"] for r in random_runs) / 100,
                               "delta_range": [min(r["mean_delta_ndcg10"] for r in random_runs), max(r["mean_delta_ndcg10"] for r in random_runs)]},
            "costs": {"api_calls": 0, "api_cost_usd": 0., "search_calls": search_calls,
                      "reindexes": reindexes, "latency_ms": (perf_counter() - start) * 1000},
            "limitations": ["saved candidate subset selected by historical diagnosis and qrels-assisted gate stopping; conditional observed-subset oracle only",
                            "historical generated-but-unsubmitted candidates absent", "historical labels reused for diagnostics",
                            "current Kiwi and full-precision fixed-denominator metrics differ from historical run",
                            "first/oracle query-specific arms do not deploy the globally evaluated configuration cumulatively",
                            "bootstrap clusters are posthoc overlap proxies, not independent human-reviewed concepts"]}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=ROOT / "work/development-replay.json")
    parser.add_argument("--csv", type=Path)
    parser.add_argument("--seed", type=int, default=SEED)
    parser.add_argument("--bootstrap-samples", type=int, default=2000)
    args = parser.parse_args(argv)
    csv_path = args.csv or args.out.with_suffix(".csv")
    for p in (args.out, csv_path):
        p = p.resolve()
        if p == SAVED or SAVED in p.parents or ROOT / "artifacts" in p.parents:
            raise ValueError("historical artifacts are read-only")
        if p.exists():
            raise FileExistsError(f"refusing to overwrite evidence: {p}")
    result = run_replay(seed=args.seed, bootstrap_samples=args.bootstrap_samples)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open("x", encoding="utf-8") as stream:
        json.dump(result, stream, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False)
        stream.write("\n")
    fields = ["query_id", "query", "stratum", "concept_group", "saved_candidates_count",
              "baseline_ndcg10", "first_ndcg10", "oracle_ndcg10", "selected_candidate_id",
              "oracle_candidate_id", "candidate_details", "semantic_status"]
    with csv_path.open("x", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fields, lineterminator="\n")
        writer.writeheader()
        scores = result["score_report"]["per_query"]
        for q in result["queries"]:
            writer.writerow({**{k: q[k] for k in fields if k in q},
                             "baseline_ndcg10": scores["no_repair"][q["query_id"]]["ndcg10"],
                             "first_ndcg10": scores["saved_first_candidate"][q["query_id"]]["ndcg10"],
                             "oracle_ndcg10": scores["oracle_submitted_candidates_with_noop"][q["query_id"]]["ndcg10"],
                             "candidate_details": json.dumps([{k: c[k] for k in ("candidate_id", "prescription", "target_before", "target_after", "target_gain", "healthy_regressed_query_ids", "strict_mean_gate", "legacy_mean_gate", "sources")} for c in q["candidates"]], ensure_ascii=False, separators=(",", ":")),
                             "semantic_status": "unavailable_not_judged"})
    print(json.dumps({"out": str(args.out), "csv": str(csv_path), "queries": len(result["queries"]),
                      "costs": result["costs"], "summaries": result["score_report"]["summaries"]}, ensure_ascii=False))


if __name__ == "__main__":
    main()
