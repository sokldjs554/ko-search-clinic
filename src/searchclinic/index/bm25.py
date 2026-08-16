"""BM25 역색인 — 외부 의존성 없는 결정적 구현.

Elasticsearch의 기본 랭킹 함수(BM25, k1=1.2, b=0.75)를 그대로 구현한다.
같은 토큰 목록을 넣으면 항상 같은 순위가 나온다 — 패치 전후 비교가
평가의 핵심이므로 랭킹의 결정성이 곧 채점의 결정성이다.

IDF는 Lucene 방식: log(1 + (N - df + 0.5) / (df + 0.5))
"""

from __future__ import annotations

import math
from collections import Counter
from dataclasses import dataclass, field

K1 = 1.2
B = 0.75


@dataclass
class SearchHit:
    doc_id: str
    score: float
    matched_terms: list[str] = field(default_factory=list)


class BM25Index:
    """토큰화된 문서들의 역색인."""

    def __init__(self) -> None:
        self._postings: dict[str, dict[str, int]] = {}  # term -> {doc_id: tf}
        self._doc_len: dict[str, int] = {}
        self._avg_len: float = 0.0

    def build(self, docs: dict[str, list[str]]) -> None:
        """{doc_id: 토큰 목록}으로 색인을 만든다."""
        self._postings.clear()
        self._doc_len.clear()
        for doc_id, tokens in docs.items():
            self._doc_len[doc_id] = len(tokens)
            for term, tf in Counter(tokens).items():
                self._postings.setdefault(term, {})[doc_id] = tf
        n = len(self._doc_len)
        self._avg_len = (sum(self._doc_len.values()) / n) if n else 0.0

    @property
    def n_docs(self) -> int:
        return len(self._doc_len)

    def vocabulary(self) -> list[str]:
        """색인에 존재하는 모든 토큰 (표기 변형 탐색용)."""
        return sorted(self._postings)

    def df(self, term: str) -> int:
        return len(self._postings.get(term, {}))

    def _idf(self, term: str) -> float:
        df = self.df(term)
        return math.log(1.0 + (self.n_docs - df + 0.5) / (df + 0.5))

    def search(self, query_tokens: list[str], k: int = 10) -> list[SearchHit]:
        """BM25 점수 상위 k건. 동점은 doc_id 사전순 (결정적)."""
        scores: dict[str, float] = {}
        matched: dict[str, set[str]] = {}
        # 질의 내 중복 토큰은 한 번만 (표준 BM25 질의 처리)
        for term in dict.fromkeys(query_tokens):
            postings = self._postings.get(term)
            if not postings:
                continue
            idf = self._idf(term)
            for doc_id, tf in postings.items():
                denom = tf + K1 * (1 - B + B * self._doc_len[doc_id] / self._avg_len)
                scores[doc_id] = scores.get(doc_id, 0.0) + idf * (tf * (K1 + 1)) / denom
                matched.setdefault(doc_id, set()).add(term)
        ranked = sorted(scores.items(), key=lambda kv: (-kv[1], kv[0]))[:k]
        return [
            SearchHit(doc_id=d, score=round(s, 4), matched_terms=sorted(matched[d]))
            for d, s in ranked
        ]
