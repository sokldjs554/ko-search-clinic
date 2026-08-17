"""질의 로그에서 **진료 대상을 뽑는다** — 평가셋을 손으로 만드는 대신.

## 이 모듈이 메우는 구멍

지금까지 진료 대상은 제가 손으로 고른 실패 질의 16건이었다. README에 한계로
적어 둔 그대로다 — *"실제 검색 로그의 제로결과 질의를 물리는 것이 다음
단계"*. 실서비스에서는 무엇을 고칠지를 사람이 고르지 않는다. **로그가
고른다.**

    수백만 줄 질의 로그
      → 제로결과 질의를 빈도순으로 집계
      → 영향(질의량)이 큰 것부터 진료 대상
      → 진료소가 진단·처방, 게이트가 검증

이 선정이 왜 중요하냐면, 검색 실패는 **롱테일**이기 때문이다. 제로결과 질의
종류는 수만 가지지만 트래픽의 대부분은 상위 수백 개가 만든다. 아무거나
고치면 사용자에게 닿지 않는다.

## 왜 Spark인가 — 그리고 왜 DuckDB도 두는가

집계 자체는 단순하다(GROUP BY + 정렬). 갈리는 것은 **데이터가 한 대에
들어가는가**이다.

- **Spark** — 로그가 여러 날·여러 파일에 흩어져 한 대 메모리를 넘을 때.
  파티션 프루닝과 분산 셔플이 이때 값을 한다.
- **DuckDB** — 한 대에 들어가는 규모. 프로세스 안에서 바로 돌아 훨씬 빠르고
  JVM이 필요 없다.

**규모가 아닌데 Spark를 쓰는 것은 비용만 낸다.** 그래서 둘 다 두고, 같은
결과를 내는지 테스트가 확인한다 — 엔진을 갈아탔는데 답이 달라지면 둘 중
하나는 틀린 것이다.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from searchclinic.scale.lake import LOG_DIR

ENGINES = ("duckdb", "spark")

# 이보다 적게 나온 질의는 후보에서 뺀다. 한 번 검색된 오타까지 진료하면
# 사전이 쓰레기로 찬다 — 사전 항목은 영구적이고 관리 비용이 붙는다.
MIN_VOLUME = 3


@dataclass(frozen=True)
class Candidate:
    """진료 후보 한 건."""

    query: str
    volume: int  # 이 질의가 검색된 횟수
    zero_results: int  # 그중 0건이었던 횟수
    clicks: int

    @property
    def zero_rate(self) -> float:
        return round(self.zero_results / self.volume, 4) if self.volume else 0.0

    @property
    def impact(self) -> int:
        """고쳤을 때 영향을 받는 검색 횟수 — 우선순위의 근거."""
        return self.zero_results


def _sql(min_volume: int, limit: int) -> str:
    """두 엔진이 **같은 SQL**을 돌게 한다 — 결과가 갈리면 비교가 무의미하다."""
    return f"""
        SELECT query,
               COUNT(*)                                  AS volume,
               SUM(CASE WHEN n_results = 0 THEN 1 ELSE 0 END) AS zero_results,
               SUM(CASE WHEN clicked THEN 1 ELSE 0 END)  AS clicks
        FROM logs
        GROUP BY query
        HAVING COUNT(*) >= {int(min_volume)}
           AND SUM(CASE WHEN n_results = 0 THEN 1 ELSE 0 END) > 0
        ORDER BY zero_results DESC, volume DESC, query ASC
        LIMIT {int(limit)}
    """


def mine_with_duckdb(root: Path | str, limit: int = 20, min_volume: int = MIN_VOLUME) -> list[Candidate]:
    try:
        import duckdb
    except ImportError as e:  # pragma: no cover - 선택 의존성
        raise RuntimeError('duckdb가 필요합니다:  pip install -e ".[scale]"') from e

    pattern = str(Path(root) / LOG_DIR / "**" / "*.parquet")
    con = duckdb.connect()
    con.execute(f"CREATE VIEW logs AS SELECT * FROM read_parquet('{pattern}')")
    rows = con.execute(_sql(min_volume, limit)).fetchall()
    con.close()
    return [Candidate(q, int(v), int(z), int(c)) for q, v, z, c in rows]


def mine_with_spark(root: Path | str, limit: int = 20, min_volume: int = MIN_VOLUME) -> list[Candidate]:
    try:
        from pyspark.sql import SparkSession
    except ImportError as e:  # pragma: no cover - 선택 의존성
        raise RuntimeError('pyspark가 필요합니다:  pip install -e ".[scale]"') from e

    spark = (
        SparkSession.builder.appName("ko-search-clinic-log-mining")
        .master("local[*]")
        # 규모 실험은 로컬 한 대에서 돈다. 파티션을 과하게 쪼개면 셔플
        # 오버헤드가 집계 자체보다 커진다.
        .config("spark.sql.shuffle.partitions", "8")
        .config("spark.ui.enabled", "false")
        .getOrCreate()
    )
    try:
        df = spark.read.parquet(str(Path(root) / LOG_DIR))
        df.createOrReplaceTempView("logs")
        rows = spark.sql(_sql(min_volume, limit)).collect()
        return [
            Candidate(r["query"], int(r["volume"]), int(r["zero_results"]), int(r["clicks"]))
            for r in rows
        ]
    finally:
        spark.stop()


def mine_candidates(
    root: Path | str,
    engine: str = "duckdb",
    limit: int = 20,
    min_volume: int = MIN_VOLUME,
) -> list[Candidate]:
    if engine not in ENGINES:
        raise ValueError(f"알 수 없는 엔진: {engine} (가능: {', '.join(ENGINES)})")
    if engine == "spark":
        return mine_with_spark(root, limit=limit, min_volume=min_volume)
    return mine_with_duckdb(root, limit=limit, min_volume=min_volume)


def render_candidates_markdown(candidates: list[Candidate], engine: str) -> str:
    lines = [
        f"### 로그에서 뽑은 진료 후보 — `{engine}`",
        "",
        f"- 후보 {len(candidates)}건 (제로결과가 1회 이상이고 질의량 {MIN_VOLUME}회 이상)",
        "",
        "| 순위 | 질의 | 질의량 | 제로결과 | 제로율 | 클릭 |",
        "|---|---|---|---|---|---|",
    ]
    for i, c in enumerate(candidates, 1):
        lines.append(
            f"| {i} | {c.query} | {c.volume} | **{c.zero_results}** | {c.zero_rate:.0%} | {c.clicks} |"
        )
    lines += [
        "",
        "제로결과 횟수 순으로 정렬한다 — **고쳤을 때 영향을 받는 검색 횟수**가 "
        "곧 우선순위이기 때문이다. 제로율이 높아도 아무도 안 치는 질의는 나중이다.",
    ]
    return "\n".join(lines)
