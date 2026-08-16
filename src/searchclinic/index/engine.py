"""검색 엔진 — 분석기 설정 + 코퍼스 + BM25 색인을 하나로 묶는다.

설정(AnalyzerConfig)이 바뀌면 색인을 처음부터 다시 만든다. Elasticsearch에서
analyzer를 바꾸면 reindex해야 하는 것과 같은 제약을 일부러 유지한다 —
"패치 적용"의 비용과 의미가 실제 운영과 같아야 이 프로젝트의 검증이
실전으로 옮겨질 수 있다.

`with_config()`가 핵심이다: 원본을 건드리지 않고 패치가 적용된 새 엔진을
만들어 준다. 회귀 게이트는 이 샌드박스 엔진에서 전체 평가셋을 돌려보고,
통과할 때만 패치를 본 설정에 편입한다. 롤백 = 그냥 원본 엔진을 계속 쓰기.
"""

from __future__ import annotations

from searchclinic.analysis.analyzer import KoreanAnalyzer
from searchclinic.analysis.config import AnalyzerConfig
from searchclinic.corpus.catalog import Document
from searchclinic.index.bm25 import BM25Index, SearchHit


class SearchEngine:
    def __init__(
        self, docs: list[Document], config: AnalyzerConfig | None = None
    ) -> None:
        self.docs = {d.doc_id: d for d in docs}
        self.config = config or AnalyzerConfig()
        self.analyzer = KoreanAnalyzer(self.config)
        self._index = BM25Index()
        self._index.build(
            {d.doc_id: self.analyzer.tokens(d.text) for d in docs}
        )

    def search(self, query: str, k: int = 10) -> list[SearchHit]:
        return self._index.search(self.analyzer.tokens(query), k=k)

    def with_config(self, config: AnalyzerConfig) -> "SearchEngine":
        """같은 코퍼스에 다른 설정을 적용한 새 엔진 (샌드박스/채택 공용)."""
        return SearchEngine(list(self.docs.values()), config)

    # ------------------------------------------------------------ 진단 보조

    def vocabulary(self) -> list[str]:
        return self._index.vocabulary()

    def doc_tokens(self, doc_id: str) -> list[str]:
        doc = self.docs.get(doc_id)
        return self.analyzer.tokens(doc.text) if doc else []

    def grep_raw(self, needle: str, limit: int = 10) -> list[Document]:
        """분석기를 **우회**한 원문 부분 문자열 검색.

        "검색은 0건인데 원문에는 있다"가 분석 실패의 결정적 증거다.
        이 도구가 있어야 의사가 '없는 문서'와 '못 찾는 문서'를 구분한다.
        """
        needle_lower = needle.lower().replace(" ", "")
        out = []
        for doc in self.docs.values():
            haystack = doc.text.lower().replace(" ", "")
            if needle_lower and needle_lower in haystack:
                out.append(doc)
                if len(out) >= limit:
                    break
        return out
