"""검색 품질 지표 — recall@k, nDCG@k, 제로결과율.

nDCG는 표준 정의를 그대로 쓴다:
    DCG@k  = Σ (2^grade - 1) / log2(rank + 1)
    nDCG@k = DCG@k / IDCG@k   (IDCG = 정답을 이상적으로 배열했을 때)
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from searchclinic.corpus.evalset import EvalQuery
from searchclinic.index.engine import SearchEngine

DEFAULT_K = 10


@dataclass(frozen=True)
class QueryMetrics:
    query: str
    ndcg: float
    recall: float
    precision5: float  # 상위 5건 중 정답 비율 — nDCG가 못 잡는 '쓰레기 유입'을 잡는다
    n_results: int
    hits_top: tuple[str, ...]  # 상위 결과 doc_id (진단·리포트용)

    @property
    def zero_result(self) -> bool:
        return self.n_results == 0


def _dcg(grades: list[int], k: int) -> float:
    return sum(
        (2**g - 1) / math.log2(rank + 2) for rank, g in enumerate(grades[:k])
    )


def evaluate_query(
    engine: SearchEngine, eq: EvalQuery, k: int = DEFAULT_K
) -> QueryMetrics:
    hits = engine.search(eq.query, k=k)
    got = [h.doc_id for h in hits]
    grades = [eq.qrels.get(d, 0) for d in got]

    ideal = sorted(eq.qrels.values(), reverse=True)
    idcg = _dcg(ideal, k)
    ndcg = _dcg(grades, k) / idcg if idcg > 0 else 0.0

    relevant = set(eq.qrels)
    recall = len(relevant & set(got)) / len(relevant) if relevant else 0.0

    top5 = got[:5]
    precision5 = (
        sum(1 for d in top5 if d in relevant) / len(top5) if top5 else 0.0
    )

    return QueryMetrics(
        query=eq.query,
        ndcg=round(ndcg, 4),
        recall=round(recall, 4),
        precision5=round(precision5, 4),
        n_results=len(got),
        hits_top=tuple(got[:5]),
    )


def evaluate_all(
    engine: SearchEngine, queries: list[EvalQuery], k: int = DEFAULT_K
) -> dict[str, QueryMetrics]:
    return {eq.query: evaluate_query(engine, eq, k) for eq in queries}


def mean_ndcg(metrics: dict[str, QueryMetrics]) -> float:
    if not metrics:
        return 0.0
    return round(sum(m.ndcg for m in metrics.values()) / len(metrics), 4)


def zero_result_rate(metrics: dict[str, QueryMetrics]) -> float:
    if not metrics:
        return 0.0
    return round(
        sum(1 for m in metrics.values() if m.zero_result) / len(metrics), 4
    )
