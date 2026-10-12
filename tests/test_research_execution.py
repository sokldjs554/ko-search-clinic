"""Real-engine safety, regression rejection, replay and metric definitions."""
import pytest
from searchclinic.corpus import load_catalog, load_evalset
from searchclinic.patch.ir import Prescription


@pytest.fixture(scope="module")
def engine():
    from searchclinic.research.costs import MeasuredEngine
    return MeasuredEngine(load_catalog())


def rx(terms=("프라이팬", "후라이팬")):
    return Prescription(target_query="후라이팬", diagnosis_family="spelling_variant",
        reasoning="비표준 표기와 원문 표준 표기의 자모 근거를 연결한다.",
        synonym_groups=[{"terms": list(terms)}])


def candidate(engine, prescription):
    from searchclinic.research.actions import Candidate, ActionKind, evidence_for
    return Candidate(ActionKind.TYPED_PATCH, prescription=prescription,
                     evidence=evidence_for(engine, prescription))


def test_observation_adapter_measures_real_scores_and_null_signals(engine):
    from searchclinic.research.observations import observe
    o = observe(engine, "후라이팬", "q1", "dev")
    assert o.result_count == 0 and o.top1_score is None and o.top2_score is None
    assert o.retriever_agreement is None and o.grounding_score is None
    healthy = observe(engine, "프라이팬", "q2", "dev")
    assert healthy.lexical_coverage == 1.0 and healthy.latency_ms >= 0
    assert healthy.top1_score >= healthy.top2_score > 0


def test_gate_requires_full_healthy_and_failure_suite(engine):
    from searchclinic.research.gate_adapter import GateAdapter
    with pytest.raises(ValueError, match="evalset"):
        GateAdapter(engine, load_evalset()[:-1])


@pytest.mark.parametrize("kwargs", [{"epsilon": float("nan")}, {"epsilon": 1.0},
                                    {"min_gain": 0.0}])
def test_gate_adapter_cannot_relax_the_v1_acceptance_contract(engine, kwargs):
    from searchclinic.research.gate_adapter import GateAdapter
    with pytest.raises(ValueError, match="contract"):
        GateAdapter(engine, load_evalset(), **kwargs)


def test_mutating_gate_config_after_construction_still_fails_closed(engine):
    from searchclinic.research.gate_adapter import GateAdapter
    gate = GateAdapter(engine, load_evalset())
    gate.epsilon = float("nan")
    assert gate.submit(candidate(engine, rx()))["reason"] == "invalid_configuration"
    assert gate.engine is engine


def test_patch_without_evidence_never_reaches_gate(engine):
    from searchclinic.research.gate_adapter import GateAdapter
    from searchclinic.research.actions import Candidate, ActionKind
    gate = GateAdapter(engine, load_evalset())
    result = gate.submit(Candidate(ActionKind.TYPED_PATCH, prescription=rx()))
    assert not result["accepted"] and result["reason"] == "invalid_evidence"
    assert gate.engine is engine and not gate.accepted


def test_forged_span_cannot_authorize_a_patch(engine):
    from searchclinic.research.gate_adapter import GateAdapter
    from dataclasses import replace
    c = candidate(engine, rx())
    c = replace(c, evidence=tuple(e.model_copy(update={"text": "forged"}) for e in c.evidence))
    assert GateAdapter(engine, load_evalset()).submit(c)["reason"] == "invalid_evidence"


def test_unrelated_synonym_blocked_even_with_real_spans(engine):
    from searchclinic.research.gate_adapter import GateAdapter
    c = candidate(engine, rx(("선풍기", "후라이팬")))
    assert c.evidence
    assert GateAdapter(engine, load_evalset()).submit(c)["reason"] == "unsupported_relation"


