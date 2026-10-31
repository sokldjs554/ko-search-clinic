"""Offline verifier: submitted semantic judgments are fixtures, never model calls."""
import importlib.util
import json

import pytest
from pydantic import ValidationError


def test_semantic_verifier_module_exists():
    assert importlib.util.find_spec("searchclinic.research_v5.semantic") is not None


def context():
    return {
        "query_id": "q1", "query": "케잌 주문", "query_tokens": ["케잌", "주문"],
        "observation": {"query_id": "q1", "query": "케잌 주문", "split": "dev", "result_count": 0},
        "search_total": 0, "grep_total": 1, "similar": [],
        "documents": [{"doc_id": "d1", "text": "케잌은 케이크의 표기 변형이다.", "tokens": ["케이크"]}],
    }


def candidate(terms=None):
    return {"target_query": "케잌 주문", "diagnosis_family": "spelling_variant",
            "reasoning": "관찰 문서에서 두 표기가 같은 대상을 가리킨다.",
            "synonym_groups": [{"terms": terms or ["케잌", "케이크"]}]}


def semantic():
    from searchclinic.research_v5 import semantic as api
    return api


def verdict(c=None, p=None, condition="rubric", **changes):
    api = semantic()
    request = api.prepare_judge_request(c or context(), p or candidate(), condition)
    value = {"request_hash": request.request_hash, "context_hash": request.context_hash,
             "candidate_hash": request.candidate_hash, "condition": condition,
             "protocol_id": request.protocol_id, "model_id": "fixture-model-v1",
             "assessments": [{"patch_id": "synonym:0", "relation": "equivalent",
                              "same_referent": True, "scope_preserved": True,
                              "context_supported": True, "confidence": 0.95,
                              "reasoning": "표기 변형으로 같은 대상을 가리킨다.",
                              "citations": [{"doc_id": "d1", "quote": "케잌은 케이크의 표기 변형이다.",
                                             "start": 0, "end": 19}]}]}
    # Python offsets are Unicode code points, not UTF-8 byte offsets.
    value["assessments"][0]["citations"][0]["end"] = len(context()["documents"][0]["text"])
    value.update(changes)
    return value


def test_equivalent_cited_verdict_selects_candidate_and_exposes_model():
    api = semantic()
    decision = api.select_candidate(context(), [candidate()], [verdict()])
    assert decision.candidate_index == 0
    assert decision.candidate_decisions[0].model_id == "fixture-model-v1"


@pytest.mark.parametrize("relation", ["broader", "narrower", "category_value", "related", "unrelated", "uncertain"])
def test_non_equivalent_relation_is_held(relation):
    v = verdict()
    v["assessments"][0]["relation"] = relation
    result = semantic().select_candidate(context(), [candidate()], [v])
    assert result.candidate_index is None
    assert "non_equivalent_relation" in result.candidate_decisions[0].reasons


@pytest.mark.parametrize("flag", ["same_referent", "scope_preserved", "context_supported"])
@pytest.mark.parametrize("value", [False, None])
def test_missing_or_failed_semantic_criterion_holds(flag, value):
    v = verdict()
    v["assessments"][0][flag] = value
    assert semantic().select_candidate(context(), [candidate()], [v]).candidate_index is None


@pytest.mark.parametrize("change", ["quote", "span", "doc_id"])
def test_unbound_evidence_is_held(change):
    v = verdict()
    cite = v["assessments"][0]["citations"][0]
    cite[{"quote": "quote", "span": "start", "doc_id": "doc_id"}[change]] = {
        "quote": "완전히 다른 문장", "span": 1, "doc_id": "missing"}[change]
    result = semantic().select_candidate(context(), [candidate()], [v])
    assert result.candidate_index is None
    assert "invalid_citation" in result.candidate_decisions[0].reasons


def test_no_citation_cannot_claim_context_support():
    v = verdict()
    v["assessments"][0]["citations"] = []
    assert semantic().select_candidate(context(), [candidate()], [v]).candidate_index is None


def test_query_or_candidate_swaps_fail_binding():
    api = semantic()
    c = context()
    c["query_id"] = c["observation"]["query_id"] = "q2"
    for changed_context, changed_candidate in [(c, candidate()), (context(), candidate(["케잌", "디저트"]))]:
        result = api.select_candidate(changed_context, [changed_candidate], [verdict()])
        assert result.candidate_index is None
        assert "binding_mismatch" in result.candidate_decisions[0].reasons


def test_pair_payload_omits_context_but_remains_bound_and_is_explicit_ablation():
    api = semantic()
    pair = api.prepare_judge_request(context(), candidate(), "pair")
    contextual = api.prepare_judge_request(context(), candidate(), "context")
    rubric = api.prepare_judge_request(context(), candidate(), "rubric")
    assert "query" not in json.loads(pair.body)
    assert "documents" not in json.loads(pair.body)
    assert "케잌 주문" not in pair.body and "표기 변형이다" not in pair.body
    assert json.loads(contextual.body)["query"] == "케잌 주문"
    assert "rubric" not in json.loads(contextual.body)
    assert "rubric" in json.loads(rubric.body)
    assert len({pair.request_hash, contextual.request_hash, rubric.request_hash}) == 3
    assert pair == api.prepare_judge_request(context(), candidate(), "pair")
    v = verdict(condition="pair")
    v["assessments"][0].update(context_supported=None, citations=[])
    assert api.select_candidate(context(), [candidate()], [v], condition="pair").candidate_index is None
    result = api.select_candidate(context(), [candidate()], [v], condition="pair", require_context=False)
    assert result.candidate_index == 0
    assert "pair_only_weaker_semantics" in result.reasons


