"""Evidence validation for generated explanations, independent of the provider.

A matching quote establishes source traceability, not semantic correctness.
The existing regression gate remains the authority for applying a candidate.
"""
from __future__ import annotations
import re
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, ValidationError
from searchclinic.patch.ir import Prescription
from searchclinic.analysis.config import AnalyzerConfig
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

def _display_text(text: str) -> tuple[str, list[int]]:
    """Map display-only whitespace collapse/bold removal back to original offsets.

    Words, punctuation, case and other markdown are never rewritten.
    """
    bold = set()
    for match in re.finditer(r"\*\*(.+?)\*\*", text, flags=re.DOTALL):
        bold.update((match.start(), match.start()+1, match.end()-2, match.end()-1))
    chars, offsets = [], []
    for i, c in enumerate(text):
        if i in bold:
            continue
        if c.isspace():
            if chars and chars[-1] != ' ':
                chars.append(' ')
                offsets.append(i)
        else:
            chars.append(c)
            offsets.append(i)
    if chars and chars[-1] == ' ':
        chars.pop()
        offsets.pop()
    return ''.join(chars), offsets

def source_quote(quote: str, body: str) -> tuple[str, bool]:
    if quote in body:
        return quote, False
    needle, _ = _display_text(quote)
    haystack, offsets = _display_text(body)
    start = haystack.find(needle) if len(needle) >= 8 else -1
    if start < 0:
        raise ValueError('citation_mismatch')
    # Return an actual substring of the provided body, never a paraphrase.
    return body[offsets[start]:offsets[start+len(needle)-1]+1], True

def validate_explanation(raw: dict, docs: list[KnowledgeDoc], query: str) -> dict:
    """Return a safe envelope; invalid output never contains executable changes."""
    failure = 'output_schema'
    recovered = False
    try:
        answer = Explanation.model_validate(raw)
        sources = {doc.doc_id: doc for doc in docs}
        failure = 'citation_source_or_text'
        for evidence in answer.evidence:
            if evidence.doc_id not in sources:
                raise ValueError('unknown_source')
            evidence.quote, changed = source_quote(evidence.quote, sources[evidence.doc_id].body)
            recovered = recovered or changed
        failure = 'status_or_support'
        if answer.status == 'abstain':
            if answer.patches:
                raise ValueError('abstention_with_patch')
            return {**answer.model_dump(), 'prescription': None, 'validation_error': None, 'citation_format_recovered': recovered}
        if not answer.evidence or answer.family == 'unknown':
            raise ValueError('missing_support')
        failure = 'invalid_patch'
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
        prescription = None
        if answer.patches:
            candidate = Prescription.model_validate(payload)
            candidate.apply_to(AnalyzerConfig())  # reject conflicting/duplicate patches before a gate
            prescription = candidate.model_dump()
        return {**answer.model_dump(), 'prescription': prescription, 'validation_error': None, 'citation_format_recovered': recovered}
    except (ValidationError, ValueError, TypeError):
        return {'status':'invalid', 'summary':'생성 결과의 형식 또는 원문 인용을 확인하지 못했습니다.',
                'family':'unknown','evidence':[], 'patches':[], 'prescription':None,
                'validation_error':failure, 'citation_format_recovered':False}
