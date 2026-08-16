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


def test_dropped_tokens_expose_why_adapter_finds_nothing():
    """'아답터'의 첫 음절은 감탄사(IC)로 오인돼 색인에서 사라진다.

    이 사실을 감추면 "왜 0건인가"의 절반이 설명되지 않는다 — 단어가
    부서지는 것만이 아니라 조각 하나가 아예 버려진다.
    """
    a = KoreanAnalyzer()
    assert a.tokens("아답터") == ["답", "터"]
    assert ("아", "IC") in a.dropped("아답터")


def test_backpack_first_syllable_is_read_as_a_number():
    """'백팩'의 '백'은 수사(NR, 숫자 100)로 분석된다 — 의미가 통째로 어긋난다."""
    a = KoreanAnalyzer()
    tags = {t["token"]: t["tag"] for t in a.explain("백팩")}
    assert tags["백"] == "NR"
    assert a.dropped("백팩") == []  # 버려지진 않는다 — 쓰레기가 되어 남는다


def test_explain_output_shape_is_unchanged_for_the_doctor_tool():
    """의사 도구가 쓰는 explain()의 형태는 고정이다.

    16/16 실측이 이 출력 위에서 나왔다. 키가 늘거나 버려진 토큰이 섞여
    들어가면 그 결과의 재현성이 깨진다 — dropped()는 별도 통로다.
    """
    rows = KoreanAnalyzer().explain("아답터")
    assert all(set(r) == {"token", "tag", "origin"} for r in rows)
    assert all(r["tag"].startswith(("NN", "NR", "NP", "SL", "SN", "SH", "XR", "VV", "VA"))
               for r in rows)