def test_judge_body_declares_output_contract_without_revealing_pair_context():
    body = json.loads(semantic().prepare_judge_request(context(), candidate(), "pair").body)
    schema = body["assessment_schema"]
    assert {"patch_id", "relation", "scope_preserved", "same_referent", "context_supported", "confidence"} <= set(schema["required"])
    assert schema["additionalProperties"] is False
    assert "null" in json.dumps(schema["properties"]["context_supported"])
    assert body["context_available"] is False


def test_missing_verdict_and_all_held_are_explicit():
    api = semantic()
    result = api.select_candidate(context(), [candidate()], [])
    assert result.candidate_index is None
    assert result.candidate_decisions[0].reasons == ("missing_verdict",)
    assert "all_candidates_held" in result.reasons


@pytest.mark.parametrize("confidence", [float("nan"), float("inf"), -0.01, 1.01, True, "0.95"])
def test_malformed_numeric_confidence_fails_closed(confidence):
    v = verdict()
    v["assessments"][0]["confidence"] = confidence
    assert semantic().select_candidate(context(), [candidate()], [v]).candidate_index is None


@pytest.mark.parametrize("where", ["verdict", "assessment", "citation"])
def test_final_feedback_fields_are_forbidden(where):
    v = verdict()
    target = {"verdict": v, "assessment": v["assessments"][0],
              "citation": v["assessments"][0]["citations"][0]}[where]
    target["qrels"] = {"d1": 1}
    with pytest.raises(ValidationError):
        semantic().SemanticVerdict.model_validate(v)
    assert semantic().select_candidate(context(), [candidate()], [v]).candidate_index is None


def test_final_feedback_in_public_input_or_prescription_is_rejected():
    api = semantic()
    c = context()
    c["final_label"] = "positive"
    with pytest.raises(ValueError):
        api.prepare_judge_request(c, candidate(), "rubric")
    p = candidate()
    p["synonym_groups"][0]["acceptance_feedback"] = True
    with pytest.raises(ValueError):
        api.prepare_judge_request(context(), p, "rubric")


def test_every_synonym_group_requires_assessment_and_worst_confidence_wins():
    api = semantic()
    p = candidate()
    p["synonym_groups"].append({"terms": ["주문", "오더"]})
    v = verdict(p=p)
    result = api.select_candidate(context(), [p], [v])
    assert result.candidate_index is None
    assert "patch_coverage_mismatch" in result.candidate_decisions[0].reasons
    second = dict(v["assessments"][0], patch_id="synonym:1", confidence=0.79)
    v["assessments"].append(second)
    assert api.select_candidate(context(), [p], [v]).candidate_index is None
    second["confidence"] = 0.8
    assert api.select_candidate(context(), [p], [v]).candidate_index == 0
    second["relation"] = "category_value"
    assert api.select_candidate(context(), [p], [v]).candidate_index is None


def test_at_most_one_candidate_selected_by_confidence_then_input_order():
    api = semantic()
    first, second = candidate(), candidate(["케이크", "케잌"])
    v1, v2 = verdict(p=first), verdict(p=second)
    assert api.select_candidate(context(), [first, second], [v1, v2]).candidate_index == 0
    v2["assessments"][0]["confidence"] = 0.99
    assert api.select_candidate(context(), [first, second], [v1, v2]).candidate_index == 1


def test_protocol_model_identity_and_duplicate_patch_ids_fail_closed():
    api = semantic()
    for field, value in [("protocol_id", "other-protocol"), ("model_id", "")]:
        v = verdict(**{field: value})
        assert api.select_candidate(context(), [candidate()], [v]).candidate_index is None
    v = verdict()
    v["assessments"].append(v["assessments"][0])
    assert api.select_candidate(context(), [candidate()], [v]).candidate_index is None


def test_request_and_verdict_schemas_are_frozen_and_unsupported_modes_rejected():
    api = semantic()
    request = api.prepare_judge_request(context(), candidate(), "rubric")
    with pytest.raises(ValidationError):
        request.condition = "pair"
    with pytest.raises(ValidationError):
        api.SemanticVerdict.model_validate(verdict()).model_id = "changed"
    with pytest.raises(ValueError):
        api.prepare_judge_request(context(), candidate(), "qrels")


@pytest.mark.parametrize("threshold", [float("nan"), float("inf"), -0.1, 1.1, True])
def test_invalid_threshold_rejected(threshold):
    with pytest.raises(ValueError):
        semantic().select_candidate(context(), [candidate()], [verdict()], min_confidence=threshold)
