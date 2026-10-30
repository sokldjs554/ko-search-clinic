"""Saved development diagnostics must not silently promote or drop evidence."""
import importlib.util
from pathlib import Path


def replay_module():
    path = Path(__file__).parents[1] / "scripts/replay_saved_development.py"
    assert path.exists(), "saved replay implementation is missing"
    spec = importlib.util.spec_from_file_location("saved_development", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_duplicate_saved_prescriptions_keep_both_sources_and_first_order():
    module = replay_module()
    rx = {"target_query": "q", "synonym_groups": [{"terms": ["a", "b"]}]}
    other = {"target_query": "q", "synonym_groups": [{"terms": ["a", "c"]}]}
    runs = {
        "always.json": {"queries": [{"query_id": "Q", "query": "q", "trace": [
            {"prescription": rx}, {"prescription": other}]}]},
        "selective.json": {"queries": [{"query_id": "Q", "query": "q", "trace": [
            {"prescription": dict(reversed(list(rx.items())))}]}]},
    }
    candidates = module.collect_candidates(runs)["Q"]
    assert len(candidates) == 2
    assert candidates[0]["prescription"] == rx
    assert [s["path"] for s in candidates[0]["sources"]] == ["always.json", "selective.json"]


def test_overlap_groups_include_transitive_shared_judged_documents():
    module = replay_module()
    groups = module.overlap_groups({"a": {"x": 2}, "b": {"x": 1, "y": 2},
                                    "c": {"y": 1}, "d": {"z": 2}})
    assert groups["a"] == groups["b"] == groups["c"]
    assert groups["d"] != groups["a"]


def test_gate_mean_tolerance_does_not_override_other_query_regression():
    module = replay_module()
    baseline = {"t": {"ndcg10": 0., "recall10": 0., "precision5": 0.},
                "h": {"ndcg10": 1., "recall10": 1., "precision5": 1.}}
    changed = {"t": {"ndcg10": .1, "recall10": .1, "precision5": .1},
               "h": {"ndcg10": .9, "recall10": 1., "precision5": 1.}}
    verdict = module.diagnose_gate(baseline, changed, "t", mean_tolerance=.02)
    assert verdict["accepted"] is False
    assert verdict["reason_codes"] == ["other_query_regression"]
    assert verdict["regression_query_ids"] == ["h"]


def test_strict_mean_gate_catches_small_distributed_losses_legacy_allows():
    module = replay_module()
    baseline = {"t": {"ndcg10": 0., "recall10": 0., "precision5": 0.}}
    changed = {"t": {"ndcg10": .05, "recall10": 0., "precision5": 0.}}
    for i in range(10):
        baseline[str(i)] = {"ndcg10": 1., "recall10": 1., "precision5": 1.}
        changed[str(i)] = {"ndcg10": .99, "recall10": 1., "precision5": 1.}
    assert module.diagnose_gate(baseline, changed, "t", mean_tolerance=.02)["accepted"]
    strict = module.diagnose_gate(baseline, changed, "t", mean_tolerance=1e-12)
    assert strict["accepted"] is False
    assert strict["reason_codes"] == ["mean_ndcg_decline"]


def test_saved_query_identity_conflict_is_not_merged():
    import pytest
    module = replay_module()
    with pytest.raises(ValueError, match="identity"):
        module.collect_candidates({"a": {"queries": [{"query_id": "Q", "query": "one", "trace": []}]},
                                   "b": {"queries": [{"query_id": "Q", "query": "two", "trace": []}]}})
