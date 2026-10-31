#!/usr/bin/env python3
"""Offline private review handoff/intake. Never produces human judgments itself."""
import argparse
import csv
from datetime import datetime, timezone
import json
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src'))


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    commands=parser.add_subparsers(dest='command',required=True)
    prep=commands.add_parser('prepare')
    prep.add_argument('--source',type=Path,required=True)
    prep.add_argument('--kind',choices=('semantic','relevance'),required=True)
    check=commands.add_parser('validate')
    check.add_argument('--packet',type=Path,required=True)
    check.add_argument('--submission',type=Path,required=True)
    check.add_argument('--reviewer-id',required=True)
    merge=commands.add_parser('reconcile')
    merge.add_argument('--review-a',type=Path,required=True)
    merge.add_argument('--review-b',type=Path,required=True)
    merge.add_argument('--adjudications',type=Path)
    for command in (prep,check,merge):command.add_argument('--out',type=Path,required=True)
    args=parser.parse_args(argv)
    from searchclinic.research_v5 import review
    from searchclinic.research_v5.transport import private_path
    from searchclinic.research_v5.__main__ import protect,write_once
    output=private_path(args.out)
    if output.exists():raise FileExistsError('output already exists; preserve the original evidence')
    if args.command=='prepare':
        source=private_path(args.source)
        protect([source/'private'])
        result=review.prepare_handoff(source,args.kind,output)
        print(json.dumps(result,ensure_ascii=False));return
    packet_files={}
    adjudication_raw=None
    if args.command=='validate':
        submission=private_path(args.submission)
        result=review.validate_submission(private_path(args.packet),submission,args.reviewer_id)
        raw=review._bytes(submission)
        if review._hash(raw)!=result['body']['submission_sha256']:
            raise ValueError('submitted bytes changed during validation')
        packet_dir=private_path(args.packet)
        packet_files={name:review._bytes(packet_dir/name) for name in ('packet.json','inputs.json','template.csv')}
        if json.loads(packet_files['packet.json'])!=result['body']['packet']:
            raise ValueError('packet changed during archival')
        for name in ('inputs.json','template.csv'):
            if review._hash(packet_files[name])!=result['body']['packet']['body']['files'][name]:
                raise ValueError('packet file changed during archival')
        summary={**result['body']['counts'],'kind':result['body']['kind']}
    else:
        a,b=review.load_submission_receipt(private_path(args.review_a)),review.load_submission_receipt(private_path(args.review_b))
        kind=review.verify(a)['kind']
        fields=['query_id','candidate_index' if kind=='semantic' else 'doc_id',
                'final_value','adjudicator_id','decision_reason','adjudicated_at_utc']
        adjudication_raw=review._bytes(private_path(args.adjudications)) if args.adjudications else None
        decisions=review._csv(adjudication_raw,fields) if adjudication_raw is not None else None
        result=review.reconcile(a,b,decisions)
        if adjudication_raw is not None:
            result['body']['adjudication_source']={'sha256':review._hash(adjudication_raw),
                'received_at_utc':datetime.now(timezone.utc).isoformat()}
            result=review.freeze(result['body'])
        summary={key:result['body'][key] for key in ('kind','pending_count','resolved_count','labels_complete','agreement')}
    summary.update(provider_calls_executed=0,final_evaluation_ready=False)
    output.mkdir(parents=True,exist_ok=False,mode=0o700)
    write_once(output/'receipt.json',result);write_once(output/'summary.json',summary)
    if args.command=='validate':
        (output/'packet').mkdir(mode=0o700)
        for name,data in packet_files.items():
            with (output/'packet'/name).open('xb') as stream:stream.write(data)
        with (output/'original-submission.csv').open('xb') as stream:stream.write(raw)
    else:
        if adjudication_raw is not None:
            with (output/'original-adjudication.csv').open('xb') as stream:stream.write(adjudication_raw)
        body=result['body']
        with (output/'adjudication-template.csv').open('x',encoding='utf-8-sig',newline='') as stream:
            writer=csv.DictWriter(stream,fieldnames=fields);writer.writeheader()
            for row in body['queue']:
                if not row['resolved'] and row['reason']!='missing_initial_review':
                    writer.writerow(dict(zip(fields[:2],row['identity'])))
        if body['labels_complete']:write_once(output/'private/labels.json',body['labels'])
    print(json.dumps(summary,ensure_ascii=False,allow_nan=False))


if __name__=='__main__':main()
