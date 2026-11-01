"""Bound, offline semantic verdict ingestion; no model or retrieval calls.

Lexical presence is not a semantic decision. This module prepares three judge
conditions over the same candidate and validates externally supplied judgments.
It cannot establish whether a model's semantic judgment is correct. Citations
establish only that the quoted text actually occurred in the public context.
"""
from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Mapping, Sequence
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from searchclinic.analysis.config import CompoundExpansion, SynonymGroup, UserWord
from searchclinic.patch.ir import Prescription
from searchclinic.research.phase2.contracts import Context

Condition = Literal["pair", "context", "rubric"]
Relation = Literal["equivalent", "broader", "narrower", "category_value", "related", "unrelated", "uncertain"]
PROTOCOL_ID = "semantic-verification-v5.1"
STRICT = ConfigDict(extra="forbid", strict=True, frozen=True, allow_inf_nan=False,
                    revalidate_instances="always")


class Strict(BaseModel):
    model_config = STRICT


class _UserWord(UserWord):
    model_config = STRICT


class _SynonymGroup(SynonymGroup):
    model_config = STRICT


class _CompoundExpansion(CompoundExpansion):
    model_config = STRICT


class _Prescription(Prescription):
    """Keep the existing patch validation while forbidding ignored extra data."""
    model_config = STRICT
    user_words: list[_UserWord] = Field(default_factory=list)
    synonym_groups: list[_SynonymGroup] = Field(default_factory=list)
    compound_expansions: list[_CompoundExpansion] = Field(default_factory=list)


def _raw(value: Any) -> Any:
    return value.model_dump(mode="python") if isinstance(value, BaseModel) else value


class SemanticInput(Strict):
    context: Context
    prescription: _Prescription
    condition: Condition = "rubric"

    @field_validator("context", mode="before")
    @classmethod
    def public_context(cls, value):
        return Context.model_validate(_raw(value), strict=True)

    @field_validator("prescription", mode="before")
    @classmethod
    def public_prescription(cls, value):
        return _Prescription.model_validate(_raw(value), strict=True)

    @model_validator(mode="after")
    def exact_query(self):
        if self.prescription.target_query != self.context.query:
            raise ValueError("prescription target must exactly match context query")
        return self


class JudgeRequest(Strict):
    """Send ``body`` to a judge; wrap its assessments with these binding fields.

    The offline caller also records the actual model_id in that verdict envelope.
    Binding metadata is recorded by the caller rather than guessed by the model.
    """
    request_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    context_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    candidate_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    condition: Condition
    protocol_id: str = Field(min_length=1)
    body: str = Field(min_length=1)


class Citation(Strict):
    """Offsets are Python Unicode code-point offsets, start inclusive/end exclusive."""
    doc_id: str = Field(min_length=1)
    quote: str = Field(min_length=1)
    start: int = Field(ge=0)
    end: int = Field(gt=0)


class PatchAssessment(Strict):
    patch_id: str = Field(min_length=1)
    relation: Relation
    same_referent: bool | None
    scope_preserved: bool | None
    context_supported: bool | None
    confidence: float = Field(ge=0, le=1)
    reasoning: str = Field(min_length=1)
    citations: tuple[Citation, ...] = Field(default=(), strict=False)


class SemanticVerdict(Strict):
    request_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    context_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    candidate_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    condition: Condition
    protocol_id: str = Field(min_length=1)
    model_id: str = Field(min_length=1, pattern=r".*\S.*")
    assessments: tuple[PatchAssessment, ...] = Field(strict=False)


class CandidateDecision(Strict):
    candidate_index: int = Field(ge=0)
    eligible: bool
    confidence: float | None = Field(default=None, ge=0, le=1)
    reasons: tuple[str, ...] = ()
    model_id: str | None = None
    request_hash: str | None = None


class SelectionDecision(Strict):
    candidate_index: int | None = Field(default=None, ge=0)
    reasons: tuple[str, ...]
    candidate_decisions: tuple[CandidateDecision, ...]


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def _digest(value: Any) -> str:
    return hashlib.sha256(_json(value).encode("utf-8")).hexdigest()


