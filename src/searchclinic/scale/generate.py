"""규모 실험용 합성 코퍼스와 질의 로그 — 결정적으로.

## 왜 필요한가

이 저장소의 결론은 전부 **문서 72건 · 질의 36건** 위에서 나왔다. 그 규모에서
"과잉 동의어는 회귀를 만든다"는 것을 보였지만, 실서비스는 문서가 수십만이고
질의 로그가 수백만이다. 거기서도 같은 판단이 나오는지는 **재보기 전에는 알 수
없다.** README에 한계로 적어 둔 것이 정확히 이것이다.

특히 의심스러운 지점이 하나 있다. BM25 점수는 IDF 항에 선형으로 비례하고,
그 IDF는 `log(1 + (N-df+0.5)/(df+0.5))`로 문서 빈도의 **로그**다. 감소는
완만하지만 방향은 분명하므로 **같은 패치라도 코퍼스 규모에 따라 안전성이
달라질 수 있다.** 문서 72건에서
`팬`을 동의어로 묶으면 오염이 즉시 보이지만, 문서 20만 건에서는 `팬`을 가진
문서가 상대적으로 희석돼 게이트가 통과시킬 수도 있다. 그러면 "게이트가
지킨다"는 이 프로젝트의 주장에 **규모 조건**이 붙는다.

그것을 재려면 규모를 바꿔가며 같은 처방을 던져볼 코퍼스가 필요하다.

## 무작위가 아니라 통제된 생성이다

문자열을 아무렇게나 만들면 형태소 분석 결과가 통제되지 않아 실패 계열이
무너진다. 그래서 **실측으로 설계된 원본 카탈로그의 구조를 유지**한 채
규모만 늘린다:

- 표준 표기만 쓴다 (비표준 표기 질의가 0건이 되는 근거)
- '팬' 토큰을 가진 문서 비율을 파라미터로 고정한다 (오염 함정의 밀도)
- 시드를 받아 **같은 시드면 같은 코퍼스**가 나온다

`random` 대신 시드 기반 결정적 생성을 쓰는 이유는, 규모 실험 결과가
재현되지 않으면 그 수치로 아무 말도 할 수 없기 때문이다.
"""

from __future__ import annotations

import random
from dataclasses import dataclass

from searchclinic.corpus.catalog import Document, load_catalog

# 합성 문서를 만들 때 쓰는 부품. 전부 표준 표기다 — 비표준 표기를 섞으면
# 실패 질의가 우연히 매칭돼 계열이 무너진다.
_MATERIALS = ["스테인리스", "실리콘", "유리", "도자기", "면", "가죽", "알루미늄", "대나무"]
_ADJECTIVES = ["프리미엄", "실속형", "휴대용", "대용량", "미니", "접이식", "인체공학", "무선"]
_NOUNS = [
    "주전자", "머그컵", "도마", "국자", "밀폐용기", "수저세트", "행주", "앞치마",
    "노트북", "마우스", "키보드", "모니터", "이어폰", "충전기", "케이블", "거치대",
    "티셔츠", "바지", "양말", "모자", "가방", "지갑", "벨트", "신발",
]
_CATEGORIES = ["주방", "가전", "패션", "생활"]

# '팬' 토큰을 만드는 문서들 — 과잉 동의어 오염 함정의 재료.
_FAN_TEMPLATES = [
    ("{who} 팬미팅 응원봉", "{who} 팬미팅 공식 굿즈. 팬 여러분을 위한 한정 수량."),
    ("{who} 팬클럽 가입 키트", "팬클럽 회원 전용 구성품. 팬 인증 카드 포함."),
    ("스탠드 선풍기 {n}인치", "저소음 선풍기. 팬 날개 {n}인치로 넓은 풍량."),
]
_WHO = ["아이돌", "배우", "가수", "밴드"]


