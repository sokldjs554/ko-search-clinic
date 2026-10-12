"""Typed actions and literal source-span evidence. No arbitrary config edits."""
from dataclasses import dataclass, field
from enum import Enum

from searchclinic.patch.ir import Prescription
from searchclinic.research.costs import CostRecord
from searchclinic.research.models import EvidenceSpan


class ActionKind(str, Enum):
    NO_OP = "no_op"
    TYPED_PATCH = "typed_patch"
    REWRITE_QUERY = "rewrite_query"
    SWITCH_OR_FUSE_RETRIEVER = "switch_or_fuse_retriever"
    RERANK = "rerank"
    ABSTAIN = "abstain"


@dataclass(frozen=True)
class Candidate:
    action: ActionKind
    prescription: Prescription | None = None
    evidence: tuple[EvidenceSpan, ...] = ()
    cost: CostRecord = field(default_factory=CostRecord)


def prescription_terms(rx):
    terms = {w.form for w in rx.user_words}
    terms.update(t for g in rx.synonym_groups for t in g.terms)
    terms.update(c.word for c in rx.compound_expansions)
    terms.update(p for c in rx.compound_expansions for p in c.parts)
    return sorted(terms)


def evidence_for(engine, prescription):
    evidence = []
    sources = [("query", prescription.target_query, prescription.target_query)]
    sources.extend(("document", d.doc_id, d.text) for d in engine.docs.values())
    for term in prescription_terms(prescription):
        for kind, source_id, text in sources:
            start = text.casefold().find(term.casefold())
            if start >= 0:
                evidence.append(EvidenceSpan(source_type=kind, source_id=source_id,
                    start=start, end=start + len(term), text=text[start:start + len(term)]))
                break
        else:
            return ()
    return tuple(evidence)
