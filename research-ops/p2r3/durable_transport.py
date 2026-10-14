"""External transport observer; frozen source, prompts and response validation remain unchanged."""
import hashlib,json,os
from pathlib import Path
from time import perf_counter
from urllib.request import Request,build_opener,ProxyHandler,HTTPRedirectHandler
from urllib.error import HTTPError
class NoRedirect(HTTPRedirectHandler):
 def redirect_request(self,*args,**kwargs):raise PermissionError('redirect forbidden')
class DurableTransport:
 def __init__(self,out,checkpoint,open_http=None):
  self.out=Path(out);self.out.mkdir(parents=True,exist_ok=True)
  self.checkpoint=checkpoint
  self.open_http=open_http or build_opener(ProxyHandler(),NoRedirect()).open
 def __call__(self,payload,*,on_event=lambda state,**fields:None):
  key=os.environ.get('OPENAI_API_KEY')
  if not key:raise PermissionError('key unavailable')
  if payload.get('model')!='gpt-4.1-mini-2025-04-14':raise ValueError('model mismatch')
  request_hash=hashlib.sha256(json.dumps(payload,ensure_ascii=False,sort_keys=True,separators=(',',':'),allow_nan=False).encode()).hexdigest()
  raw_path=self.out/(request_hash+'.http-body.bin');meta_path=self.out/(request_hash+'.http-meta.json')
  if raw_path.exists() or meta_path.exists():raise FileExistsError('transport attempt already recorded')
  meta=dict(request_hash=request_hash,state='reserved',http_status=None,transport_latency_ms=None)
  def persist():meta_path.write_text(json.dumps(meta,sort_keys=True),encoding='utf-8')
  def capture(raw):
   # Authentication credentials are not research evidence, even if echoed by a server.
   redacted=False
   for name in ('OPENAI_API_KEY','GITHUB_TOKEN'):
    secret=os.environ.get(name)
    if secret and secret.encode() in raw:raw=raw.replace(secret.encode(),b'[REDACTED]');redacted=True
   with raw_path.open('xb') as f:f.write(raw)
   meta.update(raw_sha256=hashlib.sha256(raw).hexdigest(),credential_echo_redacted=redacted)
  on_event('transmission_attempted');meta['state']='transmission_reserved';persist()
  self.checkpoint() # Durable reservation acknowledgment BEFORE first possible paid byte.
  request=Request('https://api.openai.com/v1/chat/completions',method='POST',
   data=json.dumps(payload,ensure_ascii=False).encode(),
   headers={'Content-Type':'application/json','Authorization':'Bearer '+key})
  start=perf_counter()
  try:
   with self.open_http(request,timeout=60) as response:
    on_event('response_confirmed',http_status=response.status)
    meta.update(state='response_headers_confirmed',http_status=response.status)
    raw=response.read(2_000_001)
    capture(raw);meta.update(state='body_preserved',transport_latency_ms=(perf_counter()-start)*1000);persist()
   self.checkpoint() # Persist raw response before provider parsing/next request.
   if meta.get('credential_echo_redacted'):raise ValueError('credential echo refused before provider persistence')
   if response.status!=200 or len(raw)>2_000_000:raise ValueError('unsuccessful or oversized response')
   result=json.loads(raw.decode('utf-8'))
   if not isinstance(result,dict) or not isinstance(result.get('choices'),list) or len(result['choices'])!=1:
    raise ValueError('exactly one choice required')
   return result
  except HTTPError as exc:
   on_event('response_confirmed',http_status=exc.code)
   meta.update(state='http_error',http_status=exc.code,transport_latency_ms=(perf_counter()-start)*1000)
   try:capture(exc.read(2_000_001))
   finally:exc.close();persist()
   self.checkpoint()
   raise ValueError('HTTP response error; no retry') from None
  except Exception as exc:
   meta.update(error_type=type(exc).__name__,transport_latency_ms=(perf_counter()-start)*1000)
   if meta['state']=='transmission_reserved':meta['state']='outcome_unknown_after_attempt'
   persist()
   # Do not retry a failed checkpoint. Caller attempts final evidence save once.
   raise
