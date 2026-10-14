"""Process entry points for the declared posthoc development amendment."""
import json,os,sys
from pathlib import Path
import execute

def paths(base):
 inp=Path(base)/'input'
 return (inp/'original/execution-plan.json',inp/'parent',inp/'parent-artifact.zip',inp/'original/generation/rules-preparation.json')

def main(mode,base):
 base=Path(base);sys.path.insert(0,str(base/'repo/src'))
 import continuation
 inp=base/'input';out=base/'out';amendment=inp/'amendment.json';evidence=paths(base)
 continuation.verify_amendment(amendment,*evidence)
 if mode=='verify':return
 if mode=='generate':
  from github_io import GitHubIO
  from durable_transport import DurableTransport
  from searchclinic.research.phase2 import provider
  from searchclinic.research.phase2.worker import install_boundary
  install_boundary([inp/'original/data/evaluator-only',inp/'original/evaluation'])
  io=GitHubIO(os.environ['GITHUB_REPOSITORY'],os.environ['GITHUB_REF_NAME'],os.environ['GITHUB_TOKEN'],os.environ['GITHUB_RUN_ID'])
  cp=execute.Checkpointer(base,io,bytes.fromhex(os.environ['KSC_RECIPIENT']),os.environ['GITHUB_RUN_ID'],'continuation')
  class FrozenTransport:
   def __init__(self,*,network_authorized=False):
    if not network_authorized:raise PermissionError('transport not authorized')
   def __call__(self,payload,*,on_event):
    return DurableTransport(out/'continuation/raw-http',cp)(payload,on_event=on_event)
  provider.OpenAIHTTPTransport=FrozenTransport
  def claim(family):
   parent=io._request('GET','git/ref/tags/research-lock/'+execute.FAMILY)
   if parent.get('object',{}).get('sha')!=continuation.PARENT_WORKFLOW:
    raise PermissionError('original permanent claim differs')
   io.claim(family,os.environ['GITHUB_SHA'])
   execute.save(out/'continuation-global-claim.json',dict(family=family,parent_family=execute.FAMILY,
    parent_workflow_sha=continuation.PARENT_WORKFLOW,workflow_sha=os.environ['GITHUB_SHA'],run_id=os.environ['GITHUB_RUN_ID']))
  status=continuation.run_continuation(amendment,*evidence,out/'continuation',claim_callback=claim,checkpoint=cp)
  execute.save(out/'generation-status.json',status)
  if status['status']!='candidates_sealed':raise RuntimeError('continuation stopped; no retry')
 elif mode in ('evaluate','replay'):
  continuation.evaluate_continuation(amendment,*evidence,out/'continuation',inp/'original/data/evaluator-only/labels.json',
   out/('evaluation.json' if mode=='evaluate' else 'evaluation-replay.json'))
 else:raise ValueError('unsupported mode')

if __name__=='__main__':
 try:main(sys.argv[1],Path(sys.argv[2]))
 except Exception as exc:
  print(json.dumps(dict(status='stopped',error_type=type(exc).__name__)))
  raise SystemExit(1)
