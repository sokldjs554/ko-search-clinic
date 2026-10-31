#!/usr/bin/env python3
"""Prepare/validate encrypted V5 transfer; no provider or generation requests."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from searchclinic.research_v5 import evidence


def _read(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def _git(*args):
    return subprocess.check_output(['git', *args], cwd=ROOT, text=True).strip()


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True)
    keygen = commands.add_parser('keygen')
    keygen.add_argument('--private', type=Path, required=True)
    check = commands.add_parser('verify-plan')
    check.add_argument('--plan', type=Path, required=True)
    check.add_argument('--plan-hash', required=True)
    gate = commands.add_parser('gate')
    gate.add_argument('--approval', type=Path, required=True)
    gate.add_argument('--recipient', type=Path, required=True)
    gate.add_argument('--plan-hash', required=True)
    gate.add_argument('--out', type=Path, required=True)
    for name in ('seal', 'decrypt'):
        sub = commands.add_parser(name)
        sub.add_argument('--plan-hash', required=True)
        sub.add_argument('--run-id', required=True)
        sub.add_argument('--out', type=Path, required=True)
        if name == 'seal':
            sub.add_argument('--source', type=Path, required=True)
            sub.add_argument('--recipient', type=Path, required=True)
        else:
            sub.add_argument('--envelope', type=Path, required=True)
            sub.add_argument('--private', type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        if args.command == 'keygen':
            result = evidence.create_recipient(args.private)
        elif args.command == 'verify-plan':
            if os.environ.get('OPENAI_API_KEY'):
                raise ValueError('preparation must not receive provider credentials')
            from searchclinic.research_v5.transport import _checked_plan
            plan = _read(args.plan)
            body = _checked_plan(plan)
            if plan['sha256'] != args.plan_hash:
                raise ValueError('prepared plan differs from reviewed fixed plan')
            result = {'plan_hash': plan['sha256'], 'provider_calls_executed': 0,
                      'model_id': body['model_id'], 'call_count': body['call_count'],
                      'maximum_cost_usd': body['maximum_cost_usd']}
        elif args.command == 'gate':
            if not args.approval.exists():
                print('authorized=false')
                return 0
            # Reject merges and bind to exactly one reviewed parent.
            ancestry = _git('rev-list', '--parents', '-n', '1', 'HEAD').split()
            if len(ancestry) != 2 or os.environ.get('GITHUB_SHA') != ancestry[0]:
                raise ValueError('approval head must have exactly one reviewed parent')
            approval = evidence.validate_approval_gate(
                approval=_read(args.approval), parent_commit=ancestry[1],
                changed_paths=_git('diff', '--name-only', ancestry[1], 'HEAD').splitlines(),
                commit_message=_git('log', '-1', '--format=%B'),
                attempt=os.environ.get('GITHUB_RUN_ATTEMPT'), plan_hash=args.plan_hash)
            evidence.validate_recipient(_read(args.recipient))
            out = evidence._private_path(args.out)
            out.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            evidence._write(out, evidence._json(approval) + b'\n')
            print('authorized=true')
            return 0
        elif args.command == 'seal':
            result = evidence.seal_directory(args.source, _read(args.recipient), args.out, args.plan_hash, args.run_id)
        else:
            result = evidence.decrypt_file(args.envelope, args.private, args.out, args.plan_hash, args.run_id)
        print(json.dumps(result, sort_keys=True, allow_nan=False))
        return 0
    except Exception:
        # Never expose private file contents, provider output or credential text.
        print('{"status":"blocked","error":"invalid_evidence_or_approval_inputs"}', file=sys.stderr)
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
