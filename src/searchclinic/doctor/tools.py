"""진료 도구 — 의사가 증거를 수집하고 처방을 제출하는 유일한 통로.

핵심 설계: **검증이 도구 안에 있다.** submit_prescription은 처방을 받아
회귀 게이트를 돌리고, 통과해야만 현역 설정에 편입한다. 의사(LLM이든
휴리스틱이든)는 검증을 건너뛸 방법이 없다 — 채택 여부를 결정하는 것은
의사의 확신이 아니라 전수 재실행 결과다.

의사에게 qrels(정답표)는 보이지 않는다. 의사가 보는 것은 검색 결과,
원문 grep, 형태소 분석뿐이고, 채점은 게이트(시험관)만 한다.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field

from pydantic import ValidationError

from searchclinic.analysis.jamo import jamo_similarity
from searchclinic.analysis.vectors import CachedVectors
from searchclinic.corpus.evalset import EvalQuery
from searchclinic.index.engine import SearchEngine
from searchclinic.patch.gate import GateVerdict, run_gate
from searchclinic.patch.ir import Prescription

SUBMIT_TOOL = "submit_prescription"


def build_tool_definitions() -> list[dict]:
    return [
        {
            "name": "search_products",
            "description": (
                "현재 설정으로 상품을 검색한다. 실패 질의의 현재 상태(0건인지, "
                "엉뚱한 문서가 위에 있는지)를 확인할 때 가장 먼저 호출하라. "
                "각 결과에 어떤 토큰이 매칭됐는지(matched_terms)도 나온다."
            ),
            "input_schema": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "검색 질의"},
                    "k": {"type": "integer", "description": "최대 결과 수. 기본 10"},
                },
                "required": ["query"],
            },
        },
        {
            "name": "grep_documents",
            "description": (
                "분석기를 **우회**해서 원문 부분 문자열로 문서를 찾는다 (공백 무시). "
                "검색은 0건인데 grep에는 나온다면 문서가 없는 게 아니라 분석이 "
                "실패한 것이다 — 이 대조가 진단의 결정적 증거다. 질의 그대로, "
                "그리고 예상 표준 표기로도 grep해서 문서가 실제로 어떤 표기를 "
                "쓰는지 확인하라."
            ),
            "input_schema": {
                "type": "object",
                "properties": {
                    "text": {"type": "string", "description": "찾을 문자열"},
                },
                "required": ["text"],
            },
        },
        {
            "name": "analyze_text",
            "description": (
                "텍스트가 분석 파이프라인을 통과한 결과를 보여준다 (형태소 토큰, "
                "품사, 각 토큰이 나온 경로). 질의가 어떻게 쪼개지는지, 쓰레기 "
                "분해([아,답,터] 같은)가 있는지 확인할 때 호출하라. 문서 원문을 "
                "넣으면 색인 토큰도 볼 수 있다."
            ),
            "input_schema": {
                "type": "object",
                "properties": {
                    "text": {"type": "string", "description": "분석할 텍스트"},
                },
                "required": ["text"],
            },
        },
        {
            "name": "inspect_document",
            "description": (
                "문서 id의 원문(상품명·설명)과 색인 토큰을 보여준다. grep으로 찾은 "
                "문서가 실제로 어떤 토큰으로 색인됐는지 질의 토큰과 대조할 때 호출하라."
            ),
            "input_schema": {
                "type": "object",
                "properties": {
                    "doc_id": {"type": "string", "description": "문서 id (예: P001)"},
                },
                "required": ["doc_id"],
            },
        },
        {
            "name": "find_similar_tokens",
            "description": (
                "색인 어휘에서 주어진 단어와 자모(낱글자) 수준으로 비슷한 토큰을 "
                "찾는다. '케잌'의 표준 표기('케이크')처럼 표기 변형의 상대를 찾을 때 "
                "호출하라. 유사도는 참고일 뿐이며, 의미가 같은지는 직접 판단하라."
            ),
            "input_schema": {
                "type": "object",
                "properties": {
                    "term": {"type": "string", "description": "기준 단어"},
                    "k": {"type": "integer", "description": "반환 수. 기본 8"},
                },
                "required": ["term"],
            },
        },
        {
            "name": SUBMIT_TOOL,
            "description": (
                "진단과 처방을 제출한다. 제출 즉시 **회귀 게이트**가 전체 평가셋을 "
                "재실행해 (1) 표적 질의 개선 (2) 다른 질의 무회귀 (3) 전체 평균 보존을 "
                "검사하고, 전부 통과해야만 채택된다. 기각되면 어떤 질의가 어떻게 "
                "나빠졌는지 돌려주니, 처방을 좁혀 다시 제출하라. 처방은 최소여야 "
                "한다 — 넓은 동의어 묶음은 거의 확실히 회귀를 만든다."
            ),
            "input_schema": {
                "type": "object",
                "properties": {
                    "target_query": {"type": "string", "description": "치유하려는 실패 질의 (브리핑의 질의 그대로)"},
                    "diagnosis_family": {
                        "type": "string",
                        "description": (
                            "실패 계열: spelling_variant(표기 변형) | cross_script(영한 혼용) "
                            "| synonym_gap(유의어 단절) | compound_locked(복합어 통짜) "
                            "| garbage_split(쓰레기 분해)"
                        ),
                    },
                    "reasoning": {"type": "string", "description": "증거에 기반한 진단 근거 (grep/분석 결과 인용)"},
                    "user_words": {
                        "type": "array",
                        "description": "사용자 사전 등록 목록 (쓰레기 분해 교정)",
                        "items": {
                            "type": "object",
                            "properties": {
                                "form": {"type": "string"},
                                "tag": {"type": "string", "description": "기본 NNP"},
                            },
                            "required": ["form"],
                        },
                    },
                    "synonym_groups": {
                        "type": "array",
                        "description": "동의어 그룹 목록. 각 그룹의 첫 항목이 대표형(색인에 존재하는 표준형을 첫 번째로)",
                        "items": {
                            "type": "object",
                            "properties": {
                                "terms": {"type": "array", "items": {"type": "string"}},
                            },
                            "required": ["terms"],
                        },
                    },
                    "compound_expansions": {
                        "type": "array",
                        "description": "복합어 분해 확장 목록. parts를 이어 붙이면 word가 돼야 한다",
                        "items": {
                            "type": "object",
                            "properties": {
                                "word": {"type": "string"},
                                "parts": {"type": "array", "items": {"type": "string"}},
                            },
                            "required": ["word", "parts"],
                        },
                    },
                },
                "required": ["target_query", "diagnosis_family", "reasoning"],
            },
        },
    ]


def _dumps(obj) -> str:
    return json.dumps(obj, ensure_ascii=False, default=str)


@dataclass
class AcceptedRecord:
    """채택된 처방과 그 증거 — 원장(ledger)의 한 줄."""

    prescription: Prescription
    verdict: GateVerdict
    attempts: int


@dataclass
class ClinicExecutor:
    """도구 실행기. 채택된 처방이 누적되는 상태를 가진다."""

    engine: SearchEngine
    evalset: list[EvalQuery]
    # 임베딩 벡터를 주면 find_similar_tokens가 자모 유사도와 **나란히**
    # 의미 유사도를 함께 낸다. 자모를 대체하지 않는다 — 두 자를 같이
    # 보여줘야 의사가 "형태가 닮은 것"과 "뜻이 같은 것"을 구분할 수 있다.
    vectors: CachedVectors | None = None
    accepted: list[AcceptedRecord] = field(default_factory=list)
    _attempts_this_session: int = 0
    _session_query: str | None = None

    def start_session(self, query: str | None = None) -> None:
        """진료 세션을 연다. query를 주면 그 질의로 제출 대상을 못박는다."""
        self._attempts_this_session = 0
        self._session_query = query

    # ------------------------------------------------------------------ 실행

    def execute(self, name: str, tool_input: dict) -> tuple[str, bool]:
        """(결과 문자열, is_error). 마지막 제출 채택 여부는 별도 플래그로 노출."""
        try:
            handler = getattr(self, f"_tool_{name}", None)
            if handler is None:
                return f"알 수 없는 도구: {name}", True
            return _dumps(handler(**(tool_input or {}))), False
        except (ValidationError, ValueError) as e:
            return f"처방 스키마 오류: {e}", True
        except TypeError as e:
            return f"도구 인자 오류: {e}", True
        except Exception as e:
            return f"도구 실행 실패: {type(e).__name__}: {e}", True

    # ------------------------------------------------------------------ 도구들

    def _tool_search_products(self, query: str, k: int = 10) -> dict:
        hits = self.engine.search(query, k=max(1, int(k)))
        return {
            "query": query,
            "total": len(hits),
            "results": [
                {
                    "doc_id": h.doc_id,
                    "name": self.engine.docs[h.doc_id].name,
                    "score": h.score,
                    "matched_terms": h.matched_terms,
                }
                for h in hits
            ],
        }

    def _tool_grep_documents(self, text: str) -> dict:
        docs = self.engine.grep_raw(text)
        return {
            "needle": text,
            "total": len(docs),
            "documents": [
                {"doc_id": d.doc_id, "name": d.name, "description": d.description}
                for d in docs
            ],
        }

    def _tool_analyze_text(self, text: str) -> dict:
        return {"text": text, "tokens": self.engine.analyzer.explain(text)}

    def _tool_inspect_document(self, doc_id: str) -> dict:
        doc = self.engine.docs.get(doc_id)
        if doc is None:
            raise ValueError(f"존재하지 않는 문서: {doc_id}")
        return {
            "doc_id": doc.doc_id,
            "name": doc.name,
            "description": doc.description,
            "category": doc.category,
            "index_tokens": self.engine.doc_tokens(doc_id),
        }

    def _tool_find_similar_tokens(self, term: str, k: int = 8) -> dict:
        """색인 어휘에서 닮은 토큰을 찾는다 — 형태(자모)와 의미(벡터) 두 자로.

        정렬은 **둘 중 큰 값** 기준이다. 자모로만 정렬하면 '블루투스'에 대한
        'bluetooth'(자모 0.00)가 목록 끝으로 밀려 보이지 않는다.
        """
        vectors = self.vectors
        scored: list[dict] = []
        for tok in self.engine.vocabulary():
            if tok == term:
                continue
            row = {"token": tok, "similarity": round(jamo_similarity(term, tok), 3)}
            if vectors is not None:
                vsim = vectors.similarity(term, tok)
                # 캐시에 없는 단어는 키를 아예 넣지 않는다. 0.0으로 채우면
                # '뜻이 멀다'와 '모른다'가 구분되지 않는다.
                if vsim is not None:
                    row["vector_similarity"] = round(vsim, 3)
            scored.append(row)
        scored.sort(
            key=lambda x: (-max(x["similarity"], x.get("vector_similarity", 0.0)), x["token"])
        )
        payload = {"term": term, "similar": scored[: max(1, int(k))]}
        if vectors is not None and term not in vectors:
            payload["note"] = f"'{term}'은 벡터 사전에 없어 의미 유사도를 낼 수 없다."
        return payload

    def _tool_submit_prescription(self, **kwargs) -> dict:
        prescription = Prescription(**kwargs)

        # 진료 중인 질의가 아닌 다른 질의를 표적으로 삼은 제출은 거부한다.
        # 이게 없으면 의사가 표적을 바꿔 던진 처방이 채택되고, 세션은 그것을
        # "원래 질의를 치유했다"로 기록한다 — 평가가 통째로 무의미해진다.
        if self._session_query and prescription.target_query != self._session_query:
            raise ValueError(
                f"이 진료의 표적은 '{self._session_query}'인데 "
                f"'{prescription.target_query}'를 표적으로 제출했다. "
                f"target_query를 '{self._session_query}'로 정확히 맞춰 다시 제출하라."
            )

        self._attempts_this_session += 1
        verdict, sandbox = run_gate(self.engine, self.evalset, prescription)
        if verdict.accepted:
            # 채택: 샌드박스를 현역으로 승격 — 이후 진료는 누적 설정 위에서 돈다
            self.engine = sandbox
            self.accepted.append(
                AcceptedRecord(
                    prescription=prescription,
                    verdict=verdict,
                    attempts=self._attempts_this_session,
                )
            )
        return {
            "accepted": verdict.accepted,
            "feedback": verdict.feedback(),
            "target_ndcg_before": verdict.target_before.ndcg,
            "target_ndcg_after": verdict.target_after.ndcg,
            "prescription_summary": prescription.summary(),
        }
