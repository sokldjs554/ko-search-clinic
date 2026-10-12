"""Finite candidate worker with explicit private-file/import denial.

This is a trusted worker API boundary, not an OS sandbox for hostile Python code.
"""
import json
import os
import sys
from pathlib import Path


def install_boundary(denied_paths):
    paths = tuple(Path(p).resolve() for p in denied_paths)
    def audit(event, args):
        if event == 'open' and isinstance(args[0], (str,bytes,os.PathLike)):
            path = Path(os.fsdecode(args[0])).resolve()
            if any(path == p or p in path.parents for p in paths):
                raise PermissionError('private evaluator file is unavailable to generator')
        if event == 'import' and args[0].startswith('searchclinic.research.phase2.evaluator'):
            raise ImportError('evaluator unavailable to candidate worker')
    sys.addaudithook(audit)


def main():
    payload = json.load(sys.stdin)
    denied = ['/workspace/phase2-private','/workspace/konkuk-2027-private']
    if 'probe' in payload:
        denied.append(payload['probe'])
    install_boundary(denied)
    if 'probe' in payload:
        report = {}
        try:
            Path(payload['probe']).read_text(encoding='utf-8')
            report['label_read']='allowed'
        except PermissionError:
            report['label_read']='denied'
        try:
            __import__('searchclinic.research.phase2.evaluator')
            report['evaluator_import']='allowed'
        except ImportError:
            report['evaluator_import']='denied'
    else:
        if set(payload) != {'context'}:
            raise ValueError('candidate worker accepts only the public context')
        from .generation import generate_rules
        report = generate_rules(payload['context'])
    json.dump(report,sys.stdout,ensure_ascii=False,allow_nan=False)
