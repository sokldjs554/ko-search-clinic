"""Strict offline research diagnostics, independent of candidate selection.

Inputs and outputs are JSON-compatible. Qrels must be complete: an explicit empty
mapping is a known all-nonrelevant query; missing/null judgments are an error.
Relevance > 0 is relevant. Precision@5 always divides by five, including short
rankings. Scores retain full precision and use only the stated cutoff.

Cluster intervals describe the supplied sample; they do not establish a blind
experiment, independent adjudication, or superiority. Study provenance belongs
in the caller's report. With fewer than two independent groups no CI is issued.
"""
from __future__ import annotations

from collections import defaultdict
from collections.abc import Mapping
import math
from numbers import Real
import random
import unicodedata

METRICS = ("ndcg10", "recall10", "precision5")


def _identifier(value, label):
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{label} must be a nonempty string")
    return value


def _mapping(value, label):
    if not isinstance(value, Mapping):
        raise ValueError(f"{label} must be a mapping")
    for key in value:
        _identifier(key, f"{label} key")
    return value


def _ids(value, label):
    if not isinstance(value, (list, tuple)):
        raise ValueError(f"{label} must be a list of IDs")
    for item in value:
        _identifier(item, label)
    if len(value) != len(set(value)):
        raise ValueError(f"{label} contains duplicate IDs")
    return list(value)


def _coverage(mapping, expected, label):
    _mapping(mapping, label)
    if set(mapping) != set(expected):
        raise ValueError(f"{label} must cover exactly every query ID")


def _finite(value, label):
    if isinstance(value, bool) or not isinstance(value, Real) or not math.isfinite(value):
        raise ValueError(f"{label} must be finite numeric data")
    return float(value)


def _metrics(ranking, judgments):
    # Scaling exponential gains by the largest grade prevents overflow while
    # preserving the DCG/IDCG ratio, even for large valid integer grades.
    largest = max(judgments.values(), default=0)
    def gain(grade):
        return 2.0 ** (grade - largest) - 2.0 ** (-largest)
    def dcg(grades):
        return sum(gain(g) / math.log2(i + 2) for i, g in enumerate(grades))
    ideal = dcg(sorted(judgments.values(), reverse=True)[:10])
    actual = dcg([judgments.get(doc, 0) for doc in ranking[:10]])
    relevant = {doc for doc, grade in judgments.items() if grade > 0}
    return {
        "ndcg10": actual / ideal if ideal else 0.0,
        "recall10": len(relevant.intersection(ranking[:10])) / len(relevant) if relevant else 0.0,
        "precision5": sum(doc in relevant for doc in ranking[:5]) / 5,
    }


def _percentile(values, probability):
    position = (len(values) - 1) * probability
    lower = math.floor(position)
    upper = math.ceil(position)
    return values[lower] + (values[upper] - values[lower]) * (position - lower)


def _paired_stats(qids, scores, baseline, groups, bootstrap_samples, seed):
    grouped = defaultdict(list)
    differences = {}
    for qid in qids:
        differences[qid] = {m: scores[qid][m] - baseline[qid][m] for m in METRICS}
        grouped[groups[qid]].append(qid)
    clusters = [grouped[group] for group in sorted(grouped)]
    draws = {m: [] for m in METRICS}
    if len(clusters) >= 2:
        rng = random.Random(seed)
        for _ in range(bootstrap_samples):
            # A sampled group retains ALL its queries, including multiplicity.
            sample = [qid for cluster in rng.choices(clusters, k=len(clusters)) for qid in cluster]
            for metric in METRICS:
                draws[metric].append(sum(differences[q][metric] for q in sample) / len(sample))
    output = {}
    for metric in METRICS:
        distribution = sorted(draws[metric])
        output[metric] = {
            "mean_difference": sum(differences[q][metric] for q in qids) / len(qids) if qids else None,
            "ci95": [_percentile(distribution, .025), _percentile(distribution, .975)] if distribution else None,
            "independent_groups": len(clusters),
            "inference_status": "descriptive_interval_only" if distribution else "insufficient_independent_groups",
            "superiority_claim": False,
        }
    return output


