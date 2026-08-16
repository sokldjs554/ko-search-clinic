"""분석기 파이프라인 테스트 — 설정의 각 요소가 토큰화를 실제로 바꾸는지."""

from searchclinic.analysis import (
    AnalyzerConfig,
    CompoundExpansion,
    KoreanAnalyzer,
    SynonymGroup,
    UserWord,
)


def test_base_analysis_keeps_content_words():
    tokens = KoreanAnalyzer().tokens("달콤한 샤인머스캣 포도 2kg")
    assert "샤인머스캣" in tokens
    assert "포도" in tokens
    # 조사·어미는 걸러진다 (ㄴ 어미 등)
    assert "ᆫ" not in tokens


def test_english_lowercased():
    tokens = KoreanAnalyzer().tokens("Bluetooth 스피커")
    assert "bluetooth" in tokens


def test_garbage_split_reproduced():
    """실측 근거: 아답터는 기본 분석에서 [아,답,터]로 부서진다."""
    tokens = KoreanAnalyzer().tokens("아답터")
    assert "아답터" not in tokens


def test_user_word_fixes_garbage_split():
    config = AnalyzerConfig(user_words=[UserWord(form="아답터")])
    assert "아답터" in KoreanAnalyzer(config).tokens("아답터")


def test_compound_kept_whole_without_expansion():
    """실측 근거: 물티슈는 한 토큰 — '티슈'로는 못 찾는 상태."""
    tokens = KoreanAnalyzer().tokens("아기 물티슈")
    assert "물티슈" in tokens
    assert "티슈" not in tokens


def test_compound_expansion_emits_whole_and_parts():
    config = AnalyzerConfig(
        compound_expansions=[CompoundExpansion(word="물티슈", parts=["물", "티슈"])]
    )
    tokens = KoreanAnalyzer(config).tokens("아기 물티슈")
    assert "물티슈" in tokens  # 통짜 유지 (mixed)
    assert "티슈" in tokens  # 부분어 추가
    assert "물" in tokens


def test_synonym_canonicalization():
    config = AnalyzerConfig(
        synonym_groups=[SynonymGroup(terms=["프라이팬", "후라이팬"])]
    )
    analyzer = KoreanAnalyzer(config)
    assert analyzer.tokens("후라이팬") == ["프라이팬"]
    # explain은 정규화 경로를 남긴다
    origins = [t["origin"] for t in analyzer.explain("후라이팬")]
    assert any(o.startswith("synonym:") for o in origins)


def test_synonym_applies_to_expansion_output():
    """분해 확장으로 나온 부분어에도 동의어 정규화가 걸린다 (파이프라인 순서)."""
    config = AnalyzerConfig(
        compound_expansions=[CompoundExpansion(word="물티슈", parts=["물", "티슈"])],
        synonym_groups=[SynonymGroup(terms=["휴지", "티슈"])],
    )
    tokens = KoreanAnalyzer(config).tokens("물티슈")
    assert "휴지" in tokens  # 티슈 → 휴지 정규화


def test_analyzer_is_deterministic():
    a = KoreanAnalyzer()
    text = "무선 이어폰 Bluetooth 5.3 노이즈 캔슬링"
    assert a.tokens(text) == a.tokens(text) == KoreanAnalyzer().tokens(text)
