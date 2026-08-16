"""코퍼스 설계 계약 검증.

카탈로그와 평가셋은 실측된 분석기 동작 위에 설계된 정밀한 구조물이다.
문서 하나를 무심코 고치면 실패 계열이 조용히 무너진다 — 예컨대 어떤
문서 설명에 '티슈'가 단독으로 들어가는 순간 compound_locked 계열의
"0건 실패"가 사라진다. 이 테스트가 그 계약을 지킨다.
"""

from searchclinic.corpus import failing_queries, healthy_queries, load_catalog
from searchclinic.evaluation.metrics import evaluate_query
from searchclinic.index.engine import SearchEngine


def _engine():
    return SearchEngine(load_catalog())


def test_catalog_ids_unique():
    ids = [d.doc_id for d in load_catalog()]
    assert len(ids) == len(set(ids))


def test_qrels_reference_existing_docs():
    ids = {d.doc_id for d in load_catalog()}
    for eq in healthy_queries() + failing_queries():
        missing = set(eq.qrels) - ids
        assert not missing, f"{eq.query}: 존재하지 않는 문서 {missing}"


def test_healthy_queries_all_work():
    """건강 질의는 전부 정답을 다 찾고 순위도 양호해야 한다."""
    engine = _engine()
    for eq in healthy_queries():
        m = evaluate_query(engine, eq)
        assert m.recall == 1.0, f"{eq.query}: recall {m.recall}"
        assert m.ndcg >= 0.7, f"{eq.query}: nDCG {m.ndcg}"


def test_failing_queries_all_fail_as_labeled():
    """실패 질의는 전부 실패 상태여야 한다 (고칠 게 있어야 진료가 성립)."""
    engine = _engine()
    for eq in failing_queries():
        m = evaluate_query(engine, eq)
        assert m.ndcg < 0.95, f"{eq.query}: 실패 질의인데 nDCG {m.ndcg}"


def test_zero_result_families_are_actually_zero():
    """표기변형·유의어·복합어·쓰레기분해 계열은 0건이어야 한다."""
    engine = _engine()
    for eq in failing_queries():
        if eq.family in ("spelling_variant", "synonym_gap", "compound_locked", "garbage_split"):
            m = evaluate_query(engine, eq)
            assert m.zero_result, f"{eq.query}: 0건이어야 하는데 {m.n_results}건"


def test_compound_parts_not_indexed_standalone():
    """실패 질의가 의존하는 부분어(티슈·머스캣)가 단독 토큰으로 없다.

    참고: '워시'는 이 목록에 없다. Kiwi가 '바디워시'를 문맥에 따라 다르게
    분석하는 것이 관찰됐기 때문이다 — P023 상품명("퍼퓸 바디워시 대용량")
    에서는 [바디, 워시]로 쪼개고, 설명문에서는 통짜로 유지한다. 형태소
    분석의 문맥 의존성이 실제로 일으키는 비일관성의 표본으로, 문서를
    고치는 대신 관찰 그대로 남겨 둔다 (실패 계열은 이 토큰에 의존하지 않는다).
    """
    vocab = set(_engine().vocabulary())
    for part in ("티슈", "머스캣"):
        assert part not in vocab, f"'{part}'가 색인에 단독 존재 — 계열 붕괴"
    # 통짜 형태는 존재해야 한다
    for whole in ("물티슈", "샤인머스캣"):
        assert whole in vocab


def test_trap_docs_carry_pan_token():
    """함정 문서들(팬미팅·선풍기)은 '팬' 토큰을 가져야 함정이 성립한다."""
    engine = _engine()
    for doc_id in ("P070", "P071", "P072", "P073"):
        assert "팬" in engine.doc_tokens(doc_id), f"{doc_id}에 팬 토큰 없음"
    # 프라이팬 문서는 '팬'이 아니라 '프라이팬' 통짜 토큰이다 (실측)
    assert "팬" not in engine.doc_tokens("P001")
    assert "프라이팬" in engine.doc_tokens("P001")


def test_standard_forms_only_in_documents():
    """문서에는 비표준 표기가 없어야 한다 (0건 실패의 전제)."""
    text = " ".join(d.text for d in load_catalog())
    for variant in ("후라이팬", "케잌", "도너츠", "쥬스", "소세지", "카페트", "초콜렛", "리모콘", "아답터", "츄리닝", "핸드폰"):
        assert variant not in text, f"문서에 비표준 표기 '{variant}' 존재"


def test_families_all_represented():
    families = {eq.family for eq in failing_queries()}
    assert families == {
        "spelling_variant",
        "cross_script",
        "synonym_gap",
        "compound_locked",
        "garbage_split",
    }
