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
                "name": {"type": "text", "analyzer": "clinic_korean"},
                "description": {"type": "text", "analyzer": "clinic_korean"},
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
