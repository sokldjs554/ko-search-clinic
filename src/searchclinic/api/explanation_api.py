"""Local workbench. Paid requests require explicit server setup and a local token."""
from __future__ import annotations
import hmac
import math
import os
import threading
import time
from collections import Counter, deque
from pathlib import Path
from fastapi import Header, HTTPException
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, field_validator
from searchclinic.api.rest import create_app
from searchclinic.rag.explanation_service import ExplanationService
from searchclinic.rag.openai_provider import Budget, OpenAIExplainer, ProviderError
from searchclinic.service import ClinicService

def latency_p95(values):
    """Nearest-rank percentile; retain the tail even for small samples."""
    values=sorted(values)
    return values[math.ceil(.95*len(values))-1] if values else None

class Request(BaseModel):
    query: str = Field(min_length=1,max_length=100)
    problem: str = Field(default='',max_length=500)
    @field_validator('query')
    @classmethod
    def strip_query(cls,value):
        if not value.strip(): raise ValueError('질의를 입력해 주세요.')
        return value.strip()

def create_explanation_app(*, provider=None, token: str | None=None):
    if provider is not None and (not token or len(token)<24):
        raise ValueError('Live mode requires a token of at least 24 characters')
    clinic=ClinicService()
    svc=ExplanationService(clinic,provider)
    app=create_app(clinic)
    lock=threading.Lock()
    stats_lock=threading.Lock()
    stats=Counter(requests=0,supported=0,abstain=0,invalid=0,upstream_errors=0,busy=0,gate_accepted=0,gate_rejected=0)
    latencies=deque(maxlen=100)

    def authorize(authorization):
        if provider is None: raise HTTPException(503,'실제 생성이 비활성화되어 있습니다.')
        if not authorization or not hmac.compare_digest(authorization,'Bearer '+token):
            raise HTTPException(401,'로컬 운영 토큰이 필요합니다.')

    @app.get('/explanation-status')
    def status():
        with stats_lock:
            values=sorted(latencies)
            return {'live_enabled':provider is not None,'metrics':dict(stats),
                    'latency_ms_p95':latency_p95(values),
                    'scope':'현재 프로세스 / 최근 100회, 고객 서비스 SLA 아님'}

    @app.post('/explanations')
    def explain(body:Request,authorization:str|None=Header(default=None)):
        authorize(authorization)
        if not lock.acquire(blocking=False):
            with stats_lock: stats['busy']+=1
            raise HTTPException(429,'이전 생성이 진행 중입니다. 잠시 뒤 다시 시도해 주세요.')
        started=time.monotonic()
        try:
            with stats_lock: stats['requests']+=1
            report=svc.explain(body.query,body.problem)
            with stats_lock: stats[report['answer']['status']]+=1
            return report
        except ProviderError as exc:
            with stats_lock: stats['upstream_errors']+=1
            raise HTTPException(502,str(exc)) from None
        finally:
            with stats_lock: latencies.append(round((time.monotonic()-started)*1000,1))
            lock.release()

    @app.post('/explanations/{report_id}/apply')
    def apply(report_id:str,authorization:str|None=Header(default=None)):
        authorize(authorization)
        report=svc.apply(report_id)
        # Count requests to gate endpoint, including idempotent repeated results.
        with stats_lock: stats['gate_accepted' if report['gate']['accepted'] else 'gate_rejected']+=1
        return report

    app.mount('/demo',StaticFiles(directory=Path(__file__).parents[1]/'web',html=True),name='demo')
    return app

def main():
    import uvicorn
    provider=None
    token=os.environ.get('CLINIC_LIVE_TOKEN')
    if os.environ.get('CLINIC_ENABLE_LIVE')=='1':
        provider=OpenAIExplainer(os.environ.get('OPENAI_API_KEY',''),
            budget=Budget(path=Path(os.environ.get('CLINIC_BUDGET_PATH','.clinic-budget.json'))))
    uvicorn.run(create_explanation_app(provider=provider,token=token),host='127.0.0.1',port=8000)

if __name__=='__main__': main()
