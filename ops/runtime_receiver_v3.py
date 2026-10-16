"""Minimal public encrypted v3 runtime receiver; no source checkout or model key.

Only stdlib and the unchanged public capsule/GitHubIO helpers are imported before
an externally pinned runtime ZIP hash is verified. This step cannot generate.
"""
import argparse
import base64
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import sys
import time

try:
    from .public_bootstrap import capsule, github_io
except ImportError:  # direct script on a minimal Actions bootstrap directory
    from public_bootstrap import capsule, github_io


def require(ok,message):
    if not ok:raise ValueError(message)


def receive_runtime(io,run_id,private,manifest,expected_zip_sha256,destination):
    require(type(manifest) is dict and set(manifest)=={'scope','run_id','chunks','sha256'}
            and manifest['scope']=='filtered_runtime_v1' and manifest['run_id']==run_id,'runtime scope/run mismatch')
    require(re.fullmatch('[0-9a-f]{64}',expected_zip_sha256) is not None,'frozen runtime SHA required')
    chunks=manifest['chunks'];require(type(chunks) is list and 1<=len(chunks)<=200,'runtime chunk count')
    names=set()
    for c in chunks:
        require(type(c) is dict and set(c)=={'name','sha256'},'runtime chunk fields')
        require(type(c['name']) is str and re.fullmatch(r'chunk-[0-9]+\.b64',c['name']) is not None
                and c['name'] not in names,'runtime chunk path/duplicate')
        names.add(c['name'])
    parts=[];total=0
    for c in chunks:
        data=base64.b64decode(io.get_bytes(f'runtime/{run_id}/'+c['name']),validate=True)
        total+=len(data)
        require(total<=20_000_000 and hashlib.sha256(data).hexdigest()==c['sha256'],'runtime chunk hash/size')
        parts.append(data)
    wire=b''.join(parts)
    require(hashlib.sha256(wire).hexdigest()==manifest['sha256'],'runtime envelope hash')
    raw=capsule.unseal(private,wire,('runtime-input:'+run_id).encode())
    require(hashlib.sha256(raw).hexdigest()==expected_zip_sha256,'runtime archive hash mismatch')
    capsule.extract(raw,destination)
    return Path(destination)


def rendezvous(io,environment,expected_zip_sha256,destination,*,polls=120,sleep=time.sleep):
    require(not any(k in environment for k in ('OPENAI_API_KEY','ANTHROPIC_API_KEY','GH_TOKEN')),'provider/extra key forbidden in provisioning')
    require(bool(environment.get('GITHUB_TOKEN')),'GitHub transfer key unavailable')
    require(environment.get('GITHUB_RUN_ATTEMPT')=='1','workflow rerun forbidden')
    run_id=environment.get('GITHUB_RUN_ID','');sha=environment.get('GITHUB_SHA','')
    require(re.fullmatch('[A-Za-z0-9_-]+',run_id) is not None and re.fullmatch('[0-9a-f]{40}',sha) is not None,'workflow identity required')
    require(re.fullmatch('[0-9a-f]{64}',expected_zip_sha256) is not None,'frozen runtime SHA required')
    require(not Path(destination).exists(),'runtime destination already exists')
    private,public=capsule.keypair()
    ready=json.dumps(dict(scope='filtered_runtime_v1',run_id=run_id,workflow_sha=sha,input_public_key=public.hex(),
                          expected_runtime_zip_sha256=expected_zip_sha256,generation_calls=0),sort_keys=True).encode()
    require(io.put_bytes(f'runtime/{run_id}/ready.json',ready,'research: ephemeral filtered-runtime input key')
            ==github_io._blob_sha(ready),'runtime ready acknowledgment mismatch')
    for _ in range(polls):
        manifest=io.get_json(f'runtime/{run_id}/input.json')
        if manifest is not None:
            return receive_runtime(io,run_id,private,manifest,expected_zip_sha256,destination)
        sleep(15)
    raise TimeoutError('runtime input absent; no model calls')


def verify_installed_runtime(destination):
    # Called only after authenticating the externally pinned ZIP bytes.
    dest=Path(destination).resolve()
    previous_bytecode=sys.dont_write_bytecode
    sys.dont_write_bytecode=True
    sys.path.insert(0,str(dest/'overlay'))
    try:
        spec=importlib.util.spec_from_file_location('verified_v3_snapshot',dest/'overlay/independent_v3/runtime_snapshot.py')
        module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
        return module.verify_runtime_package(dest)
    finally:
        sys.path.pop(0)
        sys.dont_write_bytecode=previous_bytecode


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--sha256',required=True);parser.add_argument('--destination',required=True)
    parser.add_argument('--verification',required=True)
    args=parser.parse_args();os.umask(0o077)
    require(not any(k in os.environ for k in ('OPENAI_API_KEY','ANTHROPIC_API_KEY','GH_TOKEN')),'provider/extra key forbidden in provisioning')
    client=github_io.GitHubIO(os.environ['GITHUB_REPOSITORY'],os.environ['GITHUB_REF_NAME'],os.environ['GITHUB_TOKEN'],os.environ['GITHUB_RUN_ID'])
    dest=rendezvous(client,os.environ,args.sha256,args.destination)
    # Import only after authenticating exact externally pinned ZIP bytes.
    sys.dont_write_bytecode=True
    result=verify_installed_runtime(dest)
    record=dict(status='runtime_verified',runtime_zip_sha256=args.sha256,files=len(result['files']),
                workflow_sha=os.environ['GITHUB_SHA'],run_id=os.environ['GITHUB_RUN_ID'],generation_calls=0)
    with Path(args.verification).open('x') as stream:json.dump(record,stream)
    print(json.dumps(record))


if __name__=='__main__':main()