def score_runs(queries, qrels, arms, *, groups=None, bootstrap_samples=2000, seed=20261030):
    """Score complete frozen runs and paired concept-cluster percentile CIs.

    ``groups`` optionally supplies a complete query-ID -> group-ID mapping;
    otherwise ``concept_id`` defines the bootstrap unit. Means weight queries,
    not concepts. Improvement is nDCG@10 gain >= .05 on failure queries; healthy
    regression is a loss > .02 on any reported metric, with 1e-12 roundoff slack.
    """
    if not isinstance(queries, (list, tuple)) or not queries:
        raise ValueError("queries must be a nonempty list")
    if isinstance(bootstrap_samples, bool) or not isinstance(bootstrap_samples, int) or bootstrap_samples < 1:
        raise ValueError("bootstrap_samples must be a positive integer")
    if isinstance(seed, bool) or not isinstance(seed, int):
        raise ValueError("seed must be an integer")
    metadata = {}
    for query in queries:
        if not isinstance(query, Mapping):
            raise ValueError("each query must contain query_id, stratum, concept_id")
        qid = _identifier(query.get("query_id"), "query_id")
        if qid in metadata:
            raise ValueError("duplicate query_id")
        if query.get("stratum") not in ("healthy", "failure"):
            raise ValueError("stratum must be healthy or failure; adjudicate ambiguous cases first")
        _identifier(query.get("concept_id"), "concept_id")
        metadata[qid] = query
    qids = sorted(metadata)
    _coverage(qrels, qids, "qrels")
    for qid in qids:
        judgments = _mapping(qrels[qid], f"qrels[{qid}]")
        for grade in judgments.values():
            _finite(grade, "relevance grade")
            if isinstance(grade, bool) or not isinstance(grade, int) or grade < 0:
                raise ValueError("relevance grades must be nonnegative integers")
    _mapping(arms, "arms")
    if "no_repair" not in arms:
        raise ValueError("arms must contain no_repair")
    for name, runs in arms.items():
        _coverage(runs, qids, f"arm {name}")
        for qid, ranking in runs.items():
            _ids(ranking, f"ranking {name}/{qid}")
    if groups is None:
        groups = {qid: metadata[qid]["concept_id"] for qid in qids}
    else:
        _coverage(groups, qids, "groups")
        for group in groups.values():
            _identifier(group, "group")
    strata = {"overall": qids, **{
        stratum: [qid for qid in qids if metadata[qid]["stratum"] == stratum]
        for stratum in ("failure", "healthy")
    }}
    per_query = {name: {qid: _metrics(runs[qid], qrels[qid]) for qid in qids}
                 for name, runs in arms.items()}
    summaries = {}
    for name, scores in per_query.items():
        summaries[name] = {
            stratum: {"count": len(ids), **{
                metric: sum(scores[q][metric] for q in ids) / len(ids) if ids else None
                for metric in METRICS
            }} for stratum, ids in strata.items()
        }
    baseline = per_query["no_repair"]
    comparisons = {}
    for name, scores in per_query.items():
        if name == "no_repair":
            continue
        comparisons[name] = {
            stratum: _paired_stats(ids, scores, baseline, groups, bootstrap_samples, seed)
            for stratum, ids in strata.items()
        }
        comparisons[name]["failure_improved_query_ids"] = [
            q for q in strata["failure"] if scores[q]["ndcg10"] - baseline[q]["ndcg10"] >= .05 - 1e-12
        ]
        comparisons[name]["healthy_regressed_query_ids"] = [
            q for q in strata["healthy"] if any(baseline[q][m] - scores[q][m] > .02 + 1e-12 for m in METRICS)
        ]
    return {"per_query": per_query, "summaries": summaries, "comparisons": comparisons,
            "bootstrap": {"method": "paired_concept_cluster_percentile", "samples": bootstrap_samples,
                          "seed": seed, "mean_weighting": "query"}}


