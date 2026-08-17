"""PostgreSQL 영속성 — 진료가 프로세스보다 오래 사는가.

DB가 없으면 통째로 건너뛴다. **DB 없이 도는 것이 이 프로젝트의 기본 상태**
이므로, 이 테스트가 필수가 되면 안 된다.

여기서 증명할 것은 CRUD가 아니라 하나다:

    프로세스를 새로 띄워도 진료가 이어지는가.

그걸 보이려면 서비스 객체를 **버리고 새로 만든 뒤** 같은 세션이 살아 있는지
확인해야 한다. 같은 객체에서 읽으면 메모리 캐시를 보는 것이라 아무것도
증명하지 못한다.
"""

import os
import uuid

import pytest

psycopg2 = pytest.importorskip("psycopg2", reason="PostgreSQL은 선택 의존성이다")

from searchclinic.service import ClinicService, SessionNotFound  # noqa: E402
from searchclinic.store import PostgresStore, PostgresUnavailable, open_store  # noqa: E402

DSN = os.environ.get("CLINIC_TEST_DSN", "postgresql://clinic:clinic@localhost:5432/clinicdb")

GOOD_RX = {
    "target_query": "후라이팬",
    "diagnosis_family": "spelling_variant",
    "reasoning": "후라이팬은 프라이팬의 비표준 표기다. 최소 범위 동의어로 잇는다.",
    "synonym_groups": [{"terms": ["프라이팬", "후라이팬"]}],
}
OVERBROAD_RX = {
    "target_query": "후라이팬",
    "diagnosis_family": "spelling_variant",
    "reasoning": "팬은 프라이팬의 준말이므로 함께 묶는다 (과잉 일반화).",
    "synonym_groups": [{"terms": ["프라이팬", "후라이팬", "팬"]}],
}


@pytest.fixture(scope="module")
def store():
    try:
        s = PostgresStore(DSN)
    except PostgresUnavailable as e:
        pytest.skip(f"PostgreSQL 없음: {e}")
    yield s
    s.close()


@pytest.fixture
def sid(store):
    session_id = uuid.uuid4().hex[:12]
    yield session_id
    store.delete_session(session_id)


# ------------------------------------------------------------- 저장소

def test_migrate_is_idempotent(store):
    """여러 프로세스가 동시에 뜨면 마이그레이션이 겹쳐 돈다."""
    store.migrate()
    store.migrate()


def test_open_store_returns_none_without_dsn(monkeypatch):
    """DB가 없다고 죽으면 안 된다 — 없이 도는 것이 기본 상태다."""
    monkeypatch.delenv("DATABASE_URL", raising=False)
    assert open_store(None) is None


def test_patches_keep_their_order(store, sid):
    """처방은 누적 순서에 의존한다 — 순서가 흐트러지면 설정이 달라진다."""
    store.create_session(sid, "순서")
    seqs = [
        store.append_patch(sid, {"target_query": f"q{i}"}, {"regressions": 0}) for i in range(4)
    ]
    assert seqs == [1, 2, 3, 4]
    assert [p.prescription["target_query"] for p in store.load_patches(sid)] == [
        "q0", "q1", "q2", "q3"
    ]


def test_deleting_a_session_removes_its_patches(store, sid):
    """세션만 지우고 처방이 남으면 다음 세션이 남의 설정을 물려받는다."""
    store.create_session(sid)
    store.append_patch(sid, {"target_query": "후라이팬"}, {})
    store.delete_session(sid)
    assert store.load_patches(sid) == []


def test_korean_survives_the_roundtrip(store, sid):
    store.create_session(sid, "한글 라벨")
    store.append_patch(sid, {"summary": "동의어(프라이팬 = 후라이팬)"}, {})
    assert store.load_patches(sid)[0].prescription["summary"] == "동의어(프라이팬 = 후라이팬)"


