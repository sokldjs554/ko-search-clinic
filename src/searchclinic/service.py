"""진료소를 프로세스 밖으로 여는 계층 — REST와 MCP가 **똑같이** 쓴다.

REST 라우트와 MCP 도구가 각자 `ClinicExecutor`를 직접 만지면 두 벌의
로직이 생기고, 그 둘은 반드시 갈라진다. 그래서 상태 관리와 표현 변환을
여기 한 곳에 모으고, 바깥 두 계층은 **얇은 결선**으로만 둔다.

이 파일은 fastapi도 mcp도 import하지 않는다. 두 선택 의존성이 없어도
계층 전체가 테스트되어야 하기 때문이다 — 설치돼야만 도는 테스트는 CI에서
영영 안 돌고, 안 도는 코드는 썩는다.

## 왜 세션인가 — 진료소는 본질적으로 상태를 가진다

`ClinicExecutor`는 처방이 채택될 때마다 **현역 설정을 갈아끼운다.** 이후
진료는 누적된 설정 위에서 돈다. 그래서 하나의 실행기를 여러 호출자가
공유하면 이런 일이 생긴다:

    A가 '후라이팬'을 고치는 동안 B가 '팬'을 동의어로 묶는다
    → A의 게이트가 "회귀 없음"이라 판정한 그 설정이 이미 B의 것이다
    → A가 본 적 없는 설정에 대해 무회귀를 보증한 셈이 된다

게이트의 보증은 **"이 설정 위에서 이 처방은 해롭지 않다"**이지 절대적인
것이 아니다. 그 전제를 지키려면 호출자마다 설정이 격리되어야 한다.
그래서 세션마다 독립된 실행기를 준다.

## 잠금이 필요한 이유

FastAPI는 `def`(비동기가 아닌) 핸들러를 **스레드풀**에서 돌린다. 같은
세션으로 두 요청이 동시에 들어오면 `execute()`가 겹쳐 돌고, 그 안에서
`self.engine`이 교체된다. 세션마다 락을 잡아 직렬화한다 — 진료는 원래
순차적인 절차이므로 병렬성을 잃는 손해가 없다.
"""

from __future__ import annotations

import threading
import uuid
from dataclasses import dataclass, field

from searchclinic.analysis.vectors import load_vectors_if_available
from searchclinic.corpus import load_catalog, load_evalset
from searchclinic.doctor import ClinicExecutor
from searchclinic.doctor.tools import build_tool_definitions
from searchclinic.index.engine import SearchEngine
from searchclinic.patch.es_render import to_es_settings, validate_es_settings

# 세션을 무한정 쌓아두면 프로세스가 메모리를 먹는다. 진료 하나가 코퍼스
# 72건짜리 색인 한 벌을 들고 있으므로, 상한을 두고 가장 오래된 것부터 버린다.
MAX_SESSIONS = 32


class SessionNotFound(KeyError):
    """없는 세션을 가리켰다. 바깥 계층이 404로 옮긴다."""


class UnknownTool(KeyError):
    """정의되지 않은 도구 이름. 바깥 계층이 404로 옮긴다."""


class ToolFailed(RuntimeError):
    """도구가 오류를 돌려줬다 (스키마 위반, 없는 문서 등). 바깥에서 400."""


@dataclass
class ClinicSession:
    session_id: str
    executor: ClinicExecutor
    label: str = ""
    lock: threading.Lock = field(default_factory=threading.Lock)


def _config_payload(cfg) -> dict:
    return {
        "user_words": [{"form": w.form, "tag": w.tag, "score": w.score} for w in cfg.user_words],
        "synonym_groups": [{"terms": list(g.terms)} for g in cfg.synonym_groups],
        "compound_expansions": [
            {"word": c.word, "parts": list(c.parts)} for c in cfg.compound_expansions
        ],
    }


def _ledger_payload(accepted) -> list[dict]:
    """채택된 처방과 **그 근거**를 함께 낸다.

    처방만 돌려주면 받는 쪽은 "왜 이게 채택됐는지"를 알 수 없다. 게이트가
    통과시켰다는 사실과 그때의 수치를 같이 실어야 사람이 다시 검토할 수 있다
    — 게이트는 '해롭지 않은가'만 보고 '말이 되는가'는 보지 않기 때문이다.
    """
    return [
        {
            "target_query": r.prescription.target_query,
            "diagnosis_family": r.prescription.diagnosis_family,
            "reasoning": r.prescription.reasoning,
            "summary": r.prescription.summary(),
            "attempts": r.attempts,
            "evidence": {
                "target_ndcg_before": r.verdict.target_before.ndcg,
                "target_ndcg_after": r.verdict.target_after.ndcg,
                "mean_ndcg_before": r.verdict.mean_before,
                "mean_ndcg_after": r.verdict.mean_after,
                "regressions": len(r.verdict.regressions),
            },
        }
        for r in accepted
    ]


