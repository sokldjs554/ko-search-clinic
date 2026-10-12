"""Research contracts: labels, missing values, leakage and intervention safety."""
import pytest


def observation(**kwargs):
    from searchclinic.research.models import RetrievalObservation
    return RetrievalObservation(query_id="q1", query="후라이팬", split="dev", **kwargs)


def test_missing_observations_stay_null():
    o = observation()
    assert o.top1_score is None and o.lexical_coverage is None
    assert o.model_dump()["grounding_score"] is None


def test_policy_view_removes_all_evaluation_labels():
    o = observation(family="garbage_split", baseline_ndcg=0.9, baseline_recall=1.0)
    view = o.policy_view()
    assert not {"family", "baseline_ndcg", "baseline_recall"} & view.model_dump().keys()


@pytest.mark.parametrize("kwargs", [{"result_count": -1}, {"lexical_coverage": 1.1},
                                    {"top1_score": float("nan")}, {"latency_ms": -1}])
def test_invalid_observations_rejected(kwargs):
    with pytest.raises(ValueError):
        observation(**kwargs)


def test_detector_uses_trace_instead_of_family():
    from searchclinic.research.detector import RuleDetector
    d = RuleDetector()
    a = observation(result_count=0, family=None)
    b = a.model_copy(update={"family": "synonym_gap", "baseline_ndcg": 1.0})
    assert d.detect(a.policy_view()) == d.detect(b.policy_view())
    assert d.detect(a.policy_view()).predicted_failure is True
    assert d.detect(observation().policy_view()).predicted_failure is None


def test_nonzero_results_without_quality_signals_require_abstention():
    from searchclinic.research.detector import RuleDetector
    result = RuleDetector().detect(observation(result_count=2).policy_view())
    assert result.predicted_failure is None


@pytest.mark.parametrize("kwargs", [{"model_calls": 0.5}, {"input_tokens": True}])
def test_cost_counts_must_be_integers(kwargs):
    from searchclinic.research.costs import CostRecord
    with pytest.raises(ValueError):
        CostRecord(**kwargs)


def test_unknown_api_cost_is_not_zero_cost_in_policy():
    from searchclinic.research.costs import CostRecord, utility
    assert utility(1, 0, CostRecord(api_cost_usd=None)) is None


def test_healthy_trace_selects_no_op():
    from searchclinic.research.detector import RuleDetector
    from searchclinic.research.policy import select_action, Budget
    o = observation(result_count=2, lexical_coverage=1.0, score_margin=0.8)
    decision = select_action(RuleDetector().detect(o.policy_view()), [], Budget())
    assert decision.action.value == "no_op"


def test_high_failure_without_evidence_abstains():
    from searchclinic.research.detector import RuleDetector
    from searchclinic.research.policy import select_action, Budget
    d = RuleDetector().detect(observation(result_count=0).policy_view())
    assert select_action(d, [], Budget()).action.value == "abstain"


def test_all_six_action_kinds_have_explicit_contract():
    from searchclinic.research.actions import ActionKind
    assert {x.value for x in ActionKind} == {"no_op", "typed_patch", "rewrite_query",
        "switch_or_fuse_retriever", "rerank", "abstain"}


def test_cost_utility_can_block_an_evidenced_patch():
    from searchclinic.research.detector import RuleDetector
    from searchclinic.research.policy import select_action, Budget
    from searchclinic.research.actions import Candidate, ActionKind
    from searchclinic.research.costs import CostRecord
    from searchclinic.research.models import EvidenceSpan
    e = EvidenceSpan(source_type="query", source_id="후라이팬", start=0, end=4, text="후라이팬")
    c = Candidate(ActionKind.TYPED_PATCH, evidence=(e,), cost=CostRecord(model_calls=100))
    d = RuleDetector().detect(observation(result_count=0).policy_view())
    assert select_action(d, [c], Budget()).reason == "nonpositive_utility"


def test_exhausted_budget_fails_closed():
    from searchclinic.research.detector import RuleDetector
    from searchclinic.research.policy import select_action, Budget
    d = RuleDetector().detect(observation(result_count=0).policy_view())
    assert select_action(d, [], Budget(used_actions=3)).reason == "budget_exhausted"


def test_cost_aggregation_preserves_unknown_usage():
    from searchclinic.research.costs import CostRecord, aggregate_costs, utility
    a = CostRecord(search_calls=2, model_calls=1, input_tokens=20, output_tokens=10,
                   latency_ms=5, api_cost_usd=0.1)
    b = CostRecord(search_calls=3, input_tokens=None, latency_ms=7, api_cost_usd=None)
    c = aggregate_costs([a, b])
    assert c.search_calls == 5 and c.model_calls == 1 and c.output_tokens == 10
    assert c.latency_ms == 12 and c.input_tokens is None and c.api_cost_usd is None
    assert utility(quality_gain=1, healthy_regression=0, cost=c) is None
    assert utility(quality_gain=1, healthy_regression=1, cost=a) < 0
    with pytest.raises(ValueError):
        CostRecord(search_calls=-1)


def split_row(query_id, query, split, **kwargs):
    from searchclinic.research.splits import SplitRow
    return SplitRow(query_id=query_id, query=query, split=split,
        document_ids=[kwargs.get("doc", query_id)], template_id=kwargs.get("template", query_id),
        synonym_group_ids=[kwargs.get("group", query_id)])


@pytest.mark.parametrize("dimension", ["doc", "template", "group", "query", "query_id"])
def test_split_leakage_blocked_in_every_dimension(dimension):
    from searchclinic.research.splits import validate_splits
    a = split_row("a", "A", "dev", doc="d1")
    b = split_row("b", "B", "test", doc="d2")
    field = {"doc": "document_ids", "template": "template_id",
             "group": "synonym_group_ids"}.get(dimension, dimension)
    b = b.model_copy(update={field: getattr(a, field)})
    with pytest.raises(ValueError, match="leak|duplicate"):
        validate_splits([a, b])


def test_normalized_query_leakage_blocked():
    from searchclinic.research.splits import validate_splits
    with pytest.raises(ValueError, match="leak"):
        validate_splits([split_row("a", "Bluetooth   스피커", "dev"),
                         split_row("b", "bluetooth 스피커", "test")])


@pytest.mark.parametrize("split", ["train", "test"])
def test_threshold_and_lambda_freeze_accepts_dev_only(split):
    from searchclinic.research.calibration import freeze_config
    with pytest.raises(ValueError, match="dev"):
        freeze_config([split_row("a", "A", split)], {"threshold": 0.5})


def test_dev_config_freeze_is_deterministic():
    from searchclinic.research.calibration import freeze_config
    rows = [split_row("a", "A", "dev")]
    a = freeze_config(rows, {"threshold": 0.5})
    assert a == freeze_config(rows, {"threshold": 0.5})
    assert len(a["split_hash"]) == 64


def test_prepare_keeps_exposed_v1_out_of_test():
    from searchclinic.research.splits import prepare_manifest
    from searchclinic.corpus import load_catalog, load_evalset
    m = prepare_manifest(load_evalset(), load_catalog())
    assert len(m["rows"]) == 36
    assert m["counts"] == {"train": 0, "dev": 36, "test": 0}
    assert m["heldout_status"] == "not_collected"
    assert m == prepare_manifest(load_evalset(), load_catalog())
