"""Normalize actual returned hits; do not invent unmeasured signals."""
from time import perf_counter

from searchclinic.research.models import RetrievalObservation


def observe(engine, query: str, query_id: str, split: str) -> RetrievalObservation:
    start = perf_counter()
    hits = engine.search(query, k=10)
    tokens = set(engine.analyzer.tokens(query))
    matched = set()
    for hit in hits:
        matched.update(tokens & set(engine.doc_tokens(hit.doc_id)))
    first = hits[0].score if hits else None
    second = hits[1].score if len(hits) > 1 else None
    margin = ((first - second) / abs(first)
              if first not in (None, 0) and second is not None else None)
    return RetrievalObservation(query_id=query_id, query=query, split=split,
        result_count=len(hits), top1_score=first, top2_score=second,
        score_margin=margin, lexical_coverage=len(matched) / len(tokens) if tokens else None,
        latency_ms=(perf_counter() - start) * 1000)
