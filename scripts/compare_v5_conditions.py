#!/usr/bin/env python3
"""Freeze, assemble, then separately score v5 conditions without provider calls.

The assemble phase requires declared private roots and cannot read labels.
Reports include per-query diagnostics: retain them locally under private/.
"""
import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))


def private_output(path):
    target = Path(path).resolve()
    if (ROOT/'work').resolve() not in target.parents:
        raise ValueError('detailed comparison outputs must remain beneath ignored work/')
    return target


def main(argv=None):
    from searchclinic.research_v5.__main__ import protect, read, write_once
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='command', required=True)
    freeze = sub.add_parser('freeze', help='Commit prospective criteria before outcomes')
    freeze.add_argument('--bundle', type=Path, required=True)
    freeze.add_argument('--candidate-source', choices=['historical_scripted', 'gpt_generated', 'mock'], required=True)
    freeze.add_argument('--study-scope', choices=['selection_only', 'full_system'], default='selection_only')
    freeze.add_argument('--phase', choices=['development', 'final'], default='development')
    freeze.add_argument('--repeats', type=int, default=2)
    assembly = sub.add_parser('assemble', help='Label-denied application invocation')
    assembly.add_argument('--bundle', type=Path, required=True)
    assembly.add_argument('--protocol', type=Path, required=True)
    source = assembly.add_mutually_exclusive_group(required=True)
    source.add_argument('--trials', type=Path, help='Complete condition/repeat aligned trial JSON list')
    source.add_argument('--transport-dir', type=Path, help='Completed or stopped transport folder with immutable raw evidence')
    assembly.add_argument('--protected-root', action='append', required=True)
    assembly.add_argument('--attestations', type=Path)
    score = sub.add_parser('score', help='Evaluate already sealed applications against private labels')
    score.add_argument('--assembly', type=Path, required=True)
    score.add_argument('--labels', type=Path, required=True)
    score.add_argument('--human-semantics', type=Path)
    score.add_argument('--bootstrap-samples', type=int, default=2000)
    score.add_argument('--random-repeats', type=int, default=100)
    score.add_argument('--seed', type=int, default=20261030)
    for command in (freeze, assembly, score):
        command.add_argument('--out', type=Path, required=True)
    args = parser.parse_args(argv)
    args.out = private_output(args.out)
    if args.out.exists():
        raise FileExistsError(f'refusing to overwrite evidence: {args.out}')
    if ROOT / 'artifacts' in args.out.resolve().parents:
        raise ValueError('historical/public artifacts are not comparison output destinations')
    if args.command == 'assemble':
        protect(args.protected_root)
    from searchclinic.research_v5 import comparison, pipeline
    if args.command == 'freeze':
        result = comparison.freeze_analysis_protocol(read(args.bundle), candidate_source=args.candidate_source,
            study_scope=args.study_scope, repeats=args.repeats, phase=args.phase)
    elif args.command == 'assemble':
        bundle, protocol = read(args.bundle), read(args.protocol)
        summary = None
        verified_evidence = None
        if args.trials:
            trials = read(args.trials)
        else:
            from searchclinic.research_v5.run_evidence import load_run
            verified_evidence = load_run(args.transport_dir, bundle,
                require_complete=pipeline.verify(protocol)['phase']=='final')
            evidence_body = pipeline.verify(verified_evidence)
            trials, summary = evidence_body['trials'], evidence_body['summary']
        result = comparison.assemble_comparison(bundle, trials, protocol=protocol,
            attestations=read(args.attestations) if args.attestations else None, transport_summary=summary,
            transport_evidence=verified_evidence)
        body = pipeline.verify(result)
        body['boundary'] = 'separate_CLI_invocation_declared_label_paths_denied'
        result = pipeline.freeze(body)
    else:
        labels = read(args.labels)
        if not isinstance(labels, dict) or set(labels) != {'queries', 'qrels'}:
            raise ValueError('labels require exactly queries and complete qrels')
        result = comparison.score_comparison(read(args.assembly), labels['queries'], labels['qrels'],
            human_semantics=read(args.human_semantics) if args.human_semantics else None,
            bootstrap_samples=args.bootstrap_samples, random_repeats=args.random_repeats, seed=args.seed)
    write_once(args.out, result)
    print(json.dumps(dict(output=str(args.out), command=args.command, provider_calls_executed=0,
                          sha256=result.get('sha256'), superiority_claim=result.get('superiority_claim', False))))


if __name__ == '__main__':
    main()
