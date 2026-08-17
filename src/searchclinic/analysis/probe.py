"""벡터 신호를 **채택하기 전에** 재는 자 — 가를 수 있기는 한가.

임계값을 정할 때 먼저 물어야 할 것은 "얼마로 할까"가 아니라 **"가르는
값이 존재하기는 하는가"**이다. 이 순서를 뒤집으면 임계값을 계속 만지면서
왜 안 되는지 모르는 상태에 빠진다 (실제로 그렇게 시작했다).

자모 임계값 0.65는 이 질문을 통과했다 — 케잌↔케이크 0.67이 최저 정답이고
그 아래에 쓰레기가 있다. 벡터는 통과하지 못했다. 이 모듈은 그 판정을
**명령 하나로 재현**하기 위해 있다.

## 세 가지를 잰다

1. **분리 가능성** — 이어야 하는 쌍과 이으면 안 되는 쌍의 유사도 분포가
   겹치는가. 겹치면 어떤 임계값도 소용없다.
2. **최적 임계값의 정확도** — 전 구간을 훑어 가장 잘 가르는 값을 찾고,
   그 값에서조차 몇 개를 틀리는지 본다.
3. **허브와 고립** — 각 토큰의 전체 평균 유사도. 짧은 한국어 토큰이
   허브가 되고 라틴 토큰이 고립되는 것이 1번의 원인이다.

쌍 목록은 손으로 골랐다. 자동 생성이 아니라 **평가셋의 실패 계열에서
직접 끌어온 것**이라, 이 목록에서 못 가르면 실제 진료에서도 못 가른다.
"""

from __future__ import annotations

from .vectors import CachedVectors

# 이어야 하는 쌍 — 평가셋 16개 실패 질의의 정답 연결.
LINK_PAIRS: list[tuple[str, str]] = [
    ("후라이팬", "프라이팬"),
    ("케잌", "케이크"),
    ("도너츠", "도넛"),
    ("카페트", "카펫"),
    ("핸드폰", "휴대폰"),
    ("블루투스", "bluetooth"),
    ("텀블러", "tumbler"),
    ("츄리닝", "트레이닝복"),
    ("아답터", "어댑터"),
    ("백팩", "배낭"),
]

# 이으면 안 되는 쌍 — 실제로 후보 목록 상위에 올라온 것들만 넣었다.
# 상상해서 만든 반례가 아니라 **의사가 실제로 봤던 유혹**이다.
NOLINK_PAIRS: list[tuple[str, str]] = [
    ("프라이팬", "팬"),
    ("선풍기", "팬"),
    ("백팩", "팩"),
    ("휴대폰", "스마트폰"),
    ("카페트", "방지"),
    ("티슈", "방지"),
    ("츄리닝", "접이식"),
    ("텀블러", "스피커"),
]


def score_pairs(
    vectors: CachedVectors, pairs: list[tuple[str, str]]
) -> list[tuple[str, str, float | None]]:
    """쌍마다 유사도. 캐시에 없는 단어가 끼면 None — 0.0으로 덮지 않는다."""
    return [(a, b, vectors.similarity(a, b)) for a, b in pairs]


