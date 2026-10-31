"""Post-hoc development grounding; never rewrite the original model evidence.

A unique verbatim quote in the supplied document permits deterministic location
recovery. Semantic relations, confidence, quote text and document identity stay
unchanged. Ambiguous or absent quotes remain invalid. No labels are accepted.
"""
from collections import Counter
import copy
import hashlib
from pathlib import Path

from .pipeline import freeze
from .run_evidence import validate_run

VERSION = 'unique-verbatim-offset-v5.2-development'


def align_unique_quotes(documents, verdict):
    derived = copy.deepcopy(verdict)
    audit = []
    for assessment_index, assessment in enumerate(derived['assessments']):
        for citation_index, citation in enumerate(assessment['citations']):
            before = [citation['start'], citation['end']]
            text = documents.get(citation['doc_id'])
            quote = citation['quote']
            if text is None:
                status = 'unknown_document'
            elif 0 <= before[0] < before[1] <= len(text) and text[before[0]:before[1]] == quote:
                status = 'already_valid'
            else:
                matches, start = [], 0
                while quote:
                    position = text.find(quote, start)
                    if position < 0:
                        break
                    matches.append(position)
                    start = position + 1  # overlapping occurrences also count
                if len(matches) == 1:
                    citation['start'] = matches[0]
                    citation['end'] = matches[0] + len(quote)
                    status = 'unique_offset_recovered'
                else:
                    status = 'ambiguous_quote' if matches else 'quote_not_found'
            audit.append(dict(assessment_index=assessment_index, citation_index=citation_index,
                              status=status, before=before, after=[citation['start'], citation['end']]))
    return derived, audit


def derive_trials(bundle, verified_evidence):
    """Bind derived trials to a complete raw run; this is not a new LLM run."""
    source = validate_run(verified_evidence, bundle, require_complete=True)
    contexts = {record['context']['query_id']: record['context'] for record in bundle['body']['records']}
    trials, audit, counts = copy.deepcopy(source['trials']), [], Counter()
    for trial in trials:
        for query_id, verdicts in trial['verdicts'].items():
            documents = {d['doc_id']: d['text'] for d in contexts[query_id]['documents']}
            for index, verdict in enumerate(verdicts):
                if verdict is None:
                    continue
                verdicts[index], changes = align_unique_quotes(documents, verdict)
                counts.update(row['status'] for row in changes)
                audit.append(dict(condition=trial['condition'], repeat=trial['repeat'],
                                  query_id=query_id, candidate_index=index, citations=changes))
    return freeze(dict(version=VERSION, stage='posthoc_development_only_not_preregistered_primary',
        source_evidence_hash=verified_evidence['sha256'], source_plan_hash=source['plan']['sha256'],
        input_hash=bundle['sha256'], implementation_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        additional_provider_calls=0, trials=trials, audit=audit, citation_counts=dict(counts)))