def test_rejected_patch_does_not_mutate_engine_and_feedback_enables_narrowing(engine):
    from searchclinic.research.gate_adapter import GateAdapter
    gate = GateAdapter(engine, load_evalset())
    bad = gate.submit(candidate(engine, rx(("프라이팬", "후라이팬", "팬"))))
    assert not bad["accepted"] and gate.engine is engine
    assert bad["regressions"] and "기각" in bad["feedback"]
    good = gate.submit(candidate(engine, rx()))
    assert good["accepted"] and len(gate.accepted) == 1
    assert good["attempt"] == 2 and good["previous_feedback"] == bad["feedback"]


def test_actual_budget_blocks_fourth_submission(engine):
    from searchclinic.research.gate_adapter import GateAdapter
    gate = GateAdapter(engine, load_evalset())
    c = candidate(engine, rx(("프라이팬", "후라이팬", "팬")))
    for _ in range(3):
        assert not gate.submit(c)["accepted"]
    assert gate.submit(candidate(engine, rx()))["reason"] == "budget_exhausted"
    assert gate.engine is engine


def test_unknown_and_cross_session_target_blocked(engine):
    from searchclinic.research.gate_adapter import GateAdapter
    gate = GateAdapter(engine, load_evalset())
    gate.start_session("티슈")
    assert gate.submit(candidate(engine, rx()))["reason"] == "target_mismatch"


def test_search_and_sandbox_reindex_are_measured(engine):
    from searchclinic.research.costs import MeasuredEngine
    e = MeasuredEngine(load_catalog())
    e.search("프라이팬")
    child = e.with_config(rx().apply_to(e.config))
    child.search("후라이팬")
    assert e.meter.search_calls == 2 and e.meter.reindexes == 2


def test_detector_metrics_handle_ties_and_exact_probabilities():
    from searchclinic.research.metrics import detection_metrics
    a = detection_metrics([False, True], [0.1, 0.9])
    assert a["auroc"] == 1 and a["auprc"] == 1 and a["f1"] == 1
    assert a["brier"] == pytest.approx(0.01)
    assert a["ece"] == pytest.approx(0.1)
    b = detection_metrics([False, True], [0.5, 0.5])
    assert b["auroc"] == 0.5 and b["auprc"] == 0.5
    assert detection_metrics([True], [0.9])["auroc"] is None


def test_missing_detector_scores_do_not_become_measured_zero_metrics():
    from searchclinic.research.metrics import detection_metrics
    result = detection_metrics([True, False], [None, None])
    assert result["precision"] is None and result["f1"] is None


def test_protocol_drives_detector_and_policy_values():
    from searchclinic.research.runner import load_protocol
    from searchclinic.research.detector import RuleDetector
    p = load_protocol()
    assert RuleDetector(p["detector"]).threshold == p["detector"]["threshold"]


def test_unsupported_actions_fail_closed(engine):
    from searchclinic.research.gate_adapter import GateAdapter
    from searchclinic.research.actions import Candidate, ActionKind
    gate = GateAdapter(engine, load_evalset())
    assert gate.submit(Candidate(ActionKind.RERANK))["reason"] == "unsupported_action"


def test_deterministic_offline_replay_has_actual_query_artifacts():
    from searchclinic.research.runner import run_experiment, replay_signature
    a = run_experiment("selective_rule")
    b = run_experiment("selective_rule")
    assert replay_signature(a) == replay_signature(b)
    assert len(a["queries"]) == 36
    assert a["summary"]["healthy_regression_count"] == 0
    assert a["costs"]["model_calls"] == 0
    assert a["costs"]["search_calls"] > 36
    assert all(x["observation"]["grounding_score"] is None for x in a["queries"])


def test_runner_checks_manifest_and_protocol_hash():
    from searchclinic.research.runner import run_experiment
    from searchclinic.research.splits import prepare_manifest
    m = prepare_manifest(load_evalset(), load_catalog())
    m["rows"][0]["split"] = "test"
    with pytest.raises(ValueError, match="hash|split"):
        run_experiment("no_repair", manifest=m)
