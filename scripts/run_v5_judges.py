#!/usr/bin/env python3
"""Prepare a free judge plan, or explicitly execute a mock/approved live run."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]


def protect(roots):
    """Install label/evaluator read denial BEFORE importing application modules.

    This audit boundary protects trusted application code, not hostile Python.
    """
    paths = [Path(p).resolve() for p in roots]
    def audit(event, args):
        if event == 'open' and isinstance(args[0], (str, bytes, os.PathLike)):
            path = Path(os.fsdecode(args[0])).resolve()
            if any(path == p or p in path.parents for p in paths):
                raise PermissionError('private labels unavailable to judge transport')
        if event == 'import' and args[0].startswith((
            'searchclinic.evaluation', 'searchclinic.research_v5.evaluation',
            'searchclinic.research.phase2.evaluator', 'searchclinic.corpus.evalset',
        )):
            raise ImportError('labels and evaluators unavailable to judge transport')
    sys.addaudithook(audit)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--bundle', type=Path, default=ROOT/'work/final-source-prepared/candidates.json')
    parser.add_argument('--out', type=Path, default=ROOT/'work/v5-judge-plan.json')
    parser.add_argument('--protected-root', action='append', type=Path, default=[])
    parser.add_argument('--execute', action='store_true', help='Execute the plan; default only saves a free plan')
    parser.add_argument('--mock', action='store_true', help='Synthetic, zero provider requests; requires --execute')
    parser.add_argument('--approval', type=Path, help='Existing independently supplied approval JSON for live execution')
    parser.add_argument('--check-model-access', action='store_true', help='Explicit GET models access check; no generation')
    args = parser.parse_args(argv)
    protected = [ROOT/'src/searchclinic/data/evalset.json', ROOT/'src/searchclinic/corpus/evalset.py',
                 args.bundle.resolve().parent/'private', *args.protected_root]
    protect(protected)
    sys.path.insert(0, str(ROOT/'src'))
    from searchclinic.research_v5.transport import build_plan, run_plan, check_model_access, private_path, _write
    try:
        if args.mock and not args.execute:
            raise ValueError('--mock requires --execute')
        if args.check_model_access and (args.execute or args.mock or args.approval):
            raise ValueError('access check must be separate from execution')
        if args.approval and not args.execute:
            raise ValueError('--approval requires --execute')
        if args.mock and args.approval:
            raise ValueError('mock does not consume live approval')
        bundle = json.loads(args.bundle.read_text(encoding='utf-8'))
        plan = build_plan(bundle)
        if args.check_model_access:
            output = private_path(args.out)
            if output.exists():
                raise ValueError('access receipt output already exists')
            output.parent.mkdir(parents=True, exist_ok=True)
            result = check_model_access(plan['body']['model_id'])
            _write(output, {'plan_hash': plan['sha256'], **result})
        elif args.execute:
            approved = json.loads(args.approval.read_text(encoding='utf-8')) if args.approval else None
            result = run_plan(plan, args.out, approval=approved, mock=args.mock)
        else:
            output = private_path(args.out)
            output.parent.mkdir(parents=True, exist_ok=True)
            _write(output, plan)
            result = {'status': 'prepared_not_executed', 'plan_hash': plan['sha256'],
                      'output': str(output), 'model_id': plan['body']['model_id'],
                      'call_count': plan['body']['call_count'], 'maximum_cost_usd': plan['body']['maximum_cost_usd'],
                      'provider_calls_executed': 0, 'model_access_checked': False,
                      'current_pricing_verified': False}
        print(json.dumps(result, ensure_ascii=False, sort_keys=True, allow_nan=False))
        return 0
    except (ValueError, OSError, KeyError, TypeError):
        # Avoid echoing paths, request bodies or credential-bearing exception text.
        print(json.dumps({'status': 'blocked', 'error': 'invalid_input_approval_credentials_or_output; inspect private artifacts and CLI contract'}))
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
