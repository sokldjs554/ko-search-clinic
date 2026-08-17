"""AnalyzerConfig → Elasticsearch(nori) 인덱스 설정 렌더링.

로컬 엔진은 Kiwi로 돌지만, 패치의 의미는 Elasticsearch nori 설정과 1:1로
대응하도록 설계했다. 채택된 설정을 이 모듈로 렌더링하면 실제 ES 클러스터에
그대로 넣을 수 있는 인덱스 설정 JSON이 나온다:

| 로컬 패치           | nori 대응물                                        |
|---------------------|----------------------------------------------------|
| UserWord            | user_dictionary_rules: "아답터"                    |
| CompoundExpansion   | user_dictionary_rules: "물티슈 물 티슈" (복합어 규칙)|
|                     | + decompound_mode: mixed (통짜·부분어 함께 색인)    |
| SynonymGroup        | synonym filter: "케잌 => 케이크" (명시적 매핑)      |
"""

from __future__ import annotations

import json

from searchclinic.analysis.config import AnalyzerConfig


def _needs_atomic_registration(term: str, decompounded: set[str]) -> bool:
    """이 동의어 표현을 nori 사전에 원자 토큰으로 등록해야 하는가.

    제외 대상:
    - 이미 분해 규칙이 걸린 말: 쪼개는 것이 의도다 (물티슈 → 물 티슈)
    - 공백이 든 말: 사전 규칙에서 공백은 '복합어 분해'를 뜻하므로 등록하면 안 된다
    - 한글이 없는 말: nori는 라틴 문자를 분해하지 않으므로 등록할 이유가 없다
    """
    if term in decompounded or " " in term:
        return False
    return any("가" <= ch <= "힣" for ch in term)


def to_es_settings(config: AnalyzerConfig, index_name: str = "products") -> dict:
    # nori 사용자 사전 규칙: 단일어는 "형태", 복합어는 "복합어 부분1 부분2 ..."
    user_rules: list[str] = [w.form for w in config.user_words]
    user_rules += [
        f"{c.word} {' '.join(c.parts)}" for c in config.compound_expansions
    ]

    # 동의어: 대표형으로의 명시적 매핑 (로컬 정규화 방식과 동일한 의미)
    synonyms: list[str] = []
    for g in config.synonym_groups:
        variants = [t for t in g.terms[1:]]
        if variants:
            synonyms.append(f"{', '.join(variants)} => {g.canonical}")

    # 동의어에 등장하는 표현은 사전에 원자 토큰으로 등록한다.
    #
    # 실측으로 확인된 실패 (ES 8.15가 인덱스 생성을 거부했다):
    #   term: 후라이팬 analyzed to a token (후라이) with position increment != 1
    #
    # decompound_mode: mixed는 '후라이팬'을 [후라이팬, 후라이, 팬]으로 **겹쳐서**
    # 내보내는데, 동의어 필터는 규칙 안의 표현이 겹치는 토큰으로 분석되면 그
    # 규칙을 만들 수 없다. Kiwi는 '후라이팬'을 한 토큰으로 두므로 이것은
    # 로컬과 nori의 동작 차이이기도 하다 — 사전 등록은 규칙을 유효하게 만드는
    # 동시에 **nori를 로컬과 같게 맞추는** 조치다.
    decompounded = {c.word for c in config.compound_expansions}
    already = set(user_rules)
    for g in config.synonym_groups:
        for term in g.terms:
            if term not in already and _needs_atomic_registration(term, decompounded):
                user_rules.append(term)
                already.add(term)

    tokenizer: dict = {
        "type": "nori_tokenizer",
        "decompound_mode": "mixed",  # CompoundExpansion의 통짜+부분어 색인과 대응
    }
    if user_rules:
        tokenizer["user_dictionary_rules"] = user_rules

    filters = ["lowercase", "nori_part_of_speech"]
    filter_defs: dict = {
        "nori_part_of_speech": {
            "type": "nori_part_of_speech",
            # 조사/어미/기호 제거 — 로컬 내용어 필터와 같은 취지
            "stoptags": ["J", "E", "IC", "MAG", "MAJ", "MM", "SP", "SSC",
                         "SSO", "SC", "SE", "XPN", "XSA", "XSN", "XSV",
                         "UNA", "NA", "VSV"],
        },
    }
    if synonyms:
        filters.append("clinic_synonyms")
        filter_defs["clinic_synonyms"] = {
            "type": "synonym_graph",
            "synonyms": synonyms,
        }

    return {
        "settings": {
            "index": {
                "analysis": {
                    "tokenizer": {"clinic_korean_tokenizer": tokenizer},
                    "filter": filter_defs,
                    "analyzer": {
                        "clinic_korean": {
                            "type": "custom",
                            "tokenizer": "clinic_korean_tokenizer",
                            "filter": filters,
                        }
                    },
                }
            }
        },
        "mappings": {
            "properties": {
                # copy_to로 name·description을 합친 text 필드를 하나 더 만든다.
                # 로컬 엔진은 Document.text(= name + " " + description)를 통짜로
                # 색인하므로, ES에서 필드를 나눠 검색하면 필드 길이 정규화가
                # 달라져 점수를 비교할 수 없다. 검증은 이 통합 필드로 한다.
                "name": {
                    "type": "text",
                    "analyzer": "clinic_korean",
                    "copy_to": "text",
                },
                "description": {
                    "type": "text",
                    "analyzer": "clinic_korean",
                    "copy_to": "text",
                },
                "text": {"type": "text", "analyzer": "clinic_korean"},
                "category": {"type": "keyword"},
            }
        },
        "_meta": {
            "index_name": index_name,
            "note": (
                "ko-search-clinic가 채택한 패치를 렌더링한 설정. "
                "user_dictionary_rules·synonym·decompound_mode가 로컬 패치와 1:1 대응한다."
            ),
        },
    }


