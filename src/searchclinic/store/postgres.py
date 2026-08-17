"""PostgreSQL 저장소 — 진료 세션이 프로세스보다 오래 살게 한다.

## 무엇을 고치는 것인가

README 한계에 이렇게 적어 뒀다:

    세션 저장소가 메모리 — REST/MCP의 진료 세션은 프로세스 안에만 있고,
    여러 프로세스로 띄우면 세션이 갈린다.

그 한계를 없앤다. 세션·패치 원장·기준선을 DB에 두면 (1) 프로세스가 죽어도
진료가 이어지고 (2) API를 여러 대로 띄워도 같은 세션을 본다.

## 무엇을 저장하고 무엇을 저장하지 않는가

**저장하는 것은 처방과 그 증거뿐이다.** 색인이나 분석기 상태는 넣지 않는다.
그것들은 **처방으로부터 결정적으로 재구성**되기 때문이다 — 같은 처방 목록을
같은 순서로 다시 적용하면 같은 설정이 나온다. 재구성 가능한 것을 저장하면
두 벌이 생기고, 두 벌은 갈라진다.

이것이 이 프로젝트가 처음부터 처방을 **구조화된 IR**로 받은 값이다. 자연어
조언이었다면 저장해도 재구성할 수 없었다.

## 스키마

    clinic_session   진료 세션 (id, label, 생성 시각)
    clinic_patch     채택된 처방 + 게이트 증거 (세션에 종속, 순서 보존)
    clinic_baseline  검색 품질 기준선 (CI가 대조하는 값)

`clinic_patch.seq`가 순서를 보존한다. 처방은 **누적 순서에 의존**하므로
순서가 흐트러지면 재구성된 설정이 달라진다.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass

DEFAULT_ENV_VAR = "DATABASE_URL"

SCHEMA = """
CREATE TABLE IF NOT EXISTS clinic_session (
    session_id  TEXT PRIMARY KEY,
    label       TEXT NOT NULL DEFAULT '',
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS clinic_patch (
    session_id  TEXT NOT NULL REFERENCES clinic_session(session_id) ON DELETE CASCADE,
    -- 처방은 누적 순서에 의존한다. 순서가 흐트러지면 재구성된 설정이 달라진다.
    seq         INTEGER NOT NULL,
    prescription JSONB NOT NULL,
    evidence    JSONB NOT NULL,
    attempts    INTEGER NOT NULL DEFAULT 1,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (session_id, seq)
);

CREATE TABLE IF NOT EXISTS clinic_baseline (
    name        TEXT PRIMARY KEY,
    payload     JSONB NOT NULL,
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);
"""


class PostgresUnavailable(RuntimeError):
    """드라이버가 없거나 접속할 수 없다. 호출자가 메모리 저장소로 되돌아간다."""


@dataclass(frozen=True)
class StoredPatch:
    seq: int
    prescription: dict
    evidence: dict
    attempts: int


def _connect(dsn: str):
    try:
        import psycopg2
    except ImportError as e:  # pragma: no cover - 선택 의존성
        raise PostgresUnavailable(
            'psycopg2가 필요합니다:  pip install -e ".[postgres]"'
        ) from e
    try:
        return psycopg2.connect(dsn)
    except Exception as e:  # pragma: no cover - 접속 환경에 따라 갈림
        raise PostgresUnavailable(f"PostgreSQL에 접속할 수 없습니다: {e}") from e


class PostgresStore:
    """진료 세션·원장·기준선의 영속 저장소."""

    def __init__(self, dsn: str | None = None) -> None:
        self.dsn = dsn or os.environ.get(DEFAULT_ENV_VAR, "")
        if not self.dsn:
            raise PostgresUnavailable(
                f"접속 문자열이 없습니다. 환경변수 {DEFAULT_ENV_VAR}를 설정하세요."
            )
        self._conn = _connect(self.dsn)
        self._conn.autocommit = True
        self.migrate()

    def migrate(self) -> None:
        """스키마를 만든다. 여러 번 불러도 안전하다(IF NOT EXISTS)."""
        with self._conn.cursor() as cur:
            cur.execute(SCHEMA)

    def close(self) -> None:
        self._conn.close()

    # ------------------------------------------------------------- 세션

    def create_session(self, session_id: str, label: str = "") -> None:
        with self._conn.cursor() as cur:
            cur.execute(
                "INSERT INTO clinic_session (session_id, label) VALUES (%s, %s) "
                "ON CONFLICT (session_id) DO NOTHING",
                (session_id, label),
            )

    def session_exists(self, session_id: str) -> bool:
        with self._conn.cursor() as cur:
            cur.execute("SELECT 1 FROM clinic_session WHERE session_id = %s", (session_id,))
            return cur.fetchone() is not None

    def list_sessions(self) -> list[dict]:
        with self._conn.cursor() as cur:
            cur.execute(
                "SELECT s.session_id, s.label, COUNT(p.seq) "
                "FROM clinic_session s LEFT JOIN clinic_patch p USING (session_id) "
                "GROUP BY s.session_id, s.label, s.created_at "
                "ORDER BY s.created_at DESC"
            )
            return [
                {"session_id": sid, "label": label, "accepted_count": int(n)}
                for sid, label, n in cur.fetchall()
            ]

    def delete_session(self, session_id: str) -> bool:
        with self._conn.cursor() as cur:
            cur.execute("DELETE FROM clinic_session WHERE session_id = %s", (session_id,))
            return cur.rowcount > 0

    # ------------------------------------------------------------- 원장

    def append_patch(
        self, session_id: str, prescription: dict, evidence: dict, attempts: int = 1
    ) -> int:
        """처방 하나를 원장 끝에 붙인다. 반환값은 부여된 순번.

        순번을 DB가 계산하게 두는 이유는 여러 프로세스가 같은 세션에 쓸 때
        파이썬 쪽에서 센 번호가 겹칠 수 있기 때문이다.
        """
        with self._conn.cursor() as cur:
            cur.execute(
                "INSERT INTO clinic_patch (session_id, seq, prescription, evidence, attempts) "
                "SELECT %s, COALESCE(MAX(seq), 0) + 1, %s, %s, %s "
                "FROM clinic_patch WHERE session_id = %s RETURNING seq",
                (
                    session_id,
                    json.dumps(prescription, ensure_ascii=False),
                    json.dumps(evidence, ensure_ascii=False),
                    attempts,
                    session_id,
                ),
            )
            return int(cur.fetchone()[0])

    def load_patches(self, session_id: str) -> list[StoredPatch]:
        """채택 순서대로. 이 순서가 곧 설정 재구성의 순서다."""
        with self._conn.cursor() as cur:
            cur.execute(
                "SELECT seq, prescription, evidence, attempts FROM clinic_patch "
                "WHERE session_id = %s ORDER BY seq",
                (session_id,),
            )
            return [
                StoredPatch(seq=int(s), prescription=p, evidence=e, attempts=int(a))
                for s, p, e, a in cur.fetchall()
            ]

    # ----------------------------------------------------------- 기준선

    def save_baseline(self, name: str, payload: dict) -> None:
        with self._conn.cursor() as cur:
            cur.execute(
                "INSERT INTO clinic_baseline (name, payload, updated_at) "
                "VALUES (%s, %s, now()) "
                "ON CONFLICT (name) DO UPDATE SET payload = EXCLUDED.payload, updated_at = now()",
                (name, json.dumps(payload, ensure_ascii=False)),
            )

    def load_baseline(self, name: str) -> dict | None:
        with self._conn.cursor() as cur:
            cur.execute("SELECT payload FROM clinic_baseline WHERE name = %s", (name,))
            row = cur.fetchone()
            return row[0] if row else None


def open_store(dsn: str | None = None) -> PostgresStore | None:
    """저장소를 열되, 못 열면 None.

    예외를 던지지 않는 이유: **DB 없이 도는 것이 이 프로젝트의 기본 상태**다.
    진료소는 CLI만으로 완결되고, PostgreSQL은 여러 프로세스로 띄울 때
    필요해지는 **선택지**이지 필수품이 아니다.
    """
    try:
        return PostgresStore(dsn)
    except PostgresUnavailable:
        return None