class ClinicService:
    """세션 저장소 + 표현 변환. 바깥 계층은 이 객체 하나만 안다."""

    def __init__(self, max_sessions: int = MAX_SESSIONS) -> None:
        self._catalog = load_catalog()
        self._evalset = load_evalset()
        self._vectors = load_vectors_if_available()
        self._sessions: dict[str, ClinicSession] = {}
        self._sessions_lock = threading.Lock()
        self._max_sessions = max_sessions
        # 읽기 전용 질의에 쓰는 기준 색인. 패치가 닿지 않으므로 세션과
        # 무관하게 언제나 **치유 전 상태**를 답한다 — 비교 기준점이 필요하다.
        self._baseline = SearchEngine(self._catalog)

    # ------------------------------------------------------------ 읽기 전용

    def health(self) -> dict:
        return {
            "status": "ok",
            "documents": len(self._catalog),
            "eval_queries": len(self._evalset),
            "failing_queries": sum(1 for q in self._evalset if not q.is_healthy),
            "vectors_loaded": self._vectors is not None,
            "active_sessions": len(self._sessions),
        }

    def tool_definitions(self) -> list[dict]:
        """진료 도구 스키마. MCP가 그대로 노출하고, REST는 문서용으로 쓴다."""
        return build_tool_definitions()

    def evalset(self) -> dict:
        """평가셋을 정답표(qrels) **없이** 낸다.

        qrels는 채점자만 본다. API로 흘리면 호출자가 정답을 보고 처방을
        맞출 수 있고, 그러면 이 평가가 측정하는 것이 사라진다.
        """
        return {
            "total": len(self._evalset),
            "queries": [
                {
                    "query": q.query,
                    "family": q.family,
                    "is_healthy": q.is_healthy,
                    "expected_patch_kinds": list(q.expected_patch_kinds),
                }
                for q in self._evalset
            ],
        }

    def search(self, query: str, k: int = 10, session_id: str | None = None) -> dict:
        """세션을 주면 그 세션의 누적 설정으로, 안 주면 치유 전 기준으로 검색한다."""
        engine = self._engine_for(session_id)
        hits = engine.search(query, k=max(1, int(k)))
        return {
            "query": query,
            "session_id": session_id,
            "total": len(hits),
            "results": [
                {
                    "doc_id": h.doc_id,
                    "name": engine.docs[h.doc_id].name,
                    "score": h.score,
                    "matched_terms": list(h.matched_terms),
                }
                for h in hits
            ],
        }

    def analyze(self, text: str, session_id: str | None = None) -> dict:
        """형태소 분석 결과 + **버려진 토큰**.

        버려진 토큰을 같이 내는 이유: `아답터`가 `[답, 터]`로 보이는 것만으로는
        원인을 알 수 없다. `아`가 감탄사(IC)로 오인돼 내용어 필터에서 사라진
        것을 봐야 사전 등록이 필요하다는 결론이 나온다.
        """
        analyzer = self._engine_for(session_id).analyzer
        return {
            "text": text,
            "session_id": session_id,
            "tokens": analyzer.explain(text),
            "dropped": [{"token": t, "tag": tag} for t, tag in analyzer.dropped(text)],
        }

    def evaluate(self, session_id: str | None = None) -> dict:
        """평가셋 전체 채점. 세션을 주면 누적 패치가 적용된 상태로 잰다.

        전체 평균과 함께 **실패셋·건강셋을 갈라서** 낸다. 전체 평균 하나만
        보면 실패 질의를 고치면서 건강 질의를 망가뜨린 경우가 상쇄돼 보이지
        않는다 — 이 프로젝트가 회귀 게이트를 두는 이유와 같은 이유다.
        """
        from searchclinic.evaluation.metrics import (
            evaluate_all,
            mean_ndcg,
            zero_result_rate,
        )

        engine = self._engine_for(session_id)
        metrics = evaluate_all(engine, self._evalset)
        failing = {q.query: metrics[q.query] for q in self._evalset if not q.is_healthy}
        healthy = {q.query: metrics[q.query] for q in self._evalset if q.is_healthy}
        family_of = {q.query: q.family for q in self._evalset}
        healthy_of = {q.query: q.is_healthy for q in self._evalset}

        return {
            "session_id": session_id,
            "mean_ndcg": mean_ndcg(metrics),
            "failing_mean_ndcg": mean_ndcg(failing),
            "healthy_mean_ndcg": mean_ndcg(healthy),
            "zero_result_rate": zero_result_rate(metrics),
            "failing_zero_result_rate": zero_result_rate(failing),
            "queries": [
                {
                    "query": m.query,
                    "family": family_of[m.query],
                    "is_healthy": healthy_of[m.query],
                    "ndcg": m.ndcg,
                    "recall": m.recall,
                    "precision5": m.precision5,
                    "n_results": m.n_results,
                }
                for m in metrics.values()
            ],
        }

    # -------------------------------------------------------------- 세션

    def create_session(self, label: str = "") -> dict:
        session_id = uuid.uuid4().hex[:12]
        session = ClinicSession(
            session_id=session_id,
            executor=ClinicExecutor(
                engine=SearchEngine(self._catalog),
                evalset=self._evalset,
                vectors=self._vectors,
            ),
            label=label,
        )
        with self._sessions_lock:
            # 상한을 넘으면 가장 오래된 것부터 버린다 (dict는 삽입 순서를 지킨다).
            while len(self._sessions) >= self._max_sessions:
                self._sessions.pop(next(iter(self._sessions)))
            self._sessions[session_id] = session
        return self.describe_session(session_id)

    def describe_session(self, session_id: str) -> dict:
        session = self._session(session_id)
        return {
            "session_id": session.session_id,
            "label": session.label,
            "accepted_count": len(session.executor.accepted),
            "config": _config_payload(session.executor.engine.config),
            "ledger": _ledger_payload(session.executor.accepted),
        }

    def list_sessions(self) -> dict:
        with self._sessions_lock:
            items = [
                {
                    "session_id": s.session_id,
                    "label": s.label,
                    "accepted_count": len(s.executor.accepted),
                }
                for s in self._sessions.values()
            ]
        return {"total": len(items), "sessions": items}

    def delete_session(self, session_id: str) -> dict:
        with self._sessions_lock:
            if session_id not in self._sessions:
                raise SessionNotFound(session_id)
            del self._sessions[session_id]
        return {"deleted": session_id}

    def elasticsearch_settings(self, session_id: str, index_name: str = "products") -> dict:
        """세션의 누적 설정을 ES nori 설정으로 렌더링한다.

        치유 결과를 실제로 **쓸 수 있는 형태**로 내보내는 자리다. 이것이
        없으면 진료소는 점수만 올리고 끝난다.

        정적 검증 결과를 `problems`에 함께 싣는다. 빈 배열이어야 정상이며,
        비어 있지 않으면 그 설정은 ES가 인덱스 생성을 **거부**한다 (실측:
        `후라이팬`이 `후라이`로 분해돼 synonym_graph 규약을 위반했다).
        보내고 나서 500을 받는 것보다 보내기 전에 아는 편이 낫다.
        """
        session = self._session(session_id)
        settings = to_es_settings(session.executor.engine.config, index_name)
        return {
            "session_id": session_id,
            "index_name": index_name,
            "problems": validate_es_settings(settings),
            "settings": settings,
        }

    # ---------------------------------------------------------- 도구 호출

    def call_tool(self, session_id: str, name: str, tool_input: dict | None = None) -> dict:
        """도구 하나를 실행한다. MCP 도구 호출과 REST가 공유하는 단일 통로.

        `submit_prescription`은 여기서도 **게이트를 거친다.** 프로토콜을
        바꿔도 검증을 우회할 수 없다는 것이 이 설계의 요점이다.
        """
        import json

        session = self._session(session_id)
        if not any(t["name"] == name for t in build_tool_definitions()):
            raise UnknownTool(name)

        with session.lock:
            payload, is_error = session.executor.execute(name, tool_input or {})
        if is_error:
            raise ToolFailed(payload)
        return json.loads(payload)

    def submit_prescription(self, session_id: str, prescription: dict) -> dict:
        """처방 제출 — 게이트 판정과 그 근거를 함께 돌려준다."""
        result = self.call_tool(session_id, "submit_prescription", prescription)
        session = self._session(session_id)
        result["accepted_count"] = len(session.executor.accepted)
        return result

    def open_query(self, session_id: str, query: str) -> dict:
        """진료 표적을 못박는다.

        표적을 고정하지 않으면 다른 질의를 표적으로 던진 처방이 채택되고,
        기록에는 원래 질의를 치유한 것으로 남는다 (실측으로 겪은 실패다).
        """
        session = self._session(session_id)
        if not any(q.query == query for q in self._evalset):
            raise ToolFailed(
                f"평가셋에 없는 질의: '{query}'. 채점할 정답이 없으므로 진료할 수 없다."
            )
        with session.lock:
            session.executor.start_session(query)
        n = session.executor.engine.search(query, k=10)
        return {"session_id": session_id, "target_query": query, "current_results": len(n)}

    # --------------------------------------------------------------- 내부

    def _session(self, session_id: str) -> ClinicSession:
        with self._sessions_lock:
            session = self._sessions.get(session_id)
        if session is None:
            raise SessionNotFound(session_id)
        return session

    def _engine_for(self, session_id: str | None) -> SearchEngine:
        return self._baseline if session_id is None else self._session(session_id).executor.engine
