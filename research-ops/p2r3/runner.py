"""Private Actions rendezvous and one-shot execution. Public logs contain status only."""
import base64,hashlib,json,os,shutil,sys,time
from pathlib import Path
import capsule,execute
from github_io import GitHubIO

def receive(io,run_id,private,manifest):
 if manifest.get('run_id')!=run_id or not 1<=len(manifest['chunks'])<=200:raise ValueError('input manifest invalid')
 parts=[]
 for item in manifest['chunks']:
  name=item['name']
  if not name.startswith('chunk-') or '/' in name:raise ValueError('chunk path invalid')
  encoded=io.get_bytes(f'transfer/{run_id}/{name}')
  data=base64.b64decode(encoded,validate=True)
  if hashlib.sha256(data).hexdigest()!=item['sha256']:raise ValueError('chunk hash mismatch')
  parts.append(data)
 wire=b''.join(parts)
 if len(wire)>20_000_000 or hashlib.sha256(wire).hexdigest()!=manifest['sha256']:raise ValueError('envelope mismatch')
 return capsule.unseal(private,wire,('input:'+run_id).encode())

def main():
 os.umask(0o077)
 if os.environ['GITHUB_RUN_ATTEMPT']!='1':raise PermissionError('workflow reruns forbidden')
 run_id=os.environ['GITHUB_RUN_ID'];recipient=bytes.fromhex(os.environ['KSC_RECIPIENT'])
 base=Path(os.environ['RUNNER_TEMP'])/('p2r3-'+run_id);base.mkdir(exist_ok=False)
 io=GitHubIO(os.environ['GITHUB_REPOSITORY'],os.environ['GITHUB_REF_NAME'],os.environ['GITHUB_TOKEN'],run_id)
 private,public=capsule.keypair()
 ready=dict(run_id=run_id,workflow_sha=os.environ['GITHUB_SHA'],input_public_key=public.hex(),output_public_key=recipient.hex(),generation_calls=0)
 io.put_bytes(f'transfer/{run_id}/ready.json',json.dumps(ready).encode(),'research: publish ephemeral input encryption key')
 print('Waiting for authenticated encrypted research input',flush=True)
 deadline=time.monotonic()+1800;manifest=None
 while time.monotonic()<deadline:
  manifest=io.get_json(f'transfer/{run_id}/input.json')
  if manifest is not None:break
  time.sleep(15)
 if manifest is None:raise TimeoutError('no input received; zero calls')
 capsule.extract(receive(io,run_id,private,manifest),base/'input')
 del private
 error=None;claimed=False
 try:
  print('Validating frozen source, cache, requests and all offline tests',flush=True)
  env=execute.prepare(base)
  io.claim(execute.FAMILY,os.environ['GITHUB_SHA']);claimed=True
  execute.save(base/'out/global-claim.json',dict(family=execute.FAMILY,workflow_sha=os.environ['GITHUB_SHA'],run_id=run_id,claim_acknowledged=True))
  execute.Checkpointer(base,io,recipient,run_id,'ready')()
  print('Validated; executing the authorized batch once',flush=True)
  genenv=dict(env,OPENAI_API_KEY=os.environ['OPENAI_API_KEY'],GITHUB_TOKEN=os.environ['GITHUB_TOKEN'])
  execute.command([sys.executable,str(Path(__file__).parent/'execute.py'),'generate',str(base)],base/'repo',genenv,base/'out/generation.log')
  print('All candidates sealed; evaluating saved candidates twice',flush=True)
  execute.evaluate(base,env)
 except Exception as exc:
  error=type(exc).__name__
 finally:
  out=base/'out';out.mkdir(exist_ok=True)
  execute.save(out/'runner-status.json',dict(error_type=error,global_claim=claimed,run_id=run_id,workflow_sha=os.environ['GITHUB_SHA'],automatic_retries=0))
  # Keep the official cache for local full regression without another download.
  if (base/'cache').is_dir():shutil.copytree(base/'cache',out/'official-tokenizer-cache')
  wire=capsule.seal(recipient,capsule.archive(out),('output:'+run_id).encode())
  final=Path(os.environ['RUNNER_TEMP'])/'p2r3-output.enc';final.write_bytes(wire)
  print(json.dumps(dict(status='stopped' if error else 'completed',error_type=error,encrypted_output_sha256=hashlib.sha256(wire).hexdigest())),flush=True)
 if error:raise SystemExit(1)

if __name__=='__main__':main()
