"""Evidence validation for generated explanations, independent of the provider.

A matching quote establishes source traceability, not semantic correctness.
The existing regression gate remains the authority for applying a candidate.
"""
from __future__ import annotations
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, ValidationError
from searchclinic.patch.ir import Prescription
from searchclinic.rag.knowledge import KnowledgeDoc

class StrictModel(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)

class Evidence(StrictModel):
    doc_id: str = Field(min_length=1, max_length=32)
    quote: str = Field(min_length=8, max_length=500)

class Patch(StrictModel):
    kind: Literal['synonym', 'user_word', 'compound']
    terms: list[str] = Field(min_length=1, max_length=6)

class Explanation(StrictModel):
    status: Literal['supported', 'abstain']
    summary: str = Field(min_length=10, max_length=1200)
    family: Literal['spelling_variant', 'cross_script', 'synonym_gap',
                    'compound_locked', 'garbage_split', 'unknown']
    evidence: list[Evidence] = Field(max_length=4)
    patches: list[Patch] = Field(max_length=4)

def validate_explanation(raw: dict, docs: list[KnowledgeDoc], query: str) -> dict:
    """Return a safe envelope; invalid output never contains executable changes."""
    try:
        answer = Explanation.model_validate(raw)
        sources = {doc.doc_id: doc for doc in docs}
        for evidence in answer.evidence:
            if evidence.doc_id not in sources or evidence.quote not in sources[evidence.doc_id].body:
                raise ValueError('citation_mismatch')
        if answer.status == 'abstain':
            if answer.patches:
                raise ValueError('abstention_with_patch')
            return {**answer.model_dump(), 'prescription': None, 'validation_error': None}
        if not answer.evidence or answer.family == 'unknown':
            raise ValueError('missing_support')
        payload = dict(target_query=query, diagnosis_family=answer.family,
                       reasoning=answer.summary, user_words=[], synonym_groups=[], compound_expansions=[])
        for patch in answer.patches:
            if patch.kind == 'synonym':
                payload['synonym_groups'].append({'terms': patch.terms})
            elif patch.kind == 'user_word':
                if len(patch.terms) != 1:
                    raise ValueError('user_word_arity')
                payload['user_words'].append({'form': patch.terms[0]})
            else:
                payload['compound_expansions'].append({'word': patch.terms[0], 'parts': patch.terms[1:]})
        prescription = Prescription.model_validate(payload).model_dump() if answer.patches else None
        return {**answer.model_dump(), 'prescription': prescription, 'validation_error': None}
    except (ValidationError, ValueError, TypeError):
        return {'status':'invalid', 'summary':'생성 결과의 형식 또는 원문 인용을 확인하지 못했습니다.',
                'family':'unknown','evidence':[], 'patches':[], 'prescription':None,
                'validation_error':'invalid_schema_or_evidence'}
