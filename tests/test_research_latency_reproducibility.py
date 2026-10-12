"""Controlled latency probes distinguish detection, abstention and measured costs."""
from dataclasses import asdict, replace

import pytest

from searchclinic.research.actions import ActionKind, Candidate
from searchclinic.research.costs import CostRecord, DEFAULT_WEIGHTS, utility
from searchclinic.research.models import Detection, EvidenceSpan
from searchclinic.research.policy import Budget, select_action


def detection():
    return Detection(failure_probability=0.95, predicted_failure=True,
                     failure_reason_codes=("zero_results",))


def candidate(ms):
    return Candidate(ActionKind.TYPED_PATCH, evidence=(EvidenceSpan(
        source_type="query", source_id="후라이팬", start=0, end=4, text="후라이팬"),),
        cost=CostRecord(latency_ms=ms))


def test_v1_measured_latency_changes_action_at_utility_boundary():
    d = detection()
    quick = select_action(d, [candidate(4249)], Budget())
    slow = select_action(d, [candidate(4250)], Budget())
    assert quick.action == ActionKind.TYPED_PATCH and quick.utility > 0
    assert slow.action == ActionKind.ABSTAIN and slow.reason == "nonpositive_utility"
    assert d.predicted_failure is True
    assert slow.action != ActionKind.NO_OP


@pytest.mark.parametrize("ms", [0, 4249, 4250, 6000, 1_000_000])
def test_v2_same_expected_cost_keeps_action_despite_measured_latency(ms):
    expected = CostRecord(latency_ms=None)
    c = replace(candidate(ms), expected_cost=expected)
    decision = select_action(detection(), [c], Budget(),
        weights={**DEFAULT_WEIGHTS, "latency_ms": 0.0}, cost_semantics="expected-v2")
    assert decision.action == ActionKind.TYPED_PATCH
    assert decision.utility == pytest.approx(0.0425)
    assert c.cost.latency_ms == ms and c.expected_cost.latency_ms is None


def test_zero_latency_weight_excludes_unknown_latency_without_fabricating_it():
    cost = CostRecord(latency_ms=None)
    assert utility(1, 0, cost, weights={**DEFAULT_WEIGHTS, "latency_ms": 0.0}) == pytest.approx(0.995)
    assert utility(1, 0, cost) is None
    assert asdict(cost)["latency_ms"] is None


def test_v2_high_expected_cost_abstains_while_detection_stays_failed():
    d = detection()
    c = replace(candidate(1), expected_cost=CostRecord(model_calls=100, latency_ms=None))
    result = select_action(d, [c], Budget(),
        weights={**DEFAULT_WEIGHTS, "latency_ms": 0.0}, cost_semantics="expected-v2")
    assert result.action == ActionKind.ABSTAIN and d.predicted_failure is True


def test_v2_missing_expected_cost_abstains_even_if_measurement_is_available():
    result = select_action(detection(), [candidate(1)], Budget(),
        weights={**DEFAULT_WEIGHTS, "latency_ms": 0.0}, cost_semantics="expected-v2")
    assert result.action == ActionKind.ABSTAIN and result.reason == "unknown_cost"


def test_v2_unknown_external_usage_is_not_ignored_by_zero_latency_weight():
    c = replace(candidate(1), expected_cost=CostRecord(model_calls=None, latency_ms=None))
    result = select_action(detection(), [c], Budget(),
        weights={**DEFAULT_WEIGHTS, "latency_ms": 0.0}, cost_semantics="expected-v2")
    assert result.action == ActionKind.ABSTAIN


def test_unknown_cost_semantics_fails_closed():
    with pytest.raises(ValueError, match="cost semantics"):
        select_action(detection(), [candidate(1)], Budget(), cost_semantics="invalid")


def test_real_candidate_generator_separates_clock_measurement_from_fixed_cost(monkeypatch):
    from searchclinic.corpus import load_catalog
    from searchclinic.research.costs import MeasuredEngine
    from searchclinic.research import runner
    e = MeasuredEngine(load_catalog())
    expected = CostRecord(latency_ms=None)
    ticks = iter([0.0, 6.0])
    monkeypatch.setattr(runner, "perf_counter", lambda: next(ticks))
    generated = runner.propose_candidates(e, "후라이팬", expected_cost=expected)
    assert generated and generated[0].prescription.target_query == "후라이팬"
    assert generated[0].cost.latency_ms == 6000
    assert generated[0].expected_cost == expected