def oracle_analysis(baseline_scores, candidate_scores, selected):
    """Diagnostic attainable and selected gains, including no repair as an option.

    This function deliberately imports no selector. Supplying qrels-derived
    scores here is retrospective analysis, never a label-free decision rule.
    """
    _mapping(baseline_scores, "baseline_scores")
    _coverage(candidate_scores, baseline_scores, "candidate_scores")
    _coverage(selected, baseline_scores, "selected")
    rows = {}
    for qid, raw_baseline in baseline_scores.items():
        baseline = _finite(raw_baseline, "baseline score")
        candidates = _mapping(candidate_scores[qid], "query candidates")
        scores = {cid: _finite(value, "candidate score") for cid, value in candidates.items()}
        chosen = selected[qid]
        if chosen is not None and (not isinstance(chosen, str) or chosen not in scores):
            raise ValueError("selected candidate must exist for its query or be None")
        useful = sorted(cid for cid, value in scores.items() if value > baseline)
        oracle = max([baseline, *scores.values()])
        chosen_score = baseline if chosen is None else scores[chosen]
        rows[qid] = {"baseline_score": baseline, "oracle_score": oracle,
                     "selected_score": chosen_score, "selected_candidate_id": chosen,
                     "available_gain": oracle - baseline, "selected_gain": chosen_score - baseline,
                     "useful_selected": [cid for cid in useful if cid == chosen],
                     "useful_rejected": [cid for cid in useful if cid != chosen]}
    return {"diagnostic_only": True, "per_query": rows,
            "available_gain_mean": sum(r["available_gain"] for r in rows.values()) / len(rows) if rows else None,
            "selected_gain_mean": sum(r["selected_gain"] for r in rows.values()) / len(rows) if rows else None}


def matched_random_selection(eligible, count, seed):
    """Choose exactly count distinct eligible queries and one candidate each."""
    _mapping(eligible, "eligible")
    for qid, candidates in eligible.items():
        _ids(candidates, f"eligible candidates for {qid}")
    qids = sorted(qid for qid, candidates in eligible.items() if candidates)
    if isinstance(count, bool) or not isinstance(count, int) or not 0 <= count <= len(qids):
        raise ValueError("count must be an integer within eligible query count")
    if isinstance(seed, bool) or not isinstance(seed, int):
        raise ValueError("seed must be an integer")
    rng = random.Random(seed)
    return {qid: rng.choice(sorted(eligible[qid])) for qid in sorted(rng.sample(qids, count))}


def audit_splits(splits):
    """Report duplicate query identities/text and document/concept leakage.

    NFKC normalization, case folding and whitespace normalization detect text
    duplicates. Query IDs must be globally unique; document/concept reuse within
    a split is allowed, but reuse across splits is reported. Missing or malformed
    metadata raises, so an incomplete manifest cannot receive a clean audit.
    """
    _mapping(splits, "splits")
    issues = []
    seen_ids, seen_text = {}, {}
    owners = {"document_ids": defaultdict(set), "concept_ids": defaultdict(set)}
    counts = {}
    for split, records in splits.items():
        if not isinstance(records, (list, tuple)):
            raise ValueError("split records must be lists")
        counts[split] = len(records)
        for record in records:
            if not isinstance(record, Mapping):
                raise ValueError("each split record must contain complete metadata")
            qid = _identifier(record.get("query_id"), "query_id")
            query = _identifier(record.get("query"), "query")
            normalized = " ".join(unicodedata.normalize("NFKC", query).casefold().split())
            location = {"split": split, "query_id": qid}
            for value, seen, kind in ((qid, seen_ids, "duplicate_query_id"),
                                      (normalized, seen_text, "normalized_query_duplicate")):
                if value in seen:
                    issues.append({"kind": kind, "value": value, "first": seen[value], "second": location})
                else:
                    seen[value] = location
            for field in owners:
                ids = _ids(record.get(field), field)
                if field == "concept_ids" and not ids:
                    raise ValueError("concept_ids must contain at least one concept")
                for identifier in ids:
                    owners[field][identifier].add(split)
    for field, identifiers in owners.items():
        for identifier, split_names in sorted(identifiers.items()):
            if len(split_names) > 1:
                issues.append({"kind": "document_overlap" if field == "document_ids" else "concept_overlap",
                               "value": identifier, "splits": sorted(split_names)})
    return {"valid": not issues, "issues": issues, "counts": counts}
