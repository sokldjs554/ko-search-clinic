"""Offline v5 metrics use positive relevance and fixed precision denominators."""
import json
import math

import pytest

from searchclinic.research_v5 import evaluation


def fixture_runs():
    queries = [
        {"query_id": "f", "stratum": "failure", "concept_id": "one"},
        {"query_id": "h", "stratum": "healthy", "concept_id": "two"},
    ]
    qrels = {"f": {"a": 2, "b": 1, "zero": 0}, "h": {"c": 1}}
    arms = {
        "no_repair": {"f": ["b", "a", "zero"], "h": ["c"]},
        "repair": {"f": ["a", "b"], "h": ["x", "c"]},
    }
    return queries, qrels, arms


def test_hand_computed_graded_metrics_and_harm():
    result = evaluation.score_runs(*fixture_runs(), bootstrap_samples=40)
    ideal = 3 + 1 / math.log2(3)
    assert result["per_query"]["no_repair"]["f"] == pytest.approx({
        "ndcg10": (1 + 3 / math.log2(3)) / ideal,
        "recall10": 1, "precision5": 2 / 5,
    })
    assert result["per_query"]["repair"]["f"]["ndcg10"] == 1
    assert result["summaries"]["repair"]["failure"]["count"] == 1
    comparison = result["comparisons"]["repair"]
    assert comparison["failure_improved_query_ids"] == ["f"]
    assert comparison["healthy_regressed_query_ids"] == ["h"]
    assert comparison["overall"]["ndcg10"]["mean_difference"] == pytest.approx(
        ((1 - (1 + 3 / math.log2(3)) / ideal) + 1 / math.log2(3) - 1) / 2
    )
    json.dumps(result, allow_nan=False)


def test_empty_ranking_and_all_zero_qrels_are_explicit_zero():
    queries, qrels, arms = fixture_runs()
    qrels["f"] = {"a": 0}
    arms["repair"]["f"] = []
    result = evaluation.score_runs(queries, qrels, arms, bootstrap_samples=10)
    assert result["per_query"]["repair"]["f"] == {
        "ndcg10": 0, "recall10": 0, "precision5": 0,
    }


@pytest.mark.parametrize("tamper", [
    lambda q, r, a: q.append(dict(q[0])),
    lambda q, r, a: r.pop("f"),
    lambda q, r, a: r.update(f=None),
    lambda q, r, a: r["f"].update(a=-1),
    lambda q, r, a: r["f"].update(a=float("nan")),
    lambda q, r, a: r["f"].update(a=True),
    lambda q, r, a: r["f"].update(a=1.5),
    lambda q, r, a: a["repair"].pop("h"),
    lambda q, r, a: a["repair"].update(extra=[]),
    lambda q, r, a: a["repair"].update(f=["a", "a"]),
    lambda q, r, a: q[0].update(stratum="ambiguous"),
    lambda q, r, a: q[0].pop("concept_id"),
    lambda q, r, a: a.pop("no_repair"),
])
def test_score_rejects_missing_ambiguous_or_tampered_rows(tamper):
    queries, qrels, arms = fixture_runs()
    tamper(queries, qrels, arms)
    with pytest.raises(ValueError):
        evaluation.score_runs(queries, qrels, arms, bootstrap_samples=10)


def test_cluster_bootstrap_preserves_dependence_and_query_weighting():
    queries = [{"query_id": q, "stratum": "failure", "concept_id": g}
               for q, g in [("a", "A"), ("b", "A"), ("c", "B")]]
    qrels = {q["query_id"]: {"yes": 1} for q in queries}
    arms = {"no_repair": {"a": [], "b": [], "c": ["yes"]},
            "repair": {"a": ["yes"], "b": ["yes"], "c": []}}
    result = evaluation.score_runs(queries, qrels, arms, bootstrap_samples=1000, seed=7)
    stat = result["comparisons"]["repair"]["overall"]["ndcg10"]
    assert stat["mean_difference"] == pytest.approx(1 / 3)
    # Sampling concept groups permits {-1, 1/3, 1}, rather than treating
    # the two copies of A as independently observed concepts.
    assert stat["ci95"] == [-1, 1]
    assert stat["independent_groups"] == 2
    assert result == evaluation.score_runs(queries, qrels, arms, bootstrap_samples=1000, seed=7)
    one_group = evaluation.score_runs(queries, qrels, arms, groups={q: "one" for q in qrels}, bootstrap_samples=20)
    stat = one_group["comparisons"]["repair"]["overall"]["ndcg10"]
    assert stat["ci95"] is None
    assert stat["inference_status"] == "insufficient_independent_groups"
    assert stat["superiority_claim"] is False


