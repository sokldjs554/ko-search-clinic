"""Draft rendezvous for a pre-provisioned, frozen runtime. Not deployed.

Run only from the workflow SHA recorded in the final plan. Labels/review records
must never be placed on this worker. Final evaluation happens after decryption
on the separate, credential-free evaluator host.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import time

from independent_v3.actions_entry import receive, launch_spec
from independent_v2.vendor import capsule
from independent_v2.vendor.github_io import GitHubIO, _blob_sha


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--approval-reference',required=True)
    parser.add_argument('--protected-root',action='append',required=True)
    args=parser.parse_args()
    os.umask(0o077)
    if os.environ['GITHUB_RUN_ATTEMPT']!='1':
        raise ValueError('workflow reruns forbidden')
    run_id=os.environ['GITHUB_RUN_ID']
    base=Path(os.environ['RUNNER_TEMP'])/('final-transfer-'+run_id)
    base.mkdir(exist_ok=False)
    recipient=bytes.fromhex(os.environ['KSC_RECIPIENT'])
    io=GitHubIO(os.environ['GITHUB_REPOSITORY'],os.environ['GITHUB_REF_NAME'],os.environ['GITHUB_TOKEN'],run_id)
    private,public=capsule.keypair()
    ready=json.dumps(dict(run_id=run_id,workflow_sha=os.environ['GITHUB_SHA'],input_public_key=public.hex(),
                          output_public_key=recipient.hex(),generation_calls=0)).encode()
    if io.put_bytes(f'transfer/{run_id}/ready.json',ready,'research: final private input key')!=_blob_sha(ready):
        raise ValueError('ready acknowledgment mismatch')
    # GET polling only waits for initial input. Writes/model requests are never retried.
    deadline=time.monotonic()+1800
    manifest=None
    while time.monotonic()<deadline:
        manifest=io.get_json(f'transfer/{run_id}/input.json')
        if manifest is not None:break
        time.sleep(15)
    if manifest is None:raise TimeoutError('no input; zero model calls')
    capsule.extract(receive(io,run_id,private,manifest),base/'input')
    del private
    command=launch_spec(base/'input',approval_reference=args.approval_reference,protected_roots=args.protected_root)
    plan=json.loads((base/'input/plan.json').read_text())
    out=Path(plan['body']['execution_directory'])
    error=None
    try:
        with (base/'generation.log').open('xb') as log:
            result=subprocess.run(command,stdout=log,stderr=subprocess.STDOUT,check=False)
        if result.returncode:error='GeneratorStopped'
    except Exception as exc:
        error=type(exc).__name__
    finally:
        # Runtime claims/checkpoints preserve any attempted call independently.
        # This artifact adds a terminal encrypted copy; never includes input labels.
        evidence=base/'terminal-evidence';evidence.mkdir()
        if out.exists():
            import shutil
            shutil.copytree(out,evidence/'run')
        if (base/'generation.log').exists():
            import shutil
            shutil.copy2(base/'generation.log',evidence/'generation.log')
        (evidence/'bootstrap-status.json').write_text(json.dumps(dict(error=error,run_id=run_id,
            workflow_sha=os.environ['GITHUB_SHA'],automatic_retries=0)))
        wire=capsule.seal(recipient,capsule.archive(evidence),('output:'+run_id).encode())
        (Path(os.environ['RUNNER_TEMP'])/'final-output.enc').write_bytes(wire)
        print(json.dumps(dict(status='stopped' if error else 'generation_finished',
                             encrypted_output_sha256=hashlib.sha256(wire).hexdigest())))
    if error:raise SystemExit(1)


if __name__=='__main__':main()
