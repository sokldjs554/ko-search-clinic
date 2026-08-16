"""Elasticsearch 백엔드 검색 엔진 — 로컬 SearchEngine과 같은 인터페이스.

핵심 설계: `search(query, k) -> list[SearchHit]` 하나만 로컬 엔진과 똑같이
맞추면, 채점 코드(`evaluate_query`/`evaluate_all`)를 **한 줄도 바꾸지 않고**
그대로 재사용할 수 있다. 비교가 의미를 가지려면 두 백엔드가 같은 자로
재어져야 하고, 같은 자를 쓰는 가장 확실한 방법은 자를 공유하는 것이다.

로컬과 다른 점은 오직 토큰화와 색인이 어디서 일어나느냐뿐이다:

    로컬: Kiwi 형태소 분석 + 파이썬 후처리(동의어/분해) + 자체 BM25
    ES  : nori_tokenizer + nori_part_of_speech + synonym_graph + Lucene BM25

따라서 두 결과의 차이는 **분석기의 차이**로 좁혀진다. 그것이 이 검증에서
알고 싶은 것이다 — "로컬에서 통과한 패치가 진짜 ES에서도 같은 효과를 내는가".
"""

from __future__ import annotations

from searchclinic.analysis.config import AnalyzerConfig
from searchclinic.corpus.catalog import Document
from searchclinic.es.client import ESClient
from searchclinic.index.bm25 import SearchHit
from searchclinic.patch.es_render import to_es_settings

DEFAULT_INDEX = "ko-search-clinic"


class ElasticsearchEngine:
    """렌더된 nori 설정으로 만든 ES 인덱스를 로컬 엔진처럼 쓰게 감싼다."""

    def __init__(
        self,
        client: ESClient,
        docs: list[Document],
        config: AnalyzerConfig | None = None,
        index: str = DEFAULT_INDEX,
    ) -> None:
        self.client = client
        self.docs = {d.doc_id: d for d in docs}
        self.config = config or AnalyzerConfig()
        self.index = index

    # ------------------------------------------------------------ 색인

    def reindex(self) -> None:
        """설정을 렌더링해 인덱스를 새로 만들고 코퍼스를 전부 넣는다.

        로컬 엔진이 설정 변경 시 색인을 통째로 다시 만드는 것과 같은 절차다
        (ES에서 analyzer를 바꾸려면 reindex가 필요한 실제 제약과 일치).
        """
        settings = to_es_settings(self.config, index_name=self.index)
        self.client.delete_index(self.index)
        self.client.create_index(self.index, settings)
        self.client.bulk_index(
            self.index,
            [
                {
                    "doc_id": d.doc_id,
                    "name": d.name,
                    "description": d.description,
                    "category": d.category,
                }
                for d in self.docs.values()
            ],
        )

    # ------------------------------------------------------------ 검색

    def search(self, query: str, k: int = 10) -> list[SearchHit]:
        """로컬 SearchEngine.search와 같은 시그니처·반환형.

        matched_terms는 채우지 않는다 — 채점(nDCG/recall/precision@5)은
        doc_id 순서만 쓰므로, 없는 정보를 지어내느니 비워 두는 편이 정직하다.
        """
        return [
            SearchHit(doc_id=h["doc_id"], score=h["score"], matched_terms=[])
            for h in self.client.search(self.index, query, k=k)
        ]

    def with_config(self, config: AnalyzerConfig) -> "ElasticsearchEngine":
        return ElasticsearchEngine(self.client, list(self.docs.values()), config, self.index)

    # ------------------------------------------------------------ 진단

    def analyze(self, text: str) -> list[str]:
        """nori가 뽑아낸 토큰 — Kiwi 결과와 나란히 놓고 차이를 본다."""
        return [t["token"] for t in self.client.analyze(self.index, text)]
