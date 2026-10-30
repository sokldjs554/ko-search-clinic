#!/usr/bin/env python3
"""Prepare sealed retrospective development inputs; never call a provider.

Saved submitted prescriptions already reflect historical outcome-dependent
stopping. Current-engine context is reconstructed and cannot reproduce the
original evidence. These controlled development data are never a blind test.
"""
from __future__ import annotations

import argparse
from dataclasses import asdict
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from searchclinic.corpus import load_catalog
from searchclinic.index.engine import SearchEngine
from searchclinic.patch.ir import Prescription
from searchclinic.research.phase2.contracts import Context
from searchclinic.research_v5.pipeline import _validated, freeze
from searchclinic.research_v5.semantic import prepare_judge_request

SAVED = ROOT / "artifacts/research/versions/phase01-v2/evaluation-final/runs"
SOURCES = (SAVED / "always_typed_patch-20261012T062838-51deca4a.json",
           SAVED / "selective_rule-20261012T062839-7de30bb4.json")
MODEL_ID = "gpt-4.1-mini-2025-04-14"
CONDITIONS = ("pair", "context", "rubric")
SEED = 20261030
MAX_INPUT = 12000
MAX_OUTPUT = 2000
REPEATS = 2


def load_saved_candidates(sources=None):
    """Whitelist raw trace identities/prescriptions; ignore all saved outcomes."""
    rows, seen_queries = {}, {}
    for path in SOURCES if sources is None else sources:
        source = json.loads(Path(path).read_text(encoding="utf-8"))
        coverage = set()
        for raw in source["queries"]:
            qid, query = raw["query_id"], raw["query"]
            if not isinstance(qid, str) or not isinstance(query, str) or not qid or not query:
                raise ValueError("saved query identity must be nonempty strings")
            if qid in coverage or (qid in rows and rows[qid]["query"] != query):
                raise ValueError("duplicate or conflicting saved query identity")
            if query in seen_queries and seen_queries[query] != qid:
                raise ValueError("duplicate saved query text")
            coverage.add(qid)
            seen_queries[query] = qid
            row = rows.setdefault(qid, {"query_id": qid, "query": query, "candidates": []})
            for event in raw["trace"]:
                candidate = event["prescription"]
                if candidate.get("target_query") != query:
                    raise ValueError("saved prescription target identity mismatch")
                if candidate not in [item["prescription"] for item in row["candidates"]]:
                    row["candidates"].append({"prescription": candidate})
        if coverage != set(rows):
            raise ValueError("saved sources require identical query coverage")
    if not rows:
        raise ValueError("saved source coverage is empty")
    return list(rows.values())


def load_evalset():
    """Load private development annotations only after public requests exist."""
    from searchclinic.corpus import load_evalset as load
    return load()


def _write(path, value):
    with path.open("x", encoding="utf-8") as stream:
        json.dump(value, stream, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False)
        stream.write("\n")


def _terms(query, candidates):
    terms = {query}
    for raw in candidates:
        p = Prescription.model_validate(raw)
        terms.update(word.form for word in p.user_words)
        terms.update(term for group in p.synonym_groups for term in group.terms)
        terms.update(term for compound in p.compound_expansions for term in [compound.word, *compound.parts])
    return terms


def _record(row, engine, docs):
    candidates = [item["prescription"] for item in row["candidates"]]
    if len(candidates) > 3:
        raise ValueError("saved query exceeds three fixed candidates")
    query, qid = row["query"], row["query_id"]
    terms = _terms(query, candidates)
    evidence = [doc for doc in docs if any(term in doc.text for term in terms)]
    total = min(10, len(engine.search(query, k=10)))
    context = Context.model_validate({
        "query_id": qid, "query": query, "query_tokens": engine.analyzer.tokens(query),
        "observation": {"query_id": qid, "query": query, "split": "dev", "result_count": total},
        "search_total": total, "grep_total": len(evidence), "similar": [],
        "documents": [{"doc_id": doc.doc_id, "text": doc.text, "tokens": engine.analyzer.tokens(doc.text)}
                      for doc in evidence[:10]],
    }, strict=True)
    checks = []
    for index, candidate in enumerate(candidates):
        # Structural/target errors stop preparation; literal-evidence failures
        # are recorded without rewriting the fixed historical candidate.
        prepare_judge_request(context, candidate)
        try:
            _validated(context, candidate)
            error = None
        except ValueError as exc:
            error = str(exc)
        checks.append({"candidate_index": index, "literal_validation_error": error})
    return {"context": context.model_dump(mode="json"), "candidates": candidates, "generation_error": None}, checks


def _concept_groups(annotations):
    """Private posthoc clusters from transitive overlap; not certified concepts."""
    parent = {qid: qid for qid in annotations}

    def find(qid):
        while parent[qid] != qid:
            parent[qid] = parent[parent[qid]]
            qid = parent[qid]
        return qid

    owners = {}
    for qid in sorted(annotations):
        for doc_id in annotations[qid]:
            if doc_id in owners:
                a, b = find(qid), find(owners[doc_id])
                parent[max(a, b)] = min(a, b)
            owners[doc_id] = qid
    return {qid: "posthoc-qrel-overlap:" + find(qid) for qid in annotations}


