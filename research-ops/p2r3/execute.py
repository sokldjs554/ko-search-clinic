"""Run immutable p2r3 in private scratch; only the wrapper is new."""
import base64,hashlib,json,os,subprocess,sys
from pathlib import Path
from urllib.request import build_opener,ProxyHandler,HTTPRedirectHandler
import capsule

SOURCE='cd76f09cf647d1ee2691ed3fd3a217d4f4eb34de'
SOURCE_HASH='5b5584f4457447967d6df5dfe047b92d345e9e249de36202a92d22327b523138'
PLAN='135f26a43bb9dd1c9f942a6b446fb637783af55e79ea29b82a3ae499bbb14b6b'
FAMILY='p2r3-gpt-'+PLAN
CACHE_URL='https://openaipublic.blob.core.windows.net/encodings/o200k_base.tiktoken'
CACHE_SHA='446a9538cb6c348e3516120d7c08b09f57c36495e2acfffe59a5bf8b0cfb1a2d'

def read(p):return json.loads(Path(p).read_text(encoding='utf-8'))
def save(p,x):
 p=Path(p);p.parent.mkdir(parents=True,exist_ok=True)
 with p.open('x',encoding='utf-8') as f:json.dump(x,f,ensure_ascii=False,indent=2,allow_nan=False)
def verify_files(root,files):
 root=Path(root).resolve()
 for name,expected in files.items():
  p=(root/name).resolve()
  if not p.is_relative_to(root) or not p.is_file() or hashlib.sha256(p.read_bytes()).hexdigest()!=expected:
   raise ValueError('input manifest drift')
def compare_relocation(old,new):
 if {k:v for k,v in old.items() if k!='execution_root'}!={k:v for k,v in new.items() if k!='execution_root'}:
  raise ValueError('only execution_root may change')
def childenv(repo,base):
 env={k:v for k,v in os.environ.items() if k not in ('OPENAI_API_KEY','GITHUB_TOKEN') and not k.startswith('SEARCHCLINIC_PHASE2_')}
 env.update(PYTHONPATH=str(repo/'src'),PYTHONIOENCODING='utf-8',
  SEARCHCLINIC_PHASE2_PROTOCOL='artifacts/research/p2r3-20261013/protocol.json',
  SEARCHCLINIC_PHASE2_COMMIT='47e2085ce04c715e738ff8330b559f398dad9d3a',
  SEARCHCLINIC_PHASE2_PRIVATE_ROOT=str(base/'out/private'),TIKTOKEN_CACHE_DIR=str(base/'cache'),KSC_INPUT=str(base/'input'))
 return env

def command(argv,cwd,env,log):
 with Path(log).open('xb') as f:r=subprocess.run(argv,cwd=cwd,env=env,stdout=f,stderr=subprocess.STDOUT)
 if r.returncode:raise RuntimeError('private command failed; inspect encrypted log')

def source_test_env(env):
 return {k:v for k,v in env.items() if not k.startswith('SEARCHCLINIC_PHASE2_') and k!='KSC_INPUT'}

def prepare(base):
 base=Path(base);inp=base/'input';out=base/'out';out.mkdir(exist_ok=False)
 verify_files(inp,read(inp/'MANIFEST.json'))
 repo=base/'repo';env=childenv(repo,base)
 command(['git','-c','core.autocrlf=false','clone','--no-checkout',str(inp/'source.bundle'),str(repo)],base,env,out/'clone.log')
 command(['git','checkout','--detach',SOURCE],repo,env,out/'checkout.log')
 command([sys.executable,'-m','pip','install','-r',str(inp/'requirements.txt')],repo,env,out/'install.log')
 cache=base/'cache';cache.mkdir()
 class NoRedirect(HTTPRedirectHandler):
  def redirect_request(self,*a,**kw):raise PermissionError('cache redirect forbidden')
 with build_opener(ProxyHandler(),NoRedirect()).open(CACHE_URL,timeout=60) as response:data=response.read(20_000_001)
 if hashlib.sha256(data).hexdigest()!=CACHE_SHA:raise ValueError('official tokenizer hash mismatch')
 (cache/hashlib.sha1(CACHE_URL.encode()).hexdigest()).write_bytes(data)
 save(out/'cache-provenance.json',dict(url=CACHE_URL,sha256=CACHE_SHA,origin='official fixed URL',verified=True))
 command([sys.executable,'-m','pytest','-q','-rs','-o','addopts=','--junitxml='+str(out/'source-tests.xml')],repo,source_test_env(env),out/'source-tests.log')
 command([sys.executable,'-m','pytest',str(Path(__file__).parent/'tests'),'-q','-rs','--junitxml='+str(out/'runner-tests.xml')],repo,env,out/'runner-tests.log')
 baseline=inp/'original/generation/rules-preparation.json'
 command([sys.executable,'-m','searchclinic.research.phase2.dev_comparison','freeze','--bundle',str(baseline),'--out',str(out/'plan.json')],repo,env,out/'freeze.log')
 old=read(inp/'original/execution-plan.json');new=read(out/'plan.json')
 old_digest=hashlib.sha256(json.dumps(old['body'],ensure_ascii=False,sort_keys=True,separators=(',',':'),allow_nan=False).encode()).hexdigest()
 if old['plan_hash']!=PLAN or old_digest!=PLAN:raise ValueError('parent plan mismatch')
 compare_relocation(old['body'],new['body'])
 if new['body']['source_sha']!=SOURCE or new['body']['source_hash']!=SOURCE_HASH or new['body']['source_dirty']:
  raise ValueError('source provenance mismatch')
 template=read(inp/'authorization.json')
 if not template['approved'] or template['plan_hash']!=PLAN:raise PermissionError('original authorization absent')
 approval=dict(template,plan_hash=new['plan_hash'],experiment_hash=new['plan_hash'],
  execution_directory=str(Path(new['body']['execution_root'])/new['plan_hash']),
  approval_reference='User 2026-10-14: complete Actions private transfer and execute existing GPT7 under USD0.15; same requests, relocated runner path only.')
 save(out/'approval.json',approval)
 save(out/'execution-freeze.json',dict(parent_plan_hash=PLAN,plan_hash=new['plan_hash'],source_sha=SOURCE,source_hash=SOURCE_HASH,
  changes=['execution_root'],body_except_execution_root_identical=True,source_tests='passed',runner_tests='passed',
  orchestrator_hashes={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in Path(__file__).parent.glob('*.py')},
  generation_calls_before_execution=0,scope='synthetic_stress_development',independent_human_review=False))
 return env

