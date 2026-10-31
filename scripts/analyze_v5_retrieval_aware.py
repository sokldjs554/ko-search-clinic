#!/usr/bin/env python3
"""Seal a private, label-denied zero-hit selection; score in a separate process."""
import argparse
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src'))


def main():
    p=argparse.ArgumentParser(description=__doc__)
    sub=p.add_subparsers(dest='command',required=True)
    a=sub.add_parser('assemble');a.add_argument('--assembly',type=Path,required=True)
    a.add_argument('--protected-root',action='append',required=True)
    s=sub.add_parser('score');s.add_argument('--selection',type=Path,required=True)
    s.add_argument('--labels',type=Path,required=True)
    for parser in (a,s):
        parser.add_argument('--out',type=Path,required=True)
    args=p.parse_args()
    from searchclinic.research_v5.__main__ import protect,read,write_once
    from searchclinic.research_v5.transport import private_path
    output=private_path(args.out)
    if args.command=='assemble':
        protect(args.protected_root)
    from searchclinic.research_v5 import retrieval_aware
    if args.command=='assemble':
        result=retrieval_aware.assemble(read(args.assembly))
    else:
        labels=read(args.labels)
        if set(labels)!={'queries','qrels'}:
            raise ValueError('expected private queries and qrels')
        result=retrieval_aware.score(read(args.selection),labels['queries'],labels['qrels'])
    write_once(output,result)
    print('Saved post-hoc development result; additional provider calls: 0.')


if __name__=='__main__':
    main()