def _save_private_labels(output, rows):
    evalset = load_evalset()
    by_query = {q.query: q for q in evalset}
    if len(by_query) != len(evalset) or len(rows) != len(evalset) or {r["query"] for r in rows} != set(by_query):
        raise ValueError("saved queries and current development annotations require exact coverage")
    annotations = {r["query_id"]: by_query[r["query"]].qrels for r in rows}
    concepts = _concept_groups(annotations)
    metadata = [{"query_id": r["query_id"], "stratum": "healthy" if by_query[r["query"]].is_healthy else "failure",
                 "concept_id": concepts[r["query_id"]]} for r in rows]
    private = output / "private"
    private.mkdir()
    path = private / "labels.json"
    _write(path, {"queries": metadata, "qrels": annotations})
    _write(private / "labels-manifest.json", {
        "labels_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        "study_status": "retrospective_controlled_development_only",
        "concept_method": "posthoc_transitive_judged_document_overlap",
        "concept_independence_certified": False,
    })


def prepare(output_dir=ROOT / "work/v5-prepared"):
    """Create a new directory containing immutable inputs and an unexecuted plan."""
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=False)
    rows = load_saved_candidates()
    if len({r["query_id"] for r in rows}) != len(rows):
        raise ValueError("duplicate saved query ID")
    docs = sorted(load_catalog(), key=lambda doc: doc.doc_id)
    engine = SearchEngine(docs)
    records, checks = [], {}
    for row in rows:
        record, checks[row["query_id"]] = _record(row, engine, docs)
        records.append(record)
    count = sum(len(record["candidates"]) for record in records)
    if count > 15:
        raise ValueError("saved candidate set exceeds the proposed maximum of 15")
    bundle = freeze({"version": "v5", "model_id": MODEL_ID, "min_confidence": .8, "seed": SEED,
                     "documents": [asdict(doc) for doc in docs], "records": records})
    _write(output / "candidates.json", bundle)
    _write(output / "verdicts-empty.json", {row["query_id"]: [] for row in rows})
    too_large = 0
    for condition in CONDITIONS:
        requests = []
        for record in records:
            for index, candidate in enumerate(record["candidates"]):
                request = prepare_judge_request(record["context"], candidate, condition)
                upper_bound = len(request.body.encode("utf-8")) + 256
                ready = upper_bound <= MAX_INPUT
                too_large += not ready
                requests.append({"query_id": record["context"]["query_id"], "candidate_index": index,
                                 "request": request.model_dump(mode="json"),
                                 "input_token_upper_bound": upper_bound,
                                 "budget_status": "ready" if ready else "request_too_large"})
        _write(output / f"requests-{condition}.json", freeze({
            "version": "judge-requests-v5", "model_id": MODEL_ID, "condition": condition,
            "input_hash": bundle["sha256"], "records": requests,
        }))
    calls = count * len(CONDITIONS) * REPEATS
    maximum_cost = round(calls * (MAX_INPUT * .4 + MAX_OUTPUT * 1.6) / 1_000_000, 6)
    _write(output / "proposal.json", {
        "status": "prepared_not_executed", "study_status": "retrospective_controlled_development_only",
        "model_id": MODEL_ID, "model_availability_verified": False, "model_documentation_status": "Deprecated",
        "pricing_url": "https://developers.openai.com/api/docs/models/gpt-4.1-mini",
        "pricing_verified_date": "2026-10-30", "input_usd_per_million_tokens": .4,
        "output_usd_per_million_tokens": 1.6, "candidate_count": count,
        "conditions": list(CONDITIONS), "repeats": REPEATS, "proposed_calls": calls,
        "maximum_calls": 90, "max_input_tokens": MAX_INPUT, "max_output_tokens": MAX_OUTPUT,
        "maximum_cost_usd": maximum_cost, "absolute_budget_ceiling_usd": .72,
        "automatic_retries": 0, "timeout_accounting": "reserve_full_per_call_maximum",
        "input_bound_method": "UTF8_bytes_plus_256_overhead; conservative_bound_not_exact_token_count",
        "oversize_policy": "hold_request_without_truncation", "oversized_unique_requests": too_large,
        "provider_calls_executed": 0, "credential_choice": "pending", "input_hash": bundle["sha256"],
    })
    # No private annotations are imported or inspected before all requests exist.
    _save_private_labels(output, rows)
    _write(output / "preparation.json", freeze({
        "version": "development-preparation-v5", "input_hash": bundle["sha256"],
        "study_status": "retrospective_controlled_development_only", "blind_evaluation": False,
        "original_context_reproduced": False, "context_status": "reconstructed_with_current_immutable_engine",
        "candidate_source": "saved_PR1_submitted_prescriptions_in_original_source_trace_order",
        "candidate_selection_bias": "historical_diagnosis_and_outcome_dependent_stopping; unsubmitted_candidates_unavailable",
        "evidence_policy": "all_literal_query_or_patch_term_matches_sorted_by_doc_id_capped_at_ten",
        "candidate_checks": checks, "queries": len(records), "candidates": count,
    }))
    return {"output_dir": str(output), "study_status": "retrospective_controlled_development_only",
            "queries": len(records), "candidates": count, "proposed_calls": calls,
            "maximum_cost_usd": maximum_cost, "provider_calls_executed": 0}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", "--output", dest="output", type=Path, default=ROOT / "work/v5-prepared")
    args = parser.parse_args(argv)
    print(json.dumps(prepare(args.output), ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
