"""평가셋 — 질의, 정답 문서(graded qrels), 실패 계열 라벨.

두 종류의 질의가 있다:

- **건강 질의**(family=None): 현재 설정에서 잘 동작한다. 패치가 이들을
  망가뜨리면 안 된다 — 회귀 게이트의 감시 대상.
- **실패 질의**(family 지정): 현재 설정에서 실패하며, 왜 실패하는지의
  정답(계열)과 어떤 종류의 패치가 고쳐야 하는지(expected_patch_kinds)가
  라벨로 붙어 있다. 의사의 진단 정확도를 채점하는 근거다.

실패 계열 (전부 Kiwi 실측 동작에 근거):

| family          | 원인                                        | 처방            |
|-----------------|---------------------------------------------|-----------------|
| spelling_variant| 비표준 표기 → 토큰 단절 (후라이팬≠프라이팬)   | synonym         |
| cross_script    | 영한 표기 혼용 (Bluetooth≠블루투스)          | synonym         |
| synonym_gap     | 유의어 단절 (츄리닝≠트레이닝복)              | synonym         |
| compound_locked | 복합어가 한 토큰 → 부분어 질의 실패 (티슈↛물티슈) | compound_expansion |
| garbage_split   | 분석기가 질의를 쓰레기로 쪼갬 (아답터→아/답/터) | user_word + synonym |

qrels 등급: 2 = 정확 표적, 1 = 관련. nDCG 계산에 그대로 쓰인다.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class EvalQuery:
    query: str
    qrels: dict[str, int]  # doc_id -> 등급 (2 정확, 1 관련)
    family: str | None = None  # None이면 건강 질의
    expected_patch_kinds: tuple[str, ...] = ()  # 진단 채점용 정답 처방 유형
    note: str = ""

    @property
    def is_healthy(self) -> bool:
        return self.family is None


FAMILIES = (
    "spelling_variant",
    "cross_script",
    "synonym_gap",
    "compound_locked",
    "garbage_split",
)


def _q(query, qrels, family=None, expected=(), note="") -> EvalQuery:
    return EvalQuery(
        query=query,
        qrels=qrels,
        family=family,
        expected_patch_kinds=tuple(expected),
        note=note,
    )


# ------------------------------------------------------------------ 건강 질의
# 패치가 이들을 건드리면 회귀다. 특히 팬미팅/선풍기는 과잉 동의어 함정의
# 감시선이다.

HEALTHY: list[EvalQuery] = [
    _q("프라이팬", {"P001": 2, "P002": 2}),
    _q("케이크", {"P006": 2, "P007": 2}),
    _q("도넛", {"P004": 2, "P005": 2}),
    _q("주스", {"P009": 2, "P010": 2}),
    _q("소시지", {"P011": 2, "P012": 2}),
    _q("어댑터", {"P035": 2, "P036": 2}),
    _q("물티슈", {"P020": 2, "P021": 2}),
    _q("샤인머스캣", {"P050": 2, "P051": 2}),
    _q("트레이닝복", {"P060": 2, "P061": 2}),
    _q("휴대폰 거치대", {"P040": 2, "P038": 1}),
    _q("무선 이어폰", {"P030": 2}),
    _q("노트북 파우치", {"P031": 2}),
    _q("팬미팅 굿즈", {"P070": 2, "P071": 1}, note="과잉 동의어 함정 감시선"),
    _q("선풍기", {"P072": 2}, note="과잉 동의어 함정 감시선"),
    _q("캠핑 의자", {"P090": 2, "P091": 1}),
    _q("운동화", {"P062": 2}),
    _q("카펫", {"P016": 2, "P017": 2}),
    _q("리모컨", {"P041": 2, "P042": 1}),
    _q("가습기", {"P097": 2}),
    _q("김치", {"P052": 2}),
]

# ------------------------------------------------------------------ 실패 질의

FAILING: list[EvalQuery] = [
    # 표기 변형 → 동의어 처방
    _q("후라이팬", {"P001": 2, "P002": 2},
       "spelling_variant", ("synonym",), "표준형은 프라이팬"),
    _q("케잌 주문", {"P006": 2, "P007": 1},
       "spelling_variant", ("synonym",), "표준형은 케이크"),
    _q("도너츠", {"P004": 2, "P005": 2},
       "spelling_variant", ("synonym",), "표준형은 도넛"),
    _q("쥬스", {"P009": 2, "P010": 2},
       "spelling_variant", ("synonym",), "표준형은 주스"),
    _q("소세지", {"P011": 2, "P012": 2},
       "spelling_variant", ("synonym",), "표준형은 소시지"),
    _q("카페트", {"P016": 2, "P017": 2},
       "spelling_variant", ("synonym",), "표준형은 카펫"),
    _q("초콜렛", {"P008": 2, "P005": 1, "P007": 1},
       "spelling_variant", ("synonym",), "표준형은 초콜릿"),
    _q("리모콘", {"P041": 2, "P042": 1},
       "spelling_variant", ("synonym",), "표준형은 리모컨"),
    # 영한 혼용 → 동의어 처방 (0건이 아니라 순위 실패인 경우 포함)
    _q("블루투스 스피커", {"P032": 2},
       "cross_script", ("synonym",),
       "표적 문서는 Bluetooth로만 표기 — 스피커 토큰만 겹쳐 유사 문서에 묻힘"),
    _q("텀블러", {"P080": 2, "P081": 2},
       "cross_script", ("synonym",),
       "P081은 tumbler 영문 표기 — 절반만 검색됨"),
    # 유의어 → 동의어 처방
    _q("핸드폰", {"P038": 2, "P039": 2, "P040": 1},
       "synonym_gap", ("synonym",),
       "문서는 휴대폰/스마트폰으로 표기 — 핸드폰 단독 질의는 0건"),
    _q("츄리닝", {"P060": 2, "P061": 2},
       "synonym_gap", ("synonym",), "문서는 트레이닝복으로 표기"),
    # 복합어 통짜 → 분해 확장 처방
    _q("티슈", {"P020": 2, "P021": 2},
       "compound_locked", ("compound_expansion",),
       "물티슈가 한 토큰이라 부분어로 못 찾음"),
    _q("머스캣", {"P050": 2, "P051": 2},
       "compound_locked", ("compound_expansion",),
       "샤인머스캣이 한 토큰"),
    # 쓰레기 분해 → 사용자 사전 + 동의어 복합 처방
    _q("아답터", {"P035": 2, "P036": 2},
       "garbage_split", ("user_word", "synonym"),
       "아답터→[아,답,터]로 쪼개짐. 사전 등록 후 어댑터와 동의어 연결 — 2단계"),
]


def load_evalset() -> list[EvalQuery]:
    return HEALTHY + FAILING


def healthy_queries() -> list[EvalQuery]:
    return list(HEALTHY)


def failing_queries() -> list[EvalQuery]:
    return list(FAILING)