def test_oracle_includes_no_repair_and_useful_rejections():
    result = evaluation.oracle_analysis(
        {"a": .4, "b": .7, "c": .3},
        {"a": {"good": .8, "bad": .1}, "b": {"bad": .2}, "c": {"good": .5}},
        {"a": "bad", "b": None, "c": "good"},
    )
    assert result["diagnostic_only"] is True
    assert result["per_query"]["a"]["available_gain"] == pytest.approx(.4)
    assert result["per_query"]["a"]["selected_gain"] == pytest.approx(-.3)
    assert result["per_query"]["a"]["useful_rejected"] == ["good"]
    assert result["per_query"]["b"]["oracle_score"] == .7
    assert result["per_query"]["c"]["useful_selected"] == ["good"]
    assert result["available_gain_mean"] == pytest.approx(.2)
    assert result["selected_gain_mean"] == pytest.approx(-.1 / 3)


@pytest.mark.parametrize("baseline,candidates,selected", [
    ({"a": .2}, {}, {"a": None}),
    ({"a": .2}, {"a": {}}, {}),
    ({"a": .2}, {"a": {"x": .3}}, {"a": "missing"}),
    ({"a": float("inf")}, {"a": {}}, {"a": None}),
    ({"a": .2}, {"a": {"x": None}}, {"a": None}),
])
def test_oracle_rejects_incomplete_and_invalid_inputs(baseline, candidates, selected):
    with pytest.raises(ValueError):
        evaluation.oracle_analysis(baseline, candidates, selected)


def test_matched_random_uses_distinct_queries_and_is_order_invariant():
    eligible = {"c": ["x", "y"], "a": ["p"], "b": ["q"]}
    selected = evaluation.matched_random_selection(eligible, 2, 41)
    assert len(selected) == 2
    assert all(cid in eligible[qid] for qid, cid in selected.items())
    assert selected == evaluation.matched_random_selection({"b": ["q"], "a": ["p"], "c": ["y", "x"]}, 2, 41)
    assert evaluation.matched_random_selection({}, 0, 41) == {}
    for invalid in [-1, 4, 1.5, True]:
        with pytest.raises(ValueError):
            evaluation.matched_random_selection(eligible, invalid, 41)
    with pytest.raises(ValueError):
        evaluation.matched_random_selection({"a": ["x", "x"]}, 1, 41)


def record(qid, query, docs, concepts):
    return dict(query_id=qid, query=query, document_ids=docs, concept_ids=concepts)


def test_split_audit_reports_unicode_duplicates_and_cross_split_leakage():
    result = evaluation.audit_splits({
        "dev": [record("d", "Café   검색", ["doc"], ["concept"])],
        "test": [record("t", "CAFE\u0301 검색", ["doc"], ["concept"])],
    })
    assert result["valid"] is False
    assert {issue["kind"] for issue in result["issues"]} == {
        "normalized_query_duplicate", "document_overlap", "concept_overlap",
    }
    json.dumps(result)


def test_split_audit_rejects_missing_metadata_and_detects_duplicate_query_id():
    with pytest.raises(ValueError):
        evaluation.audit_splits({"test": [{"query_id": "x", "query": "q"}]})
    result = evaluation.audit_splits({"dev": [record("x", "a", [], ["c"])],
                                     "test": [record("x", "b", [], ["d"])]})
    assert {issue["kind"] for issue in result["issues"]} == {"duplicate_query_id"}
    assert evaluation.audit_splits({"dev": [record("x", "a", [], ["c"])]})["valid"]
