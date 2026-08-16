"""코퍼스 설계 계약 검증.

카탈로그와 평가셋은 실측된 분석기 동작 위에 설계된 정밀한 구조물이다.
문서 하나를 무심코 고치면 실패 계열이 조용히 무너진다 — 예컨대 어떤
문서 설명에 '티슈'가 단독으로 들어가는 순간 compound_locked 계열의
"0건 실패"가 사라진다. 이 테스트가 그 계약을 지킨다.
"""

from searchclinic.corpus import (
    ZERO_RESULT_AT_BASELINE,
    failing_queries,
    healthy_queries,
    load_catalog,
)
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


def test_zero_result_queries_are_actually_zero():
    """0건으로 설계된 질의는 실제로 0건이어야 한다."""
    engine = _engine()
    for eq in failing_queries():
        if eq.query in ZERO_RESULT_AT_BASELINE:
            m = evaluate_query(engine, eq)
            assert m.zero_result, f"{eq.query}: 0건이어야 하는데 {m.n_results}건"


def test_non_zero_failures_return_junk_not_nothing():
    """0건이 아닌 실패 질의는 '결과는 나오는데 틀린' 상태여야 한다.

    이쪽이 실무에서 더 위험하다 — 검색이 되는 것처럼 보여 아무도 신고하지 않는다.
    """
    engine = _engine()
    for eq in failing_queries():
        if eq.query in ZERO_RESULT_AT_BASELINE:
            continue
        m = evaluate_query(engine, eq)
        assert m.n_results > 0, f"{eq.query}: 0건이면 ZERO_RESULT_AT_BASELINE에 넣어야 한다"
        assert m.ndcg < 0.95, f"{eq.query}: 결과는 나오지만 틀려야 하는데 nDCG {m.ndcg}"


def test_backpack_trap_needs_two_stage_prescription():
    """'백팩'은 동의어만으로는 절대 고쳐지지 않는다 (사전 등록이 선행돼야 함).

    질의가 [백, 팩]으로 부서지므로 '백팩'이라는 토큰 자체가 생기지 않는다.
    동의어 그룹에 '백팩'을 넣어도 발화되지 않아 표적이 개선되지 않고 기각된다.
    """
    from searchclinic.analysis.config import AnalyzerConfig, SynonymGroup, UserWord

    engine = _engine()
    eq = next(q for q in failing_queries() if q.query == "백팩")

    synonym_only = engine.with_config(
        AnalyzerConfig(synonym_groups=[SynonymGroup(terms=["배낭", "백팩"])])
    )
    assert evaluate_query(synonym_only, eq).ndcg == 0.0, "동의어만으로 고쳐지면 함정이 아니다"

    two_stage = engine.with_config(
        AnalyzerConfig(
            user_words=[UserWord(form="백팩")],
            synonym_groups=[SynonymGroup(terms=["배낭", "백팩"])],
        )
    )
    assert evaluate_query(two_stage, eq).ndcg == 1.0, "2단계 처방으로는 풀려야 한다"


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


def test_documented_scale_matches_reality():
    """문서가 선언한 코퍼스 규모가 실제와 일치해야 한다.

    실측 실패: 질의를 하나 추가한 뒤 문서의 '66건/35질의/실패 15'가 그대로
    남아 조용히 거짓말이 됐다. 검증되지 않는 문서 수치는 반드시 낡는다.

    규모를 '선언하는' 문장만 대조한다 — 본문에는 '평가셋 16건을 순회'처럼
    부분집합을 가리키는 정당한 표현이 있으므로 숫자를 싸잡아 훑지 않는다.
    """
    from pathlib import Path

    from searchclinic.corpus import load_evalset

    n_docs, n_eval = len(load_catalog()), len(load_evalset())
    n_fail, n_healthy = len(failing_queries()), len(healthy_queries())
    assert n_fail + n_healthy == n_eval, "실패+건강이 평가셋 전체와 다르다"

    required = {
        "README.md": [
            f"상품 카탈로그 {n_docs}건",
            f"평가셋 {n_eval}질의",
            f"건강 {n_healthy} + 실패 {n_fail}",
        ],
        "docs/ARCHITECTURE.md": [
            f"상품 카탈로그 {n_docs}건",
            f"문서 {n_docs}건, 질의 {n_eval}건(건강 {n_healthy} + 실패 {n_fail})",
        ],
        "docs/EVALUATION.md": [f"코퍼스 {n_docs}건, 평가셋 {n_eval}건"],
    }

    root = Path(__file__).resolve().parent.parent
    stale = [
        f"{rel}: '{phrase}' 없음"
        for rel, phrases in required.items()
        for phrase in phrases
        if phrase not in (root / rel).read_text(encoding="utf-8")
    ]
    assert not stale, "문서의 규모 선언이 실제와 어긋남: " + "; ".join(stale)