class Checkpointer:
 def __init__(self,base,io,recipient,run_id,phase):
  self.base=Path(base);self.io=io;self.recipient=recipient;self.run_id=run_id;self.phase=phase;self.sequence=0
 def __call__(self):
  self.sequence+=1
  wire=capsule.seal(self.recipient,capsule.archive(self.base/'out'),('output:'+self.run_id).encode())
  prefix=f'transfer/{self.run_id}/checkpoint-{self.phase}-{self.sequence:03d}'
  chunks=[]
  for offset in range(0,len(wire),400_000):
   part=wire[offset:offset+400_000];name=prefix+f'-{len(chunks):03d}.b64'
   self.io.put_bytes(name,base64.b64encode(part),'research: preserve encrypted execution checkpoint')
   chunks.append(dict(path=name,sha256=hashlib.sha256(part).hexdigest()))
  self.io.put_bytes(prefix+'.json',json.dumps(dict(chunks=chunks,sha256=hashlib.sha256(wire).hexdigest())).encode(),'research: acknowledge complete encrypted checkpoint')

def generation(base):
 base=Path(base);repo=base/'repo';out=base/'out';inp=base/'input'
 sys.path.insert(0,str(repo/'src'))
 from github_io import GitHubIO
 from durable_transport import DurableTransport
 from searchclinic.research.phase2 import dev_comparison as dev,provider
 from searchclinic.research.phase2.worker import install_boundary
 # Trusted Python API/process guard, not an OS sandbox for adversarial code.
 install_boundary([inp/'original/data/evaluator-only',inp/'original/evaluation'])
 io=GitHubIO(os.environ['GITHUB_REPOSITORY'],os.environ['GITHUB_REF_NAME'],os.environ['GITHUB_TOKEN'],os.environ['GITHUB_RUN_ID'])
 cp=Checkpointer(base,io,bytes.fromhex(os.environ['KSC_RECIPIENT']),os.environ['GITHUB_RUN_ID'],'generation')
 class FrozenTransport:
  def __init__(self,*,network_authorized=False):
   if not network_authorized:raise PermissionError('transport not authorized')
  def __call__(self,payload,*,on_event):
   return DurableTransport(out/'raw-http',cp)(payload,on_event=on_event)
 provider.OpenAIHTTPTransport=FrozenTransport
 status=dev.run_plan(out/'plan.json',inp/'original/generation/rules-preparation.json',approval=read(out/'approval.json'))
 save(out/'generation-status.json',status);cp()
 if status['status']!='candidates_sealed':raise RuntimeError('generation halted; no automatic retry or evaluation')

def evaluate(base,env):
 base=Path(base);out=base/'out';inp=base/'input';repo=base/'repo'
 plan=read(out/'plan.json');run=Path(plan['body']['execution_root'])/plan['plan_hash']
 common=[sys.executable,'-m','searchclinic.research.phase2.dev_comparison','evaluate','--plan',str(out/'plan.json'),
  '--baseline',str(inp/'original/generation/rules-preparation.json'),'--run-dir',str(run),
  '--labels',str(inp/'original/data/evaluator-only/labels.json')]
 command(common+['--out',str(out/'evaluation.json')],repo,env,out/'evaluation.log')
 command(common+['--out',str(out/'evaluation-replay.json')],repo,env,out/'evaluation-replay.log')
 # Compare every scientific metric/decision. Measured runtime/PIDs vary on replay.
 def scientific(value):
  if isinstance(value,dict):return {k:scientific(v) for k,v in value.items() if k not in ('latency_ms','elapsed_ms','worker_pid','pid')}
  if isinstance(value,list):return [scientific(v) for v in value]
  return value
 a=scientific(read(out/'evaluation.json'));b=scientific(read(out/'evaluation-replay.json'))
 save(out/'replay-check.json',dict(scientific_content_equal=a==b,paid_regeneration_calls=0,
  comparison='All fields except measured latency/PID',stored_candidates_reused=True))
 if a!=b:raise ValueError('stored candidate evaluation replay differs')

if __name__=='__main__':
 try:
  if sys.argv[1]!='generate':raise ValueError('unsupported child mode')
  generation(Path(sys.argv[2]))
 except Exception as exc:
  print(json.dumps({'status':'stopped','error_type':type(exc).__name__}))
  raise SystemExit(1)