def _patches(prescription: Prescription) -> list[dict]:
    patches = []
    for i, word in enumerate(prescription.user_words):
        patches.append({"patch_id": f"user_word:{i}", "kind": "user_word", "terms": [word.form]})
    for i, group in enumerate(prescription.synonym_groups):
        patches.append({"patch_id": f"synonym:{i}", "kind": "synonym", "terms": group.terms})
    for i, compound in enumerate(prescription.compound_expansions):
        patches.append({"patch_id": f"compound_expansion:{i}", "kind": "compound_expansion",
                        "terms": [compound.word, *compound.parts]})
    return patches


def prepare_judge_request(context, prescription, condition: Condition = "rubric") -> JudgeRequest:
    """Build reproducible pair/context/rubric inputs without invoking an LLM.

    Pair omits the question, document text, diagnosis and candidate reasoning.
    Its binding hashes still change when the unseen public context changes.
    All modes require one assessment of the *whole* relation in each patch.
    """
    value = SemanticInput(context=context, prescription=prescription, condition=condition)
    c, p = value.context, value.prescription
    body = {"condition": condition, "patches": _patches(p),
            "context_available": condition != "pair",
            "task": "Assess every patch separately, considering every listed term. Return one assessment per patch using assessment_schema. When context_available is false, context_supported must be null and citations empty.",
            "assessment_schema": PatchAssessment.model_json_schema(),
            "relations": ["equivalent", "broader", "narrower", "category_value", "related", "unrelated", "uncertain"]}
    if condition != "pair":
        body.update(query=c.query, documents=[{"doc_id": d.doc_id, "text": d.text} for d in c.documents])
    if condition == "rubric":
        body["rubric"] = [
            "Equivalent requires the same referent and preserved query scope for every term in a synonym group.",
            "Distinguish equivalent spelling or cross-script variants from broader, narrower, category_value, related and unrelated relations.",
            "A category and one of its values or examples are not equivalent; shared document occurrence is not evidence of equivalence.",
            "For a user_word, assess whether retaining the whole surface form preserves the intended referent and query scope.",
            "For a compound_expansion, assess every part: shared spelling or reconstructing the word alone does not establish preserved query scope.",
            "Use the question and supplied document text as evidence, not final relevance labels, retrieval scores, or acceptance feedback.",
            "Cite exact document quotes with doc_id and Unicode start/end offsets. Set context_supported true only with supporting citations.",
            "Use uncertain and nullable booleans when the available input does not support a decision; report confidence between zero and one.",
        ]
    body_string = _json(body)
    bindings = {"context_hash": _digest(c.model_dump(mode="json")),
                "candidate_hash": _digest(p.model_dump(mode="json")),
                "condition": condition, "protocol_id": PROTOCOL_ID, "body": body_string}
    return JudgeRequest(request_hash=_digest(bindings), **bindings)


def _citation_valid(citation: Citation, documents: Mapping[str, str]) -> bool:
    text = documents.get(citation.doc_id)
    return (text is not None and citation.start < citation.end <= len(text)
            and text[citation.start:citation.end] == citation.quote)


def _parse_verdict(raw) -> SemanticVerdict:
    if isinstance(raw, (str, bytes)):
        return SemanticVerdict.model_validate_json(raw)
    return SemanticVerdict.model_validate(_raw(raw))