def separability(
    link: list[tuple[str, str, float | None]],
    nolink: list[tuple[str, str, float | None]],
) -> dict:
    """두 분포가 가려지는지 판정한다.

    `clean_split`은 **정답 최저 > 쓰레기 최고**일 때만 참이다. 이때만
    "임계값을 잘 고르면 된다"는 말이 성립한다. 거짓이면 임계값 탐색은
    무의미하고, 신호 자체가 이 구분을 담고 있지 않다는 뜻이다.
    """
    ls = sorted(s for _, _, s in link if s is not None)
    ns = sorted(s for _, _, s in nolink if s is not None)
    if not ls or not ns:
        return {"clean_split": False, "reason": "캐시에 없는 토큰이 있어 판정 불가"}

    # 후보 임계값은 관측된 값들 사이. 각 값에서 정오답을 세어 최고를 고른다.
    # 동점이면 **높은 쪽**을 고른다(오름차순 순회 + `>=`). 정확도가 같다면
    # 쓰레기를 덜 들이는 쪽이 낫다 — 이 프로젝트에서 비싼 실수는 미치유가
    # 아니라 엉뚱한 동의어를 채택하는 것이다(`방지 = 카페트`).
    best_t, best_correct = 0.0, -1
    for t in sorted({*ls, *ns}):
        correct = sum(1 for s in ls if s >= t) + sum(1 for s in ns if s < t)
        if correct >= best_correct:
            best_t, best_correct = t, correct

    # 견줄 바닥선: 신호를 아예 안 보고 **전부 채택** 또는 **전부 기각**했을 때.
    # 최적 임계값이 이보다 낫지 않으면, 그 신호는 이 판단에 쓸 정보를
    # 담고 있지 않다는 뜻이다 — "임계값을 더 찾아보자"가 아니라 거기서 끝이다.
    total = len(ls) + len(ns)
    baseline = max(len(ls), len(ns))
    return {
        "clean_split": ls[0] > ns[-1],
        "baseline_correct": baseline,
        "beats_baseline": best_correct > baseline,
        "link_min": ls[0],
        "link_max": ls[-1],
        "nolink_min": ns[0],
        "nolink_max": ns[-1],
        "best_threshold": best_t,
        "best_correct": best_correct,
        "total": total,
        "best_accuracy": best_correct / total,
        # 겹침 구간 — 이 안에 정답과 쓰레기가 섞여 있다.
        "overlap_low": max(ls[0], ns[0]),
        "overlap_high": min(ls[-1], ns[-1]),
    }


def hub_scores(vectors: CachedVectors, tokens: list[str]) -> list[tuple[str, float]]:
    """각 토큰의 **전체 평균 유사도**. 높으면 허브(아무것과도 닮음),
    낮으면 고립(무엇과도 안 닮음). 둘 다 유사도를 못 쓰게 만든다."""
    known = [t for t in tokens if t in vectors]
    out: list[tuple[str, float]] = []
    for t in known:
        sims = [s for o in known if o != t and (s := vectors.similarity(t, o)) is not None]
        if sims:
            out.append((t, sum(sims) / len(sims)))
    out.sort(key=lambda x: (-x[1], x[0]))
    return out


# 벡터로 못 고친 질의어와 그 정답. 임계값이 아니라 **순위**가 문제라는
# 것을 보이려면, 정답이 후보 목록 몇 번째에 있는지를 봐야 한다.
UNHEALED: list[tuple[str, str]] = [
    ("블루투스", "bluetooth"),
    ("텀블러", "tumbler"),
    ("츄리닝", "트레이닝복"),
    ("아답터", "어댑터"),
    ("백팩", "배낭"),
]


def rank_of_answer(
    vectors: CachedVectors, term: str, answer: str, vocabulary: list[str]
) -> tuple[int | None, list[tuple[str, float]]]:
    """정답이 유사도 순위 몇 번째인지와 상위 목록.

    순위가 후보 절단선(k=8) 밖이면 임계값을 아무리 내려도 의사는 그
    후보를 **보지 못한다.** 임계값은 목록에 오른 것을 거르는 장치이지,
    목록에 없는 것을 불러오지 않는다.
    """
    ranked = vectors.most_similar(term, vocabulary, k=len(vocabulary))
    for i, (tok, _) in enumerate(ranked, start=1):
        if tok == answer:
            return i, ranked[:5]
    return None, ranked[:5]


def _fmt(s: float | None) -> str:
    return "캐시 없음" if s is None else f"{s:.3f}"