def test_baseline_upsert(store):
    name = f"t-{uuid.uuid4().hex[:8]}"
    store.save_baseline(name, {"mean_ndcg": 0.5})
    store.save_baseline(name, {"mean_ndcg": 0.9})
    assert store.load_baseline(name)["mean_ndcg"] == 0.9
    assert store.load_baseline("없는기준선") is None


# --------------------------------------------------- 서비스와의 결합

def test_session_survives_a_process_restart(store):
    """이 테스트가 이 기능의 존재 이유다.

    서비스 객체를 버리고 새로 만든다 — 프로세스를 새로 띄운 것과 같다.
    같은 객체에서 읽으면 메모리 캐시를 보는 것이라 아무것도 증명하지 못한다.
    """
    first = ClinicService(store=store)
    sid = first.create_session("재시작 시험")["session_id"]
    first.open_query(sid, "후라이팬")
    assert first.submit_prescription(sid, GOOD_RX)["accepted"] is True
    assert first.search("후라이팬", session_id=sid)["total"] == 2

    del first  # 프로세스가 죽었다고 치자

    second = ClinicService(store=store)
    assert second.search("후라이팬", session_id=sid)["total"] == 2

    described = second.describe_session(sid)
    assert {"프라이팬", "후라이팬"} == set(described["config"]["synonym_groups"][0]["terms"])
    second.delete_session(sid)


def test_restarted_session_keeps_the_evidence_not_just_the_config(store):
    """설정만 살아나고 원장이 비면 "왜 넣었는지"가 사라진다.

    이 프로젝트의 원칙이 "채택된 모든 패치에 증거가 남는다"인데, 재시작에서
    그게 깨지면 원칙이 가장 필요한 순간에 없는 것이다 — 운영 중 재시작 뒤
    사전에 왜 이 항목이 있는지 아무도 모르게 된다.
    """
    first = ClinicService(store=store)
    sid = first.create_session("근거 보존")["session_id"]
    first.open_query(sid, "후라이팬")
    first.submit_prescription(sid, GOOD_RX)

    revived = ClinicService(store=store).describe_session(sid)
    assert revived["accepted_count"] == 1
    entry = revived["ledger"][0]
    assert entry["summary"] == "동의어(프라이팬 = 후라이팬)"
    assert entry["reasoning"] == GOOD_RX["reasoning"]
    assert entry["evidence"]["target_ndcg_before"] == 0.0
    assert entry["evidence"]["target_ndcg_after"] == 1.0
    assert entry["evidence"]["regressions"] == 0
    assert entry["restored"] is True  # 이번 프로세스가 아니라 저장소에서 온 줄

    ClinicService(store=store).delete_session(sid)


def test_rejected_prescriptions_are_not_persisted(store):
    """기각된 처방을 저장하면 재구성이 틀린 설정을 만든다."""
    svc = ClinicService(store=store)
    sid = svc.create_session()["session_id"]
    svc.open_query(sid, "후라이팬")
    assert svc.submit_prescription(sid, OVERBROAD_RX)["accepted"] is False

    assert store.load_patches(sid) == []
    revived = ClinicService(store=store)
    assert revived.describe_session(sid)["config"]["synonym_groups"] == []
    svc.delete_session(sid)


def test_deleted_session_is_gone_from_both(store):
    svc = ClinicService(store=store)
    sid = svc.create_session()["session_id"]
    svc.delete_session(sid)
    assert not store.session_exists(sid)
    with pytest.raises(SessionNotFound):
        ClinicService(store=store).describe_session(sid)


def test_health_reports_persistence(store):
    assert ClinicService(store=store).health()["persistent"] is True
    assert ClinicService().health()["persistent"] is False


def test_sessions_are_visible_across_service_instances(store):
    """다른 프로세스가 만든 세션도 목록에 보여야 한다 — 여러 대로 띄우는 이유."""
    a = ClinicService(store=store)
    sid = a.create_session("공유")["session_id"]
    b = ClinicService(store=store)
    assert sid in {s["session_id"] for s in b.list_sessions()["sessions"]}
    b.delete_session(sid)
