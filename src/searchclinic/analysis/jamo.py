"""자모 분해와 자모 편집 거리.

'케잌'과 '케이크'는 음절 단위로는 아예 다른 문자열이지만, 자모로 풀면
ㅋㅔㅇㅣㄱ vs ㅋㅔㅇㅣㅋㅡ — 거의 같다. 표기 변형 후보를 찾으려면
음절이 아니라 자모 수준에서 거리를 재야 한다.

외부 의존성 없이 유니코드 산술로 구현한다 (한글 음절 = U+AC00 + 초성×588
+ 중성×28 + 종성).
"""

from __future__ import annotations

_BASE = 0xAC00
_CHOSEONG = [
    "ㄱ", "ㄲ", "ㄴ", "ㄷ", "ㄸ", "ㄹ", "ㅁ", "ㅂ", "ㅃ", "ㅅ",
    "ㅆ", "ㅇ", "ㅈ", "ㅉ", "ㅊ", "ㅋ", "ㅌ", "ㅍ", "ㅎ",
]
_JUNGSEONG = [
    "ㅏ", "ㅐ", "ㅑ", "ㅒ", "ㅓ", "ㅔ", "ㅕ", "ㅖ", "ㅗ", "ㅘ",
    "ㅙ", "ㅚ", "ㅛ", "ㅜ", "ㅝ", "ㅞ", "ㅟ", "ㅠ", "ㅡ", "ㅢ", "ㅣ",
]
_JONGSEONG = [
    "", "ㄱ", "ㄲ", "ㄳ", "ㄴ", "ㄵ", "ㄶ", "ㄷ", "ㄹ", "ㄺ",
    "ㄻ", "ㄼ", "ㄽ", "ㄾ", "ㄿ", "ㅀ", "ㅁ", "ㅂ", "ㅄ", "ㅅ",
    "ㅆ", "ㅇ", "ㅈ", "ㅊ", "ㅋ", "ㅌ", "ㅍ", "ㅎ",
]


def to_jamo(text: str) -> str:
    """한글 음절을 자모 나열로 푼다. 한글이 아닌 문자는 그대로 둔다."""
    out: list[str] = []
    for ch in text:
        code = ord(ch)
        if _BASE <= code <= 0xD7A3:
            offset = code - _BASE
            out.append(_CHOSEONG[offset // 588])
            out.append(_JUNGSEONG[(offset % 588) // 28])
            jong = _JONGSEONG[offset % 28]
            if jong:
                out.append(jong)
        else:
            out.append(ch)
    return "".join(out)


def jamo_distance(a: str, b: str) -> int:
    """자모 수준 Levenshtein 거리."""
    ja, jb = to_jamo(a), to_jamo(b)
    if ja == jb:
        return 0
    if not ja or not jb:
        return max(len(ja), len(jb))
    prev = list(range(len(jb) + 1))
    for i, ca in enumerate(ja, 1):
        cur = [i]
        for j, cb in enumerate(jb, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (ca != cb)))
        prev = cur
    return prev[-1]


def jamo_similarity(a: str, b: str) -> float:
    """0~1 유사도: 1 - 거리/최대자모길이."""
    ja, jb = to_jamo(a), to_jamo(b)
    denom = max(len(ja), len(jb))
    if denom == 0:
        return 1.0
    return 1.0 - jamo_distance(a, b) / denom