def _evaluate(index, c, p, raw, condition, threshold, require_context) -> CandidateDecision:
    try:
        request = prepare_judge_request(c, p, condition)
    except (ValueError, TypeError):
        return CandidateDecision(candidate_index=index, eligible=False, reasons=("invalid_candidate",))
    if raw is None:
        return CandidateDecision(candidate_index=index, eligible=False, reasons=("missing_verdict",),
                                 request_hash=request.request_hash)
    try:
        verdict = _parse_verdict(raw)
    except (ValueError, TypeError):
        return CandidateDecision(candidate_index=index, eligible=False, reasons=("malformed_verdict",),
                                 request_hash=request.request_hash)
    reasons = []
    for name in ("request_hash", "context_hash", "candidate_hash", "condition", "protocol_id"):
        if getattr(request, name) != getattr(verdict, name):
            reasons.append("binding_mismatch")
            break
    prescription = _Prescription.model_validate(_raw(p), strict=True)
    expected = {patch["patch_id"] for patch in _patches(prescription)}
    actual = [a.patch_id for a in verdict.assessments]
    if set(actual) != expected or len(actual) != len(expected):
        reasons.append("patch_coverage_mismatch")
    docs = {d.doc_id: d.text for d in c.documents}
    for assessment in verdict.assessments:
        if assessment.relation != "equivalent":
            reasons.append("non_equivalent_relation")
        if assessment.same_referent is not True:
            reasons.append("same_referent_not_confirmed")
        if assessment.scope_preserved is not True:
            reasons.append("scope_not_preserved")
        if assessment.confidence < threshold:
            reasons.append("low_confidence")
        if any(not _citation_valid(cite, docs) for cite in assessment.citations):
            reasons.append("invalid_citation")
        if condition == "pair":
            # A pair-only judge never received documents, even if a submitted
            # response claims to have considered them.
            if require_context:
                reasons.append("context_required_for_pair_condition")
            if assessment.context_supported is not None or assessment.citations:
                reasons.append("pair_context_claim_forbidden")
        elif require_context and (assessment.context_supported is not True or not assessment.citations):
            reasons.append("context_support_not_confirmed")
        elif assessment.context_supported is True and not assessment.citations:
            reasons.append("context_support_not_confirmed")
    confidence = min((a.confidence for a in verdict.assessments), default=None)
    return CandidateDecision(candidate_index=index, eligible=not reasons, confidence=confidence,
                             reasons=tuple(dict.fromkeys(reasons)), model_id=verdict.model_id,
                             request_hash=request.request_hash)


def select_candidate(context, candidates: Sequence, verdicts: Sequence, *, condition: Condition = "rubric",
                     min_confidence: float = 0.8, require_context: bool = True) -> SelectionDecision:
    """Hold incomplete/invalid judgments; select at most one complete candidate.

    Verdicts are positionally aligned with the fixed candidates. Ranking uses the
    minimum patch confidence, then the original candidate index. Pair-only
    semantics can be studied only by explicitly setting require_context=False.
    These are supplied model judgments, not proof of actual retrieval benefit.
    """
    if (isinstance(min_confidence, bool) or not isinstance(min_confidence, (int, float))
            or not math.isfinite(min_confidence) or not 0 <= min_confidence <= 1):
        raise ValueError("min_confidence must be finite and between zero and one")
    if type(require_context) is not bool or condition not in ("pair", "context", "rubric"):
        raise ValueError("invalid semantic selection configuration")
    if (not isinstance(candidates, (list, tuple)) or not isinstance(verdicts, (list, tuple))):
        raise ValueError("candidates and verdicts must be ordered sequences")
    c = Context.model_validate(_raw(context), strict=True)
    if len(verdicts) > len(candidates):
        decisions = tuple(CandidateDecision(candidate_index=i, eligible=False,
                                            reasons=("unexpected_verdict_count",)) for i in range(len(candidates)))
    else:
        decisions = tuple(_evaluate(i, c, p, verdicts[i] if i < len(verdicts) else None,
                                    condition, min_confidence, require_context)
                          for i, p in enumerate(candidates))
    eligible = [d for d in decisions if d.eligible]
    selected = min(eligible, key=lambda d: (-d.confidence, d.candidate_index)) if eligible else None
    reasons = ["selected_by_semantic_verdict" if selected else "all_candidates_held"]
    if condition == "pair" and not require_context:
        reasons.append("pair_only_weaker_semantics")
    return SelectionDecision(candidate_index=selected.candidate_index if selected else None,
                             reasons=tuple(reasons), candidate_decisions=decisions)
