"""Offline CLI. Application and scoring run in separate invocations.

The audit hook protects declared label paths from trusted project code. It is
not an operating-system sandbox against hostile Python or a proof of blinding.
"""
import argparse
import json
import os
from pathlib import Path
import sys


def read(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def write_once(path, value):
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    # Exclusive creation prevents accidental overwriting of experiment evidence.
    with target.open('x', encoding='utf-8', newline='\n') as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2, allow_nan=False)
        stream.write('\n')


def protect(roots):
    paths = [Path(p).resolve() for p in roots]
    def audit(event, args):
        if event == 'open' and isinstance(args[0], (str, bytes, os.PathLike)):
            path = Path(os.fsdecode(args[0])).resolve()
            if any(path == p or p in path.parents for p in paths):
                raise PermissionError('private labels unavailable to application')
        if event == 'import' and args[0].startswith((
            'searchclinic.evaluation', 'searchclinic.research_v5.evaluation',
            'searchclinic.research.phase2.evaluator',
        )):
            raise ImportError('evaluator unavailable to application')
    sys.addaudithook(audit)


def main():
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, 'reconfigure'):
            stream.reconfigure(encoding='utf-8')
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='command', required=True)
    for name in ('freeze', 'verify', 'requests', 'apply', 'diagnostic', 'score'):
        p = sub.add_parser(name)
        p.add_argument('input', type=Path)
        if name != 'verify':
            p.add_argument('--out', required=True, type=Path)
        if name in ('requests', 'apply', 'diagnostic'):
            p.add_argument('--protected-root', action='append', required=True)
        if name in ('requests', 'apply'):
            p.add_argument('--condition', choices=['pair', 'context', 'rubric'], default='rubric')
        if name == 'apply':
            p.add_argument('--verdicts', type=Path, required=True)
            p.add_argument('--policy', choices=['semantic', 'first_valid'], default='semantic')
        if name == 'score':
            p.add_argument('--labels', type=Path, required=True,
                           help='JSON with queries and qrels, accessible only in scoring invocation')
    probe = sub.add_parser('probe')
    probe.add_argument('--protected-root', action='append', required=True)
    args = parser.parse_args()
    if hasattr(args, 'protected_root'):
        protect(args.protected_root)
    if args.command == 'probe':
        result = {}
        try:
            Path(args.protected_root[0]).read_bytes()
            result['label_read'] = 'allowed'
        except PermissionError:
            result['label_read'] = 'denied'
        try:
            __import__('searchclinic.research_v5.evaluation')
            result['evaluator_import'] = 'allowed'
        except ImportError:
            result['evaluator_import'] = 'denied'
        print(json.dumps(result))
        return
    from .pipeline import freeze, verify, apply_candidates, diagnostic_candidates, score_application
    value = read(args.input)
    if args.command == 'verify':
        verify(value)
        print(json.dumps({'verified_sha256': value['sha256']}))
        return
    if args.command == 'freeze':
        result = freeze(value)
    elif args.command == 'requests':
        from .pipeline import _bundle
        from .semantic import prepare_judge_request
        _, _, records = _bundle(value)
        requests = {}
        generation_errors = {}
        for qid, (context, record) in records.items():
            requests[qid] = []
            generation_errors[qid] = record['generation_error']
            if record['generation_error'] is not None:
                continue
            for candidate in record['candidates']:
                try:
                    request = prepare_judge_request(context, candidate, args.condition)
                    requests[qid].append({'request': request.model_dump(), 'error': None})
                except (ValueError, TypeError) as exc:
                    requests[qid].append({'request': None, 'error': str(exc)})
        result = freeze({'input_hash': value['sha256'], 'condition': args.condition,
                         'generation_calls': 0, 'requests': requests,
                         'generation_errors': generation_errors})
    elif args.command == 'apply':
        result = apply_candidates(value, read(args.verdicts), condition=args.condition, policy=args.policy)
    elif args.command == 'diagnostic':
        result = diagnostic_candidates(value)
    else:
        labels = read(args.labels)
        if set(labels) != {'queries', 'qrels'}:
            raise ValueError('label envelope requires exactly queries and qrels')
        result = score_application(value, labels['queries'], labels['qrels'])
    write_once(args.out, result)
    print(json.dumps({'output': str(args.out), 'sha256': result['sha256']}))


if __name__ == '__main__':
    main()
