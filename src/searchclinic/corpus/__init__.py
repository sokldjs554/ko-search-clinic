"""코퍼스 계층 — 상품 카탈로그와 평가셋."""

from searchclinic.corpus.catalog import CATALOG, Document, load_catalog
from searchclinic.corpus.evalset import (
    FAILING,
    ZERO_RESULT_AT_BASELINE,
    FAMILIES,
    HEALTHY,
    EvalQuery,
    failing_queries,
    healthy_queries,
    load_evalset,
)

__all__ = [
    "Document",
    "CATALOG",
    "load_catalog",
    "EvalQuery",
    "FAMILIES",
    "HEALTHY",
    "FAILING",
    "ZERO_RESULT_AT_BASELINE",
    "load_evalset",
    "healthy_queries",
    "failing_queries",
]
