"""Elasticsearch 검증 계층 — 렌더된 nori 설정이 실제로 동작하는지 확인한다.

렌더러(`patch/es_render.py`)는 "이 패치는 nori 설정으로 이렇게 대응된다"고
주장한다. 이 패키지는 그 주장을 실제 ES 클러스터에 물려 검증한다.
"""

from searchclinic.es.client import ESClient, ESError
from searchclinic.es.engine import DEFAULT_INDEX, ElasticsearchEngine
from searchclinic.es.verify import (
    DIVERGENCE_EPS,
    QueryDivergence,
    VerificationReport,
    render_verification_markdown,
    verify,
)

__all__ = [
    "DEFAULT_INDEX",
    "DIVERGENCE_EPS",
    "ESClient",
    "ESError",
    "ElasticsearchEngine",
    "QueryDivergence",
    "VerificationReport",
    "render_verification_markdown",
    "verify",
]
