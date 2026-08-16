"""로컬 BM25 vs Elasticsearch nori 대조 검증.

이 모듈의 목적은 **"ES에서도 됩니다"를 보이는 것이 아니다.** Kiwi와 nori는
서로 다른 분석기이므로 결과는 어차피 완전히 같을 수 없다. 알고 싶은 것은
하나뿐이다:

    로컬 게이트를 통과해 채택된 패치가, ES nori 설정으로 옮겨졌을 때도
    같은 방향의 효과를 내는가? 아니라면 정확히 어느 질의에서, 왜 갈리는가?

그래서 산출물은 "일치/불일치" 도장이 아니라 **질의별 차이표와 그 원인이 되는
토큰화 차이**다. 불일치는 실패가 아니라 발견이며, 발견은 감추지 않는다.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from searchclinic.corpus.evalset import EvalQuery
from searchclinic.es.engine import ElasticsearchEngine
from searchclinic.evaluation.metrics import QueryMetrics, evaluate_all
from searchclinic.index.engine import SearchEngine

# 두 백엔드의 nDCG 차이가 이보다 크면 "갈렸다"고 본다. 랭킹 미세 차이(동점
# 처리·필드 길이 정규화)는 이 아래로 떨어지므로, 이 선을 넘는 것은 분석기가
# 실제로 다르게 동작했다는 뜻이다.
DIVERGENCE_EPS = 0.05


@dataclass
class QueryDivergence:
    query: str
    family: str
    local: QueryMetrics
    es: QueryMetrics
    kiwi_tokens: list[str]
    nori_tokens: list[str]

    @property
    def ndcg_delta(self) -> float:
        return round(self.es.ndcg - self.local.ndcg, 4)

    @property
    def diverged(self) -> bool:
        return abs(self.ndcg_delta) > DIVERGENCE_EPS

    @property
    def tokens_differ(self) -> bool:
        return self.kiwi_tokens != self.nori_tokens


@dataclass
class VerificationReport:
    rows: list[QueryDivergence] = field(default_factory=list)
    es_version: str = ""

    @property
    def diverged(self) -> list[QueryDivergence]:
        return [r for r in self.rows if r.diverged]

    @property
    def local_mean(self) -> float:
        return round(sum(r.local.ndcg for r in self.rows) / len(self.rows), 4) if self.rows else 0.0

    @property
    def es_mean(self) -> float:
        return round(sum(r.es.ndcg for r in self.rows) / len(self.rows), 4) if self.rows else 0.0


def verify(
    local: SearchEngine,
    es: ElasticsearchEngine,
    queries: list[EvalQuery],
    es_version: str = "",
) -> VerificationReport:
    """같은 평가셋을 두 백엔드에 돌리고 질의별로 대조한다.

    채점 함수는 양쪽 모두 `evaluate_all` 하나를 쓴다 — 자를 공유해야
    차이가 백엔드의 차이로만 남는다.
    """
    local_metrics = evaluate_all(local, queries)
    es_metrics = evaluate_all(es, queries)

    rows = [
        QueryDivergence(
            query=q.query,
            family=q.family,
            local=local_metrics[q.query],
            es=es_metrics[q.query],
            kiwi_tokens=local.analyzer.tokens(q.query),
            nori_tokens=es.analyze(q.query),
        )
        for q in queries
    ]
    return VerificationReport(rows=rows, es_version=es_version)


def render_verification_markdown(report: VerificationReport) -> str:
    out: list[str] = []
    out.append("### 로컬 BM25 vs Elasticsearch nori — 대조 검증")
    if report.es_version:
        out.append(f"\nElasticsearch {report.es_version} · analysis-nori\n")
    out.append(
        f"\n- 질의 {len(report.rows)}건 · 평균 nDCG: 로컬 **{report.local_mean}** / "
        f"ES **{report.es_mean}**"
    )
    out.append(
        f"- nDCG 차이가 {DIVERGENCE_EPS}를 넘는 질의: **{len(report.diverged)}건**"
    )
    out.append(
        f"- 토큰화가 다른 질의: **{sum(1 for r in report.rows if r.tokens_differ)}건** "
        "(Kiwi ≠ nori — 차이가 나는 것이 정상이며, 결과까지 갈리는지가 관건)"
    )
    out.append("\n| 질의 | 계열 | 로컬 nDCG | ES nDCG | 차이 | Kiwi 토큰 | nori 토큰 |")
    out.append("|---|---|---|---|---|---|---|")
    for r in sorted(report.rows, key=lambda r: -abs(r.ndcg_delta)):
        mark = " ⚠️" if r.diverged else ""
        out.append(
            f"| {r.query} | {r.family} | {r.local.ndcg:.2f} | {r.es.ndcg:.2f} | "
            f"{r.ndcg_delta:+.2f}{mark} | `{' '.join(r.kiwi_tokens) or '없음'}` | "
            f"`{' '.join(r.nori_tokens) or '없음'}` |"
        )

    if report.diverged:
        out.append("\n#### 갈린 질의")
        for r in report.diverged:
            out.append(
                f"\n**{r.query}** ({r.family}) — 로컬 {r.local.ndcg:.2f} → ES {r.es.ndcg:.2f}\n"
                f"- Kiwi: `{' '.join(r.kiwi_tokens) or '없음'}`\n"
                f"- nori: `{' '.join(r.nori_tokens) or '없음'}`\n"
                f"- 로컬 상위: {', '.join(r.local.hits_top) or '없음'}\n"
                f"- ES 상위: {', '.join(r.es.hits_top) or '없음'}"
            )
    else:
        out.append(
            "\n갈린 질의가 없다 — 채택된 패치가 nori 설정으로 옮겨진 뒤에도 "
            "같은 효과를 냈다는 뜻이다."
        )
    return "\n".join(out)