def render_es_json(config: AnalyzerConfig, index_name: str = "products") -> str:
    return json.dumps(to_es_settings(config, index_name), ensure_ascii=False, indent=2)


def validate_es_settings(settings: dict) -> list[str]:
    """렌더된 설정을 ES에 보내기 전에 정적으로 검사한다.

    ES는 인덱스 생성 시점에야 이런 문제를 알려주고, 그러려면 클러스터가
    떠 있어야 한다. 클러스터 없이도 잡을 수 있는 것은 여기서 잡는다 —
    Docker가 필요한 검사는 CI에서 영영 안 돌기 때문이다.

    지금 검사하는 것은 실측으로 부딪힌 실패 하나다: 동의어 규칙에 등장하는
    한글 표현이 사전에 원자 토큰으로 등록돼 있지 않으면, decompound_mode가
    그 표현을 겹치는 토큰으로 쪼개 ES가 규칙 생성을 거부한다.
    """
    analysis = settings.get("settings", {}).get("index", {}).get("analysis", {})
    tokenizer = analysis.get("tokenizer", {}).get("clinic_korean_tokenizer", {})
    syn_filter = analysis.get("filter", {}).get("clinic_synonyms")
    if not syn_filter:
        return []
    if tokenizer.get("decompound_mode") == "none":
        return []  # 분해가 없으면 겹침도 없다

    rules = tokenizer.get("user_dictionary_rules", [])
    atomic = {r for r in rules if " " not in r}
    decompounded = {r.split()[0] for r in rules if " " in r}

    problems: list[str] = []
    for rule in syn_filter.get("synonyms", []):
        left, _, right = rule.partition("=>")
        terms = [t.strip() for t in left.split(",")] + [right.strip()]
        for term in terms:
            if not term or not _needs_atomic_registration(term, decompounded):
                continue
            if term not in atomic:
                problems.append(
                    f"동의어 '{rule.strip()}'의 '{term}'이 사전에 원자 토큰으로 "
                    f"등록돼 있지 않다 — nori가 분해하면 ES가 규칙 생성을 거부한다"
                )
    return problems
