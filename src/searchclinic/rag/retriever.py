"""지식 검색 — RAG의 R.

## 왜 새 검색 엔진을 만들지 않는가

이 저장소에는 이미 한국어 분석기와 BM25 색인이 있다. 지식 검색을 위해
또 하나를 만들면 두 벌이 되고, 두 벌은 갈라진다. 그래서 **상품 검색에 쓰는
그 엔진을 그대로** 쓴다.

여기에는 덤이 하나 있다. 지식 문서도 한국어이므로, 상품 검색을 괴롭히던
바로 그 형태소 문제가 지식 검색에도 그대로 나타난다 — 이 프로젝트가 다루는
문제를 이 프로젝트의 도구가 다시 겪는 셈이다.

## 두 신호를 모두 둔 이유

- **어휘 검색(BM25)** — 모델 없이 돌고, 용어가 정확히 겹칠 때 강하다.
- **의미 검색(임베딩)** — 표현이 달라도 잡지만, 캐시나 모델이 필요하다.

벡터 실측에서 확인했듯 임베딩은 **짧은 토큰**에서 무너진다. 그런데 지식
문서는 문장 단위라 그 약점이 덜하다. 같은 신호가 층에 따라 다르게 작동하는지
직접 재보려고 둘 다 두고, 어느 쪽이 나은지는 오프라인 채점으로 정했다
(`clinic rag-eval`).

## 기본값을 실측으로 정했다 — 그리고 한 번 뒤집혔다

적중률(관련 문서가 상위 k 안에 하나라도 들어오는 비율):

    k      1     3     5     8
    bm25   12%   88%   88%   88%
    dense  56%   62%   88%  100%
    hybrid  0%   75%   88%   88%

**어느 쪽도 지배하지 않는다.** 의미 검색은 **1위를 맞히는 데** 강하고
(56% vs 12%), 어휘 검색은 **좁은 상위 목록을 채우는 데** 강하다(k=3에서
88% vs 62%). 기본 top-k가 3이므로 기본값은 `bm25`다.

이 표는 한 번 뒤집혔다. 지식 문서가 전부 200자 안팎이던 때는 dense가 모든
k에서 이겼는데, 실무 문서 길이의 긴 문서를 넣자 BM25가 따라잡았다. 긴 문서는
용어가 더 많이 겹쳐 어휘 검색에 유리하기 때문이다. **코퍼스의 성질이 바뀌면
신호의 우열도 바뀐다** — 회귀 테스트가 이 뒤집힘을 잡아냈다.

하이브리드가 k=1에서 0%로 둘보다 나쁜 것도 기록해 둔다. RRF는 두 순위를
대등하게 섞으므로, 한쪽 신호가 확연히 약하면 그 약한 순위가 1위 자리를
빼앗는다. **"합치면 낫다"가 늘 참은 아니다.**

### 이 표를 아직 믿으면 안 되는 이유

커밋된 벡터 캐시가 지식베이스 어휘의 **6%만** 안다(캐시를 상품 어휘로 만들었기
때문). 그러니 dense 수치는 임베딩의 실력이 아니라 **캐시의 결손**을 함께 잰
값이다. `clinic build-vectors`로 캐시를 다시 만들면 달라지고, 리포트가 이
커버리지를 함께 내도록 해 두었다.

순위 융합은 RRF(Reciprocal Rank Fusion)를 쓴다 — 두 신호의 점수 척도가
서로 달라(BM25는 무계, 코사인은 [-1,1]) 그대로 더할 수 없고, 순위만 쓰면
척도를 맞출 필요가 없기 때문이다.
"""

from __future__ import annotations

from dataclasses import dataclass

from searchclinic.analysis.vectors import CachedVectors
from searchclinic.corpus.catalog import Document
from searchclinic.index.engine import SearchEngine
from searchclinic.rag.chunker import DEFAULT_MAX_CHARS, DEFAULT_OVERLAP, chunk_knowledge
from searchclinic.rag.knowledge import KnowledgeDoc, load_knowledge

# RRF 상수. 표준값 60을 쓴다 — 상위 순위의 영향력을 과하지 않게 누른다.
RRF_K = 60

DEFAULT_TOP_K = 3

MODES = ("bm25", "dense", "hybrid")

# 실측으로 정한 기본값 — 기본 top-k(3)에서 bm25가 이긴다 (위 표).
# 모델도 캐시도 필요 없다는 것이 덤이다.
DEFAULT_MODE = "bm25"


