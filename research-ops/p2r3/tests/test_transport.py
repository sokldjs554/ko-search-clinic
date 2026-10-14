import importlib.util,io,json,os,sys,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
from urllib.error import HTTPError,URLError
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
class Response:
 status=200
 def __init__(self,body):self.body=body
 def __enter__(self):return self
 def __exit__(self,*a):pass
 def read(self,n):return self.body
class TransportTests(unittest.TestCase):
 def module(self):
  self.assertIsNotNone(importlib.util.find_spec('durable_transport'),'transport missing')
  import durable_transport
  return durable_transport
 def invoke(self,body=None,checkpoint=lambda:None,exception=None):
  m=self.module();calls=[];events=[]
  def open(req,timeout):
   calls.append(req)
   if exception:raise exception
   return Response(body)
  with tempfile.TemporaryDirectory() as d,patch.dict(os.environ,{'OPENAI_API_KEY':'fixture-hidden-key'}):
   t=m.DurableTransport(Path(d),checkpoint,open)
   try:result=t({'model':'gpt-4.1-mini-2025-04-14','x':'private-query'},on_event=lambda e,**f:events.append(e));error=None
   except Exception as exc:result=None;error=exc
   files={p.name:p.read_bytes() for p in Path(d).iterdir()}
  return result,error,calls,events,files
 def test_checkpoint_failure_prevents_generation(self):
  def fail():raise RuntimeError('storage failed')
  _,error,calls,_,_=self.invoke(checkpoint=fail)
  self.assertIsNotNone(error);self.assertEqual(calls,[])
 def test_exact_invalid_json_body_retained_and_no_retry(self):
  raw=b'not JSON private response'
  _,error,calls,events,files=self.invoke(body=raw)
  self.assertIsNotNone(error);self.assertEqual(len(calls),1)
  self.assertIn(raw,files.values());self.assertIn('response_confirmed',events)
 def test_model_response_returned_only_after_checkpoint(self):
  order=[];raw=b'{"choices":[{}],"usage":{"prompt_tokens":3,"completion_tokens":4}}'
  result,error,calls,events,files=self.invoke(body=raw,checkpoint=lambda:order.append('checkpoint'))
  self.assertIsNone(error);self.assertEqual(len(calls),1);self.assertGreaterEqual(len(order),2)
  self.assertIn(raw,files.values());self.assertEqual(result['usage']['prompt_tokens'],3)
  self.assertEqual(calls[0].get_method(),'POST')
  self.assertEqual(calls[0].full_url,'https://api.openai.com/v1/chat/completions')
 def test_multiple_choices_halt_before_provider(self):
  _,error,calls,_,files=self.invoke(body=b'{"choices":[{},{}]}')
  self.assertIsNotNone(error);self.assertEqual(len(calls),1)
 def test_timeout_no_retry(self):
  _,error,calls,events,files=self.invoke(exception=TimeoutError('private detail'))
  self.assertIsNotNone(error);self.assertEqual(len(calls),1);self.assertIn('transmission_attempted',events)
 def test_http_failure_body_retained(self):
  e=HTTPError('url',429,'private',{},io.BytesIO(b'quota-body'))
  _,error,calls,_,files=self.invoke(exception=e)
  self.assertIsNotNone(error);self.assertEqual(len(calls),1);self.assertIn(b'quota-body',files.values())
 def test_credential_echo_never_returns_to_provider_or_persisted_bytes(self):
  raw=json.dumps({'choices':[{'message':{'content':'fixture-hidden-key'}}],'usage':{'prompt_tokens':3,'completion_tokens':4}}).encode()
  result,error,calls,events,files=self.invoke(body=raw)
  self.assertIsNone(result);self.assertIsNotNone(error);self.assertEqual(len(calls),1)
  self.assertTrue(any(b'[REDACTED]' in value for value in files.values()))
  self.assertTrue(all(b'fixture-hidden-key' not in value for value in files.values()))
if __name__=='__main__':unittest.main()
