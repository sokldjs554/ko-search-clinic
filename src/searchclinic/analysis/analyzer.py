"""한국어 분석기 — Kiwi 형태소 분석 + 설정(AnalyzerConfig) 적용.

파이프라인:

    원문 → Kiwi 형태소 분석 (사용자 사전 반영)
        → 내용어 필터 (조사/어미 제거)
        → 소문자화 (영문 대소문자 통일)
        → 복합어 분해 확장 (물티슈 → 물티슈·물·티슈)
        → 동의어 정규화 (케잌 → 케이크)
        → 토큰 목록

색인과 질의가 **같은 파이프라인**을 지나므로, 설정이 바뀌면 색인을 다시
만들어야 한다 (SearchEngine이 담당). 이는 Elasticsearch에서 analyzer 설정
변경 시 reindex가 필요한 것과 같은 제약이며, 일부러 같게 만들었다.
"""

from __future__ import annotations

from dataclasses import dataclass

from kiwipiepy import Kiwi

from searchclinic.analysis.config import AnalyzerConfig

# 검색에 의미 있는 내용어 품사만 남긴다 (nori의 POS 필터와 같은 취지).
# N*: 체언, SL: 외국어(영문), SN: 숫자, SH: 한자, XR: 어근, VV/VA: 용언 어간
_KEEP_PREFIXES = ("NN", "NR", "NP", "SL", "SN", "SH", "XR", "VV", "VA")

_USER_WORD_SCORE = 12.0  # Kiwi 기본 분석을 확실히 이기도록 높게

# Kiwi 초기화는 ~2초로 비싸다. 게이트가 샌드박스 엔진을 만들 때마다 새로
# 초기화하면 진료 한 바퀴에 분 단위가 걸리므로, **등록 단어 집합이 같으면
# 같은 인스턴스를 공유**한다. tokenize는 상태를 바꾸지 않으므로 안전하고,
# 동의어·분해 확장은 Kiwi 밖(파이썬 후처리)에서 적용되므로 키에 안 들어간다.
_kiwi_cache: dict[tuple, Kiwi] = {}


def _kiwi_for(words: tuple[tuple[str, str], ...]) -> Kiwi:
    if words not in _kiwi_cache:
        kiwi = Kiwi()
        for form, tag in words:
            kiwi.add_user_word(form, tag, _USER_WORD_SCORE)
        _kiwi_cache[words] = kiwi
    return _kiwi_cache[words]


@dataclass(frozen=True)
class AnalyzedToken:
    """토큰 하나. origin은 이 토큰이 어떻게 나왔는지 설명한다 (진단 도구용)."""

    form: str
    tag: str
    origin: str  # "kiwi" | "expansion" | "synonym:<원형>"


class KoreanAnalyzer:
    """설정이 적용된 분석기. 설정이 다르면 새 인스턴스를 만든다 (불변)."""

    def __init__(self, config: AnalyzerConfig | None = None) -> None:
        self.config = config or AnalyzerConfig()
        # 사용자 사전(쓰레기 분해 교정) + 복합어(통짜 토큰이 나와야 확장이 걸림)
        words = tuple(
            sorted(
                {(w.form, w.tag) for w in self.config.user_words}
                | {(c.word, "NNP") for c in self.config.compound_expansions}
            )
        )
        self._kiwi = _kiwi_for(words)
        self._expansions = {c.word: c.parts for c in self.config.compound_expansions}
        self._canonical: dict[str, str] = {}
        for g in self.config.synonym_groups:
            for term in g.terms:
                self._canonical[term.lower()] = g.canonical.lower()

    # ------------------------------------------------------------------ 분석

    def analyze(self, text: str) -> list[AnalyzedToken]:
        """전체 파이프라인을 적용한 토큰 목록 (진단용 상세 정보 포함)."""
        out: list[AnalyzedToken] = []
        for tok in self._kiwi.tokenize(text):
            if not tok.tag.startswith(_KEEP_PREFIXES):
                continue
            form = tok.form.lower()
            emitted = [(form, tok.tag, "kiwi")]
            # 복합어 분해 확장: 통짜 토큰과 부분어를 함께 방출 (mixed)
            if form in self._expansions:
                emitted.extend(
                    (p.lower(), "NNG", "expansion") for p in self._expansions[form]
                )
            for f, tag, origin in emitted:
                canon = self._canonical.get(f)
                if canon is not None and canon != f:
                    out.append(AnalyzedToken(canon, tag, f"synonym:{f}"))
                else:
                    out.append(AnalyzedToken(f, tag, origin))
        return out

    def tokens(self, text: str) -> list[str]:
        """검색 색인/질의에 쓰는 최종 토큰 형태 목록."""
        return [t.form for t in self.analyze(text)]

    def explain(self, text: str) -> list[dict]:
        """진단 도구용: 각 토큰이 어떤 경로로 나왔는지 설명한다.

        의사 도구(`analyze_text`)가 그대로 쓰는 출력이라 형태를 바꾸지 않는다 —
        실측 결과가 이 출력 위에서 나왔다. 버려진 토큰까지 보려면
        `explain_with_dropped()`를 쓴다 (CLI `clinic analyze` 전용).
        """
        return [
            {"token": t.form, "tag": t.tag, "origin": t.origin}
            for t in self.analyze(text)
        ]

    def dropped(self, text: str) -> list[tuple[str, str]]:
        """내용어 필터에서 **버려진** 토큰 (form, tag) 목록.

        `아답터`가 대표 사례다. Kiwi는 이걸 [아(IC), 답(NNG), 터(NNG)]로
        쪼개는데, 첫 음절 '아'가 **감탄사(IC)로 오인**돼 필터에서 통째로
        사라진다. 남는 색인 토큰은 [답, 터]뿐이라 '아답터'는 무엇과도
        매칭되지 않는다 — 왜 0건인지 설명하려면 사라진 조각을 보여야 한다.
        """
        return [
            (tok.form, tok.tag)
            for tok in self._kiwi.tokenize(text)
            if not tok.tag.startswith(_KEEP_PREFIXES)
        ]