@dataclass(frozen=True)
class Retrieved:
    doc: KnowledgeDoc
    score: float
    rank_bm25: int | None = None
    rank_dense: int | None = None


def _as_documents(docs: list[KnowledgeDoc]) -> list[Document]:
    """지식 문서를 상품 색인이 쓰는 형태로 옮긴다 — 같은 엔진을 쓰기 위해."""
    return [
        Document(doc_id=d.doc_id, name=d.title, description=d.body, category="knowledge")
        for d in docs
    ]


def _as_chunk_documents(docs: list[KnowledgeDoc], max_chars: int, overlap: int):
    """청킹한 조각들을 색인 단위로 쓴다.

    조각의 `doc_id`는 원문 문서 id를 유지한다(`K001#0`). 채점과 근거 표시는
    문서 단위로 하므로 조각이 어디서 왔는지를 잃으면 안 된다.
    """
    chunks = chunk_knowledge(docs, max_chars=max_chars, overlap=overlap)
    return chunks, [
        Document(
            doc_id=c.chunk_id, name=c.heading, description=c.text, category="knowledge"
        )
        for c in chunks
    ]


class KnowledgeRetriever:
    """지식베이스에서 질의에 맞는 문서를 고른다."""

    def __init__(
        self,
        docs: list[KnowledgeDoc] | None = None,
        vectors: CachedVectors | None = None,
        mode: str = DEFAULT_MODE,
        chunked: bool = False,
        max_chars: int = DEFAULT_MAX_CHARS,
        overlap: int = DEFAULT_OVERLAP,
    ) -> None:
        if mode not in MODES:
            raise ValueError(f"알 수 없는 검색 방식: {mode} (가능: {', '.join(MODES)})")
        self.docs = docs if docs is not None else load_knowledge()
        self.chunked = chunked
        self.max_chars = max_chars
        self.overlap = overlap
        self.requested_mode = mode
        self.vectors = vectors

        # 벡터 캐시가 없으면 dense·hybrid는 조용히 빈 결과를 내게 된다. 그러면
        # "RAG를 켜고 돌린 결과"라는 기록이 거짓이 된다 — 실제로 무엇으로
        # 돌았는지를 `mode`에 남겨, 리포트가 사실을 말하게 한다.
        self.mode = mode if (vectors is not None or mode == "bm25") else "bm25"
        self.degraded = self.mode != self.requested_mode

        self._by_id = {d.doc_id: d for d in self.docs}
        if chunked:
            self.chunks, indexed = _as_chunk_documents(self.docs, max_chars, overlap)
            # 조각 id → 원문 문서. 검색 단위는 조각이지만 결과는 문서로 돌려준다.
            self._owner = {c.chunk_id: self._by_id[c.doc_id] for c in self.chunks}
            self._chunk_text = {c.chunk_id: c.display for c in self.chunks}
        else:
            self.chunks = []
            indexed = _as_documents(self.docs)
            self._owner = dict(self._by_id)
            self._chunk_text = {}
        self._engine = SearchEngine(indexed)

    def vector_coverage(self) -> float:
        """지식베이스 어휘 중 벡터 캐시가 아는 비율.

        이 값이 낮으면 dense 성적은 **신호의 실력이 아니라 캐시의 결손**을
        잰 것이다. 낮은 채로 "임베딩이 이만큼 한다"고 적으면 거짓말이 되므로,
        리포트가 이 값을 함께 내도록 한다.
        """
        if self.vectors is None:
            return 0.0
        texts = [c.display for c in self.chunks] if self.chunked else [d.text for d in self.docs]
        tokens = {t for text in texts for t in self._engine.analyzer.tokens(text)}
        if not tokens:
            return 0.0
        return round(sum(1 for t in tokens if t in self.vectors) / len(tokens), 4)

    # ------------------------------------------------------------- 신호

    def _index_size(self) -> int:
        return len(self.chunks) if self.chunked else len(self.docs)

    def _fold(self, unit_ids: list[str]) -> list[str]:
        """검색 단위(조각) 순위를 **문서** 순위로 접는다.

        같은 문서의 조각이 여러 개 걸리면 가장 높은 순위 하나만 남긴다.
        접지 않으면 상위 k가 한 문서의 조각들로 채워져, 청킹이 오히려
        다양성을 죽인다.
        """
        seen: list[str] = []
        for unit_id in unit_ids:
            owner = self._owner.get(unit_id)
            if owner is None:
                continue
            if owner.doc_id not in seen:
                seen.append(owner.doc_id)
        return seen

    def _bm25_ranking(self, query: str) -> list[str]:
        hits = self._engine.search(query, k=self._index_size())
        return self._fold([h.doc_id for h in hits])

    def _dense_ranking(self, query: str) -> list[str]:
        """질의 토큰과 문서 토큰의 최대 유사도 평균으로 문서를 정렬한다.

        캐시는 **토큰 단위**라 문장 벡터가 없다. 그래서 질의의 각 토큰이
        문서에서 가장 가까운 토큰과 얼마나 닮았는지를 모아 문서 점수로
        삼는다(MaxSim). 문장 임베딩보다 거칠지만, 캐시만으로 모델 없이
        재현된다는 이 저장소의 규칙을 지킬 수 있다.
        """
        if self.vectors is None:
            return []
        q_tokens = [t for t in self._engine.analyzer.tokens(query) if t in self.vectors]
        if not q_tokens:
            return []

        units = (
            [(c.chunk_id, c.display) for c in self.chunks]
            if self.chunked
            else [(d.doc_id, d.text) for d in self.docs]
        )
        scored: list[tuple[str, float]] = []
        for unit_id, unit_text in units:
            d_tokens = [t for t in self._engine.analyzer.tokens(unit_text) if t in self.vectors]
            if not d_tokens:
                continue
            total = 0.0
            for qt in q_tokens:
                sims = [s for dt in d_tokens if (s := self.vectors.similarity(qt, dt)) is not None]
                total += max(sims) if sims else 0.0
            scored.append((unit_id, total / len(q_tokens)))

        scored.sort(key=lambda x: (-x[1], x[0]))
        return self._fold([unit_id for unit_id, _ in scored])

    # ------------------------------------------------------------- 검색

    def retrieve(self, query: str, k: int = DEFAULT_TOP_K) -> list[Retrieved]:
        """문서가 있는 한 **빈 목록을 돌려주지 않는다.**

        의미 순위는 질의 토큰이 캐시에 하나도 없으면 비게 되는데(캐시는 유한한
        어휘로 만들어진다), 그때 빈 목록을 돌려주면 진료는 근거 없이 진행되면서
        기록에는 "RAG로 돌았다"고 남는다. 그런 침묵이 측정을 거짓말로 만든다.
        의미 순위가 비면 어휘 순위로 채운다 — 근거 없는 것보다 낫다.
        """
        k = max(1, int(k))
        bm25 = self._bm25_ranking(query)
        dense = self._dense_ranking(query) if self.mode in ("dense", "hybrid") else []

        def from_bm25() -> list[Retrieved]:
            return [
                Retrieved(self._by_id[d], 1.0 / (RRF_K + i + 1), rank_bm25=i + 1)
                for i, d in enumerate(bm25[:k])
            ]

        if self.mode == "bm25" or not dense:
            return from_bm25()
        if self.mode == "dense":
            return [
                Retrieved(self._by_id[d], 1.0 / (RRF_K + i + 1), rank_dense=i + 1)
                for i, d in enumerate(dense[:k])
            ]

        # 하이브리드 — RRF로 두 순위를 융합한다.
        rank_b = {d: i + 1 for i, d in enumerate(bm25)}
        rank_d = {d: i + 1 for i, d in enumerate(dense)}
        fused: list[tuple[str, float]] = []
        for doc_id in self._by_id:
            score = 0.0
            if doc_id in rank_b:
                score += 1.0 / (RRF_K + rank_b[doc_id])
            if doc_id in rank_d:
                score += 1.0 / (RRF_K + rank_d[doc_id])
            if score:
                fused.append((doc_id, score))
        fused.sort(key=lambda x: (-x[1], x[0]))

        return [
            Retrieved(self._by_id[d], s, rank_bm25=rank_b.get(d), rank_dense=rank_d.get(d))
            for d, s in fused[:k]
        ]


def render_context(hits: list[Retrieved]) -> str:
    """검색된 문서를 프롬프트에 넣을 형태로.

    출처를 함께 싣는다. 근거 없는 문장을 근거처럼 읽게 만들면 RAG는
    할루시네이션의 도구가 된다 — 어디서 온 말인지 보여야 사람이 검증할 수 있다.
    """
    if not hits:
        return ""
    blocks = [
        f"[{h.doc.doc_id}] {h.doc.title}\n{h.doc.body}\n(출처: {h.doc.source})" for h in hits
    ]
    return "\n\n".join(blocks)
