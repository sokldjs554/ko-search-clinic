#!/usr/bin/env python3
"""Free preparation by default; bounded GPT experiment requires separate approval."""
import argparse
from dataclasses import asdict
import json
import os
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src'))


def read(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def prepare():
    # This extraction process has no provider credential. Only public identities
    # survive; the credentialed process cannot open the historical source files.
    from prepare_v5_development import SOURCES, MODEL_ID
    from searchclinic.corpus import load_catalog
    from searchclinic.research_v5.pipeline import freeze
    from searchclinic.research_v5.generation import build_study
    identities = None
    for path in SOURCES:
        rows = read(path)['queries']
        pairs = [(r['query_id'],r['query']) for r in rows]
        if len(pairs)!=len(set(qid for qid,_ in pairs)) or (identities is not None and pairs!=identities):
            raise ValueError('historical public identity coverage mismatch')
        identities = pairs
    if len(identities)!=36:
        raise ValueError('exactly 36 existing development queries required')
    records = [dict(context=dict(query_id=qid,query=query,query_tokens=[],search_total=0,grep_total=0,
        similar=[],documents=[],observation=dict(query_id=qid,query=query,split='dev',result_count=0)),
        candidates=[],generation_error=None) for qid,query in identities]
    return build_study(freeze(dict(version='v5',model_id=MODEL_ID,min_confidence=.8,seed=20261030,
        documents=[asdict(d) for d in sorted(load_catalog(),key=lambda d:d.doc_id)],records=records)))


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command',choices=['prepare','mock','execute','gate'])
    parser.add_argument('--study',type=Path)
    parser.add_argument('--out',type=Path,required=True)
    parser.add_argument('--approval',type=Path)
    parser.add_argument('--expect-hash')
    parser.add_argument('--protected-root',action='append',default=[])
    args = parser.parse_args(argv)
    try:
        if args.command in ('prepare','mock') and os.environ.get('OPENAI_API_KEY'):
            raise ValueError('free preparation/mock must not receive provider credentials')
        if args.command in ('mock','execute'):
            from run_v5_judges import protect
            protect([ROOT/'src/searchclinic/corpus/evalset.py',ROOT/'src/searchclinic/data/evalset.json',
                     ROOT/'artifacts/research/versions',ROOT/'work/private',*args.protected_root])
        from searchclinic.research_v5 import generation, transport
        output = transport.private_path(args.out)
        study = prepare() if args.command=='prepare' else read(args.study)
        body = generation.checked_study(study)
        if args.expect_hash and args.expect_hash!=study['sha256']:
            raise ValueError('reviewed study hash mismatch')
        if args.command=='prepare':
            output.mkdir(parents=True,mode=0o700,exist_ok=False)
            transport._write(output/'study.json',study)
            transport._write(output/'generation-plan.json',generation.build_generation_plan(study))
            result = dict(study_hash=study['sha256'],model_id=body['model_id'],max_calls=body['max_calls'],
                maximum_cost_usd=body['maximum_cost_usd'],provider_calls_executed=0,
                independent_final_evaluation=False)
            transport._write(output/'proposal.json',result)
        elif args.command=='gate':
            if args.approval is None or not args.approval.exists():
                print('authorized=false')
                return 0
            def git(*values):
                return subprocess.check_output(['git',*values],cwd=ROOT,text=True).strip()
            ancestry = git('rev-list','--parents','-n','1','HEAD').split()
            if len(ancestry)!=2 or ancestry[0]!=os.environ.get('GITHUB_SHA'):
                raise ValueError('approval must be a single-parent reviewed commit')
            approved = generation.validate_approval_gate(study=study,approval=read(args.approval),
                parent_commit=ancestry[1],changed_paths=git('diff','--name-only',ancestry[1],'HEAD').splitlines(),
                commit_message=git('log','-1','--format=%B'),attempt=os.environ.get('GITHUB_RUN_ATTEMPT'))
            from searchclinic.research_v5.evidence import validate_recipient
            validate_recipient(read(ROOT/'ops/v5-recipient.json'))
            output.parent.mkdir(parents=True,exist_ok=True)
            transport._write(output,approved)
            print('authorized=true')
            return 0
        else:
            result = generation.run_study(study,output,mock=args.command=='mock',
                approval=read(args.approval) if args.approval else None)
            result = {k:result[k] for k in ('study_hash','status','provider_calls_executed','candidate_count',
                                           'maximum_cost_usd','independent_final_evaluation')}
        print(json.dumps(result,sort_keys=True))
        return 0
    except Exception:
        print('{"status":"blocked","error":"invalid_generated_study_or_execution_inputs"}',file=sys.stderr)
        return 2


if __name__=='__main__':
    raise SystemExit(main())