@dataclass(frozen=True)
class QueryLogRow:
    """검색 로그 한 줄 — 실서비스 로그에서 흔히 쓰는 최소 필드."""

    ts: str  # ISO 날짜 (파티션 키로 쓴다)
    query: str
    n_results: int
    clicked: bool


def synthesize_catalog(
    n_docs: int,
    seed: int = 20260817,
    fan_ratio: float = 0.02,
    keep_original: bool = True,
) -> list[Document]:
    """원본 카탈로그를 유지한 채 합성 문서를 덧붙여 규모를 키운다.

    원본을 남기는 이유는 **실패 질의의 정답 문서가 거기 있기** 때문이다.
    원본을 빼면 평가셋이 통째로 무의미해지고, 그러면 규모 실험이 무엇을
    재는지 알 수 없다.
    """
    rng = random.Random(seed)
    docs: list[Document] = list(load_catalog()) if keep_original else []
    n_fan = int(max(0, n_docs) * fan_ratio)

    for i in range(max(0, n_docs)):
        idx = i + 1
        if i < n_fan:
            name_t, desc_t = _FAN_TEMPLATES[i % len(_FAN_TEMPLATES)]
            who = _WHO[i % len(_WHO)]
            n = rng.choice([12, 14, 16, 18])
            docs.append(
                Document(
                    doc_id=f"S{idx:07d}",
                    name=name_t.format(who=who, n=n),
                    description=desc_t.format(who=who, n=n),
                    category="생활",
                )
            )
            continue

        material = rng.choice(_MATERIALS)
        adjective = rng.choice(_ADJECTIVES)
        noun = rng.choice(_NOUNS)
        docs.append(
            Document(
                doc_id=f"S{idx:07d}",
                name=f"{adjective} {material} {noun}",
                description=(
                    f"{material} 소재의 {noun}. {adjective} 설계로 일상에서 쓰기 좋습니다."
                ),
                category=rng.choice(_CATEGORIES),
            )
        )
    return docs


def synthesize_query_log(
    n_rows: int,
    seed: int = 20260817,
    days: int = 7,
    failing_share: float = 0.12,
) -> list[QueryLogRow]:
    """검색 질의 로그를 만든다.

    실서비스 로그의 성질 두 가지를 흉내낸다:

    1. **롱테일** — 소수 질의가 대부분의 트래픽을 차지하고 꼬리가 길다.
       그래서 "제로결과 질의를 빈도순으로 골라야" 진료 대상 선정이 의미를
       가진다. 균등 분포라면 아무거나 골라도 같다.
    2. **제로결과가 소수** — 대부분의 질의는 잘 돈다. 그 안에서 실패를
       찾아내는 것이 로그 마이닝의 일이다.
    """
    from searchclinic.corpus import failing_queries, healthy_queries

    rng = random.Random(seed)
    failing = [q.query for q in failing_queries()]
    healthy = [q.query for q in healthy_queries()]
    noise = [f"{rng.choice(_ADJECTIVES)} {rng.choice(_NOUNS)}" for _ in range(200)]

    rows: list[QueryLogRow] = []
    for i in range(max(0, n_rows)):
        # 지프 분포에 가깝게: 앞쪽 질의가 훨씬 자주 나온다.
        roll = rng.random()
        if roll < failing_share:
            pool = failing
            zero = True
        elif roll < 0.75:
            pool = healthy
            zero = False
        else:
            pool = noise
            zero = rng.random() < 0.3

        rank = int(len(pool) * (rng.random() ** 2))  # 앞쪽에 몰리게
        query = pool[min(rank, len(pool) - 1)]
        n_results = 0 if zero else rng.randint(1, 40)
        rows.append(
            QueryLogRow(
                ts=f"2026-08-{10 + (i % max(1, days)):02d}",
                query=query,
                n_results=n_results,
                # 결과가 0이면 클릭도 없다 — 로그가 스스로 모순되면 안 된다.
                clicked=bool(n_results) and rng.random() < 0.35,
            )
        )
    return rows
