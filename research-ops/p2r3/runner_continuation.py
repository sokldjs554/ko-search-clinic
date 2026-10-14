"""Private transfer for six untouched requests, preserving the first failed attempt."""
import hashlib,json,os,shutil,sys,time
from pathlib import Path
import capsule,execute
from github_io import GitHubIO
from runner import receive

def main():
 os.umask(0o077)
 if os.environ['GITHUB_RUN_ATTEMPT']!='1':raise PermissionError('workflow reruns forbidden')
 run_id=os.environ['GITHUB_RUN_ID'];recipient=bytes.fromhex(os.environ['KSC_RECIPIENT'])
 base=Path(os.environ['RUNNER_TEMP'])/('p2r3-continuation-'+run_id);base.mkdir(exist_ok=False)
 io=GitHubIO(os.environ['GITHUB_REPOSITORY'],os.environ['GITHUB_REF_NAME'],os.environ['GITHUB_TOKEN'],run_id)
 private,public=capsule.keypair()
 io.put_bytes(f'transfer/{run_id}/ready.json',json.dumps(dict(run_id=run_id,workflow_sha=os.environ['GITHUB_SHA'],
  input_public_key=public.hex(),output_public_key=recipient.hex(),parent_calls=1,new_calls=0)).encode(),
  'research: publish ephemeral continuation input key')
 print('Waiting for encrypted immutable parent evidence and six-request amendment',flush=True)
 deadline=time.monotonic()+1800;manifest=None
 while time.monotonic()<deadline:
  manifest=io.get_json(f'transfer/{run_id}/input.json')
  if manifest is not None:break
  time.sleep(15)
 if manifest is None:raise TimeoutError('no input; no new calls')
 capsule.extract(receive(io,run_id,private,manifest),base/'input');del private
 error=None
 try:
  print('Running original full regression and continuation fault tests',flush=True)
  env=execute.prepare(base)
  cli=str(Path(__file__).parent/'continue_execute.py')
  execute.command([sys.executable,cli,'verify',str(base)],base/'repo',env,base/'out/amendment-verify.log')
  execute.Checkpointer(base,io,recipient,run_id,'verified')()
  print('Verified fixed requests and parent accounting; no failed request will be resent',flush=True)
  genenv=dict(env,OPENAI_API_KEY=os.environ['OPENAI_API_KEY'],GITHUB_TOKEN=os.environ['GITHUB_TOKEN'])
  execute.command([sys.executable,cli,'generate',str(base)],base/'repo',genenv,base/'out/generation.log')
  for mode in ('evaluate','replay'):
   execute.command([sys.executable,cli,mode,str(base)],base/'repo',env,base/'out'/(mode+'.log'))
  def science(x):
   if isinstance(x,dict):return {k:science(v) for k,v in x.items() if k not in ('latency_ms','elapsed_ms','worker_pid','pid')}
   if isinstance(x,list):return [science(v) for v in x]
   return x
  equal=science(execute.read(base/'out/evaluation.json'))==science(execute.read(base/'out/evaluation-replay.json'))
  execute.save(base/'out/replay-check.json',dict(scientific_content_equal=equal,paid_regeneration_calls=0,stored_candidates_reused=True))
  if not equal:raise ValueError('stored-candidate replay differs')
 except Exception as exc:error=type(exc).__name__
 finally:
  out=base/'out';out.mkdir(exist_ok=True)
  execute.save(out/'runner-status.json',dict(error_type=error,run_id=run_id,workflow_sha=os.environ['GITHUB_SHA'],automatic_retries=0))
  if (base/'cache').is_dir():shutil.copytree(base/'cache',out/'official-tokenizer-cache')
  wire=capsule.seal(recipient,capsule.archive(out),('output:'+run_id).encode())
  (Path(os.environ['RUNNER_TEMP'])/'p2r3-output.enc').write_bytes(wire)
  print(json.dumps(dict(status='stopped' if error else 'completed',error_type=error,encrypted_output_sha256=hashlib.sha256(wire).hexdigest())),flush=True)
 if error:raise SystemExit(1)

if __name__=='__main__':main()