def test_v2_protocol_is_separate_and_leaves_detector_threshold_unchanged():
    from searchclinic.research.runner import load_protocol
    a, b = load_protocol(), load_protocol("phase01-v2")
    assert a["version"] == "phase01-v1" and b["version"] == "phase01-v2"
    assert a["policy"]["weights"]["latency_ms"] == 0.00001
    assert b["policy"]["weights"]["latency_ms"] == 0
    assert a["detector"] == b["detector"]
    assert b["policy"]["expected_action_cost"]["latency_ms"] is None


def test_v2_runner_records_both_cost_scopes_and_new_protocol():
    from searchclinic.research.runner import run_experiment
    run = run_experiment("selective_rule", protocol_version="phase01-v2")
    assert run["protocol_version"] == "phase01-v2"
    assert run["costs"]["latency_ms"] > 0
    decisions = [e for q in run["queries"] for e in q["policy_events"] if e.get("expected_cost")]
    assert decisions and all(e["expected_cost"]["latency_ms"] is None for e in decisions)
    assert all(e["measured_candidate_generation_cost"]["latency_ms"] >= 0 for e in decisions)


def test_cli_v2_evaluation_uses_a_separate_root_and_protocol(tmp_path):
    import json
    from searchclinic.cli import main
    root = str(tmp_path)
    assert main(["research", "prepare", "--root", root, "--protocol-version", "phase01-v2"]) == 0
    assert main(["research", "run", "--root", root, "--policy", "no_repair",
                 "--protocol-version", "phase01-v2"]) == 0
    artifact = next((tmp_path / "runs").glob("*.json"))
    assert json.loads(artifact.read_text(encoding="utf-8"))["protocol_version"] == "phase01-v2"


def test_run_cannot_select_a_protocol_outside_supported_versions():
    from searchclinic.research.runner import run_experiment
    with pytest.raises(ValueError, match="protocol"):
        run_experiment("no_repair", protocol_version="not-a-version")


def test_no_repair_cannot_escape_all_run_provenance_checks():
    from copy import deepcopy
    from searchclinic.research.runner import run_experiment
    from searchclinic.research.artifacts import compare_runs, render_report
    base = run_experiment("no_repair")
    a, s = deepcopy(base), deepcopy(base)
    a["policy"], s["policy"] = "always_typed_patch", "selective_rule"
    base["source_hash"] = "different-source"
    for check in (compare_runs, render_report):
        with pytest.raises(ValueError, match="source_hash"):
            check([base, a, s])


def test_cli_v2_cannot_append_to_any_root_containing_v1_runs(tmp_path):
    import json
    from searchclinic.cli import main
    root = str(tmp_path)
    assert main(["research", "prepare", "--root", root]) == 0
    assert main(["research", "run", "--root", root, "--policy", "no_repair"]) == 0
    existing = list((tmp_path / "runs").glob("*.json"))
    original = json.loads(existing[0].read_text(encoding="utf-8"))
    assert main(["research", "run", "--root", root, "--policy", "selective_rule",
                 "--protocol-version", "phase01-v2"]) == 1
    assert len(list((tmp_path / "runs").glob("*.json"))) == 1
    assert json.loads(existing[0].read_text(encoding="utf-8")) == original


def test_cli_report_must_match_the_requested_protocol_version(tmp_path):
    from searchclinic.cli import main
    root = str(tmp_path)
    assert main(["research", "prepare", "--root", root]) == 0
    assert main(["research", "run", "--root", root, "--policy", "no_repair"]) == 0
    assert main(["research", "report", "--root", root,
                 "--protocol-version", "phase01-v2"]) == 1
    assert not (tmp_path / "summaries/RESULTS.md").exists()


def test_new_v2_default_cannot_touch_the_preserved_v1_root(tmp_path, monkeypatch):
    from searchclinic.cli import main
    monkeypatch.chdir(tmp_path)
    assert main(["research", "prepare", "--protocol-version", "phase01-v2"]) == 1
    assert not (tmp_path / "artifacts/research/splits/controlled-v1.json").exists()