def render_probe_markdown(
    vectors: CachedVectors, vocabulary: list[str], top: int = 6
) -> str:
    """사람이 읽고 판단할 수 있는 형태로. 숫자만 던지면 결론이 안 남는다."""
    link = score_pairs(vectors, LINK_PAIRS)
    nolink = score_pairs(vectors, NOLINK_PAIRS)
    sep = separability(link, nolink)

    lines = [
        "### 벡터 신호 분리 검사",
        "",
        f"- 모델: `{vectors.model or '(미기록)'}`",
        f"- 캐시 토큰: {len(vectors)}개",
        "",
        "| 이어야 하는 쌍 | 유사도 | | 이으면 안 되는 쌍 | 유사도 |",
        "|---|---|---|---|---|",
    ]
    ls = sorted(link, key=lambda x: -(x[2] if x[2] is not None else -1))
    ns = sorted(nolink, key=lambda x: -(x[2] if x[2] is not None else -1))
    for i in range(max(len(ls), len(ns))):
        lcell = f"{ls[i][0]} ↔ {ls[i][1]} | {_fmt(ls[i][2])}" if i < len(ls) else " | "
        ncell = f"{ns[i][0]} ↔ {ns[i][1]} | {_fmt(ns[i][2])}" if i < len(ns) else " | "
        lines.append(f"| {lcell} | | {ncell} |")

    lines.append("")
    if sep.get("clean_split"):
        lines.append(
            f"**분리 가능.** 정답 최저 {sep['link_min']:.3f} > 쓰레기 최고 "
            f"{sep['nolink_max']:.3f} — 그 사이 어떤 값을 골라도 전부 맞는다."
        )
    elif "best_threshold" in sep:
        lines += [
            f"**분리 불가.** 정답이 {sep['link_min']:.3f}~{sep['link_max']:.3f}, "
            f"쓰레기가 {sep['nolink_min']:.3f}~{sep['nolink_max']:.3f}에 퍼져 "
            f"**{sep['overlap_low']:.3f}~{sep['overlap_high']:.3f} 구간에서 겹친다.**",
            "",
            f"가장 잘 가르는 임계값 {sep['best_threshold']:.3f}에서조차 "
            f"{sep['total']}쌍 중 {sep['total'] - sep['best_correct']}쌍이 틀린다 "
            f"(정확도 {sep['best_accuracy']:.0%}). 임계값을 바꿔서 해결되는 문제가 아니다.",
        ]
        if not sep["beats_baseline"]:
            lines += [
                "",
                f"게다가 이 정확도는 신호를 **아예 안 보고** 전부 채택(또는 전부 기각)했을 "
                f"때의 {sep['baseline_correct']}/{sep['total']}과 같거나 그보다 낮다. "
                "이 유사도는 두 쌍을 가르는 데 쓸 정보를 담고 있지 않다.",
            ]
    else:
        lines.append(f"**판정 불가** — {sep.get('reason', '')}")

    hubs = hub_scores(vectors, vocabulary)
    if hubs:
        lines += [
            "",
            f"### 허브와 고립 (어휘 {len(hubs)}개 기준 전체 평균 유사도)",
            "",
            "| 가장 높은 (허브) | 평균 | | 가장 낮은 (고립) | 평균 |",
            "|---|---|---|---|---|",
        ]
        for i in range(min(top, len(hubs) // 2)):
            h, hv = hubs[i]
            lo, lv = hubs[-(i + 1)]
            lines.append(f"| {h} | {hv:.3f} | | {lo} | {lv:.3f} |")
        lines += [
            "",
            "허브는 **무엇과 비교해도 높게** 나오고 고립은 **정답과 비교해도 낮게** "
            "나온다. 두 현상이 같은 축에 섞이면서 위의 겹침이 만들어진다.",
        ]

    lines += [
        "",
        "### 정답의 순위 — 임계값이 아니라 순위가 문제다",
        "",
        "| 질의어 | 정답 | 정답 순위 | 상위 후보 (유사도) |",
        "|---|---|---|---|",
    ]
    for term, answer in UNHEALED:
        if term not in vectors:
            lines.append(f"| {term} | {answer} | 캐시 없음 | — |")
            continue
        rank, head = rank_of_answer(vectors, term, answer, vocabulary)
        rank_txt = "어휘에 없음" if rank is None else f"{rank}위"
        if rank is not None and rank > 8:
            rank_txt = f"**{rank}위** (절단선 8 밖)"
        top = " · ".join(f"{t} {s:.3f}" for t, s in head[:3])
        lines.append(f"| {term} | {answer} | {rank_txt} | {top} |")
    lines += [
        "",
        "의사는 상위 8개만 본다. 정답이 그 밖이면 임계값을 0까지 내려도 "
        "**후보에 없으므로** 채택될 수 없다.",
    ]

    return "\n".join(lines)
