"""자모 분해·거리 테스트.

실측 고정(pin) 테스트가 중요하다: ScriptedDoctor의 임계값(0.65)은
케잌↔케이크(0.67)는 잡고 핸드폰↔휴대폰(0.63)은 놓치도록 설계됐다.
자모 구현이 바뀌어 이 값이 흔들리면 베이스라인의 한계선 전체가 무너진다.
"""

from searchclinic.analysis.jamo import jamo_distance, jamo_similarity, to_jamo
from searchclinic.doctor.scripted import SIM_THRESHOLD


def test_decompose_syllable():
    assert to_jamo("한") == "ㅎㅏㄴ"
    assert to_jamo("케이크") == "ㅋㅔㅇㅣㅋㅡ"
    assert to_jamo("케잌") == "ㅋㅔㅇㅣㅋ"  # 잌의 종성은 ㅋ


def test_non_hangul_passthrough():
    assert to_jamo("iPhone 15") == "iPhone 15"
    assert to_jamo("블루투스 5.3") == "ㅂㅡㄹㄹㅜㅌㅜㅅㅡ 5.3"


def test_distance_zero_for_same():
    assert jamo_distance("프라이팬", "프라이팬") == 0


def test_variant_pairs_above_threshold():
    """베이스라인이 잡아야 하는 표기 변형 쌍 — 임계값 위."""
    for a, b in [
        ("케잌", "케이크"),
        ("후라이팬", "프라이팬"),
        ("도너츠", "도넛"),
        ("쥬스", "주스"),
        ("소세지", "소시지"),
        ("카페트", "카펫"),
        ("초콜렛", "초콜릿"),
        ("리모콘", "리모컨"),
        ("아답터", "어댑터"),
    ]:
        assert jamo_similarity(a, b) >= SIM_THRESHOLD, (a, b, jamo_similarity(a, b))


def test_semantic_pairs_below_threshold():
    """형태가 다른 유의어 — 자모 규칙이 닿으면 안 되는 쌍 (베이스라인 한계선)."""
    for a, b in [
        ("핸드폰", "휴대폰"),
        ("츄리닝", "트레이닝복"),
        ("블루투스", "bluetooth"),
        ("텀블러", "tumbler"),
    ]:
        assert jamo_similarity(a, b) < SIM_THRESHOLD, (a, b, jamo_similarity(a, b))


def test_empty_strings():
    assert jamo_distance("", "") == 0
    assert jamo_similarity("", "") == 1.0
    assert jamo_distance("가", "") == 2  # ㄱ+ㅏ
