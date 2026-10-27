"""Evidence-backed diagnosis and explicitly requested, isolated gate application."""
from __future__ import annotations
import copy
import hashlib
import json
import threading
import uuid
from collections import OrderedDict
from datetime import datetime, timezone
from searchclinic.rag.explanation import validate_explanation
from searchclinic.rag.knowledge import KnowledgeDoc
from searchclinic.rag.retriever import KnowledgeRetriever
from searchclinic.service import ClinicService, ToolFailed

class ExplanationService:
    def __init__(self, clinic: ClinicService, provider=None, retriever=None):
        self.clinic=clinic
        self.provider=provider
        self.retriever=retriever or KnowledgeRetriever(mode='bm25')
        self._reports=OrderedDict()
        self._lock=threading.RLock()

    def context(self, query: str, problem: str) -> tuple[dict,list[KnowledgeDoc]]:
        if not query.strip() or len(query)>100 or len(problem)>500:
            raise ToolFailed('질의는 1~100자, 관찰 내용은 500자 이하입니다.')
        # Labels/families/qrels are intentionally absent from the context.
        hits=self.retriever.retrieve(query+' '+problem,k=3)
        docs=[KnowledgeDoc(h.doc.doc_id,h.doc.title,h.doc.body[:400],h.doc.source) for h in hits]
        context={'query':query,'problem':problem,
            'analysis':self.clinic.analyze(query), 'search':self.clinic.search(query,k=3),
            'documents':[{'id':d.doc_id,'title':d.title,'body':d.body,'source':d.source} for d in docs]}
        return context,docs

    def explain(self, query: str, problem: str) -> dict:
        from searchclinic.rag.openai_provider import ProviderError
        if self.provider is None:
            raise ProviderError('provider_not_configured')
        context,docs=self.context(query,problem)
        generated=self.provider.generate(context)
        answer=validate_explanation(generated['raw'],docs,query)
        report={'id':uuid.uuid4().hex,'mode':'live','created_at':datetime.now(timezone.utc).isoformat(),
            'context':context,'context_sha256':hashlib.sha256(json.dumps(context,ensure_ascii=False,sort_keys=True).encode()).hexdigest(),
            'answer':answer,'generation':generated,'gate':None,'session_id':None}
        with self._lock:
            self._reports[report['id']]=report
            while len(self._reports)>64:
                self._reports.popitem(last=False)
        return copy.deepcopy(report)

    def apply(self, report_id: str) -> dict:
        with self._lock:
            if report_id not in self._reports:
                raise ToolFailed('저장된 진단이 없거나 만료됐습니다.')
            report=self._reports[report_id]
            if report['gate'] is not None:
                return copy.deepcopy(report)
            rx=report['answer']['prescription']
            if not rx:
                raise ToolFailed('검증 가능한 수정 후보가 없습니다.')
            query=report['context']['query']
            sid=self.clinic.create_session(label='RAG '+report_id)['session_id']
            try:
                self.clinic.open_query(sid,query)
                gate=self.clinic.submit_prescription(sid,rx)
            except Exception:
                self.clinic.delete_session(sid)
                raise
            report.update(gate=gate,session_id=sid)
            return copy.deepcopy(report)
