"""검색 품질을 **생성 없이** 채점한다 — RAG의 R만 따로.

RAG가 안 되는 이유는 둘 중 하나다: 못 찾았거나(R), 찾았는데 못 썼거나(G).
둘을 섞어 재면 어느 쪽이 문제인지 알 수 없고, 그러면 무엇을 고쳐야 하는지도
모른다. 그래서 검색만 따로 채점한다 — **API 키 없이, 모델 없이** 돈다.

## 정답 라벨을 어떻게 정하는가

각 지식 문서에 "이 문서가 근거가 되는 실패 계열"을 달아 뒀다. 실패 질의는
이미 계열이 라벨링돼 있으므로, **질의의 계열을 담은 문서가 검색되면 맞다**로
채점한다. 질의별로 정답 문서를 손으로 지정하지 않은 이유는, 그렇게 하면
지식베이스가 정답표가 되기 때문이다.

### 모든 계열에 걸린 문서는 정답에서 뺀다

처음 이렇게 재자 적중률 100%, MRR 1.000이 나왔다. 좋아 보였지만 **거짓이었다.**
K012("진단의 결정적 증거")는 다섯 계열 전부에 라벨돼 있어 어떤 질의에도
"관련 문서"가 되고, 일반 어휘가 많아 BM25 상위에 늘 오른다. 그것 하나로
모든 질의가 적중 처리됐다.

**모든 계열에 관련된 문서는 어느 계열을 찾았는지에 대해 아무 정보도 주지
않는다.** 그래서 채점에서 제외한다 — 이 문서가 쓸모없다는 뜻이 아니라,
검색이 **계열에 맞는 지식**을 찾았는지 재는 데는 쓸 수 없다는 뜻이다.

## 검색 질의를 무엇으로 삼는가

실패 질의 원문만 던지면 검색이 될 리가 없다 — `아답터`라는 단어는 지식
문서에 없다. 실제 시스템이 그러듯 **증상**으로 검색한다: 결과가 몇 건인지,
어떤 토큰으로 쪼개졌는지, 어떤 토큰이 어떤 품사로 버려졌는지, 원문 grep에는
있는지. 이것들은 전부 의사가 도구로 관측할 수 있는 값이고, 정답을 포함하지
않는다.
"""

from __future__ import annotations

from dataclasses import dataclass

from searchclinic.corpus.evalset import EvalQuery
from searchclinic.index.engine import SearchEngine
from searchclinic.rag.retriever import DEFAULT_TOP_K, KnowledgeRetriever


def build_retrieval_query(query: str, engine: SearchEngine) -> str:
    """관측 가능한 증상만으로 검색 질의를 만든다.

    정답(어느 계열인지, 어떤 처방인지)은 넣지 않는다. 넣으면 검색이 잘 되는
    것이 아니라 답을 흘린 것이 된다.
    """
    analyzer = engine.analyzer
    tokens = analyzer.tokens(query)
    dropped = analyzer.dropped(query)
    n_results = len(engine.search(query, k=10))
    in_raw = len(engine.grep_raw(query.replace(" ", "")))

    parts = [query, f"검색 결과 {n_results}건"]
    if n_results == 0:
        parts.append("결과 없음 0건")
    if tokens:
        parts.append("분석 토큰 " + " ".join(tokens))
    if len(tokens) > 1 and all(len(t) == 1 for t in tokens):
        parts.append("한 음절씩 쪼개짐 분해")
    if dropped:
        parts.append("버려진 토큰 " + " ".join(f"{t} {tag}" for t, tag in dropped))
        parts.append("품사 오인 내용어 필터 제거")
    if in_raw:
        parts.append("원문에는 존재 grep 매칭됨 분석 실패")
    return " ".join(parts)


@dataclass
class RetrievalScore:
    query: str
    family: str
    retrieved: list[str]
    relevant: list[str]

    @property
    def hits(self) -> list[str]:
        return [d for d in self.retrieved if d in self.relevant]

    @property
    def recall(self) -> float:
        return len(self.hits) / len(self.relevant) if self.relevant else 0.0

    @property
    def precision(self) -> float:
        return len(self.hits) / len(self.retrieved) if self.retrieved else 0.0

    @property
    def hit(self) -> bool:
        """상위 k 안에 관련 문서가 하나라도 있는가 — 생성이 쓸 근거가 있느냐."""
        return bool(self.hits)

    @property
    def reciprocal_rank(self) -> float:
        for i, d in enumerate(self.retrieved, start=1):
            if d in self.relevant:
                return 1.0 / i
        return 0.0


