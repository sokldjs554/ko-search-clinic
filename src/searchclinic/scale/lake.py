"""데이터 레이크 — 코퍼스와 질의 로그를 Parquet으로.

## 왜 CSV가 아니라 Parquet인가

질의 로그는 "한 번 쓰고 여러 번 집계하는" 데이터다. 이런 데이터에 행 기반
포맷을 쓰면 집계할 때마다 안 쓰는 컬럼까지 전부 읽는다. 열 기반(Parquet)은
필요한 컬럼만 읽고, 같은 값이 반복되는 컬럼(`ts`, `query`)을 사전 인코딩으로
압축한다 — 검색 로그는 정확히 그런 모양이다.

## 왜 날짜로 파티션하는가

    logs/ts=2026-08-10/part-0.parquet
    logs/ts=2026-08-11/part-0.parquet

집계는 거의 항상 기간으로 자른다("최근 7일 제로결과 질의"). 디렉터리가
날짜로 갈려 있으면 엔진이 **읽을 파일 자체를 건너뛴다**(파티션 프루닝).
Spark든 DuckDB든 Hive 스타일의 이 규약을 그대로 이해한다.

## pyarrow만 쓴다

레이크를 만드는 데는 Spark가 필요 없다. 쓰는 쪽을 가볍게 두어야 테스트가
Spark 없이 돌고, 읽는 쪽(Spark / DuckDB)을 갈아끼울 수 있다.
"""

from __future__ import annotations

from collections import defaultdict
from pathlib import Path

from searchclinic.corpus.catalog import Document
from searchclinic.scale.generate import QueryLogRow

CATALOG_DIR = "catalog"
LOG_DIR = "logs"


def _require_pyarrow():
    try:
        import pyarrow as pa
        import pyarrow.parquet as pq
    except ImportError as e:  # pragma: no cover - 선택 의존성
        raise RuntimeError(
            "pyarrow가 필요합니다:  pip install -e \".[scale]\""
        ) from e
    return pa, pq


def write_catalog(docs: list[Document], root: Path | str) -> Path:
    """상품 카탈로그를 Parquet 한 벌로. 카탈로그는 기간 개념이 없어 파티션하지 않는다."""
    pa, pq = _require_pyarrow()
    out = Path(root) / CATALOG_DIR
    out.mkdir(parents=True, exist_ok=True)
    table = pa.table(
        {
            "doc_id": [d.doc_id for d in docs],
            "name": [d.name for d in docs],
            "description": [d.description for d in docs],
            "category": [d.category for d in docs],
        }
    )
    path = out / "part-0.parquet"
    pq.write_table(table, path, compression="snappy")
    return out


def write_query_log(rows: list[QueryLogRow], root: Path | str) -> Path:
    """질의 로그를 **날짜 파티션**으로 쓴다 (Hive 스타일 `ts=YYYY-MM-DD`)."""
    pa, pq = _require_pyarrow()
    out = Path(root) / LOG_DIR
    out.mkdir(parents=True, exist_ok=True)

    by_day: dict[str, list[QueryLogRow]] = defaultdict(list)
    for r in rows:
        by_day[r.ts].append(r)

    for day, day_rows in sorted(by_day.items()):
        part = out / f"ts={day}"
        part.mkdir(parents=True, exist_ok=True)
        table = pa.table(
            {
                "query": [r.query for r in day_rows],
                "n_results": [r.n_results for r in day_rows],
                "clicked": [r.clicked for r in day_rows],
            }
        )
        pq.write_table(table, part / "part-0.parquet", compression="snappy")
    return out


def read_catalog(root: Path | str) -> list[Document]:
    pa, pq = _require_pyarrow()
    table = pq.read_table(Path(root) / CATALOG_DIR)
    cols = table.to_pydict()
    return [
        Document(doc_id=i, name=n, description=d, category=c)
        for i, n, d, c in zip(
            cols["doc_id"], cols["name"], cols["description"], cols["category"]
        )
    ]


def lake_stats(root: Path | str) -> dict:
    """레이크의 크기와 파티션 수 — 규모 리포트에 싣는다."""
    root = Path(root)
    files = list(root.rglob("*.parquet"))
    partitions = sorted({p.parent.name for p in (root / LOG_DIR).rglob("*.parquet")})
    return {
        "files": len(files),
        "bytes": sum(f.stat().st_size for f in files),
        "log_partitions": partitions,
    }