@dataclass
class RetrievalReport:
    mode: str
    k: int
    rows: list[RetrievalScore]
    # 의미 검색이 지식베이스 어휘를 얼마나 아는가. 낮으면 dense 성적은
    # 신호의 실력이 아니라 캐시의 결손을 잰 것이다.
    vector_coverage: float = 1.0
    degraded: bool = False

    def _mean(self, attr: str) -> float:
        if not self.rows:
            return 0.0
        return round(sum(getattr(r, attr) for r in self.rows) / len(self.rows), 4)

    @property
    def hit_rate(self) -> float:
        return self._mean("hit")

    @property
    def recall(self) -> float:
        return self._mean("recall")

    @property
    def precision(self) -> float:
        return self._mean("precision")

    @property
    def mrr(self) -> float:
        return self._mean("reciprocal_rank")

    def markdown(self) -> str:
        lines = [
            f"### 지식 검색 품질 — `{self.mode}` (top-{self.k})",
            "",
            f"- 적중률(관련 문서 1건 이상): **{self.hit_rate:.0%}**",
            f"- recall@{self.k}: {self.recall:.3f} · precision@{self.k}: {self.precision:.3f} · MRR: {self.mrr:.3f}",
        ]
        if self.degraded:
            lines.append(
                "- ⚠️ **벡터 캐시가 없어 어휘 검색으로 내려갔다** — 이 수치는 dense가 아니다."
            )
        elif self.mode != "bm25" and self.vector_coverage < 0.5:
            lines.append(
                f"- ⚠️ **벡터 캐시가 지식베이스 어휘의 {self.vector_coverage:.0%}만 안다.** "
                "이 수치는 임베딩의 실력이 아니라 캐시의 결손을 반영한다 — "
                "`clinic build-vectors`로 캐시를 다시 만들면 달라진다."
            )
        lines += [
            "",
            "| 질의 | 계열 | 검색된 문서 | 관련 |",
            "|---|---|---|---|",
        ]
        for r in self.rows:
            mark = "✅" if r.hit else "❌"
            got = " ".join(f"**{d}**" if d in r.relevant else d for d in r.retrieved)
            lines.append(f"| {mark} {r.query} | {r.family} | {got} | {len(r.hits)}/{len(r.relevant)} |")
        return "\n".join(lines)


def discriminative_docs(retriever: KnowledgeRetriever) -> list:
    """어느 계열을 찾았는지 **가려낼 수 있는** 문서만.

    모든 계열에 걸린 문서는 어떤 질의에도 정답이 되므로, 그것으로 잰 적중률은
    검색이 잘 됐다는 뜻이 아니다 (실측으로 겪은 함정 — 위 모듈 설명 참조).
    """
    all_families = {f for d in retriever.docs for f in d.families}
    return [d for d in retriever.docs if d.families and set(d.families) != all_families]


def evaluate_retrieval(
    retriever: KnowledgeRetriever,
    queries: list[EvalQuery],
    engine: SearchEngine,
    k: int = DEFAULT_TOP_K,
) -> RetrievalReport:
    scorable = discriminative_docs(retriever)
    rows: list[RetrievalScore] = []
    for eq in queries:
        relevant = [d.doc_id for d in scorable if eq.family in d.families]
        if not relevant:
            continue  # 이 계열을 다루는 문서가 없으면 채점할 것이 없다
        retrieval_query = build_retrieval_query(eq.query, engine)
        got = [h.doc.doc_id for h in retriever.retrieve(retrieval_query, k=k)]
        rows.append(
            RetrievalScore(query=eq.query, family=eq.family, retrieved=got, relevant=relevant)
        )
    return RetrievalReport(
        mode=retriever.mode,
        k=k,
        rows=rows,
        vector_coverage=retriever.vector_coverage(),
        degraded=retriever.degraded,
    )
