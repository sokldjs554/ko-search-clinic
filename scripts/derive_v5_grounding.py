#!/usr/bin/env python3
"""Create a private, label-denied post-hoc derivation from saved provider evidence."""
import argparse
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'src'))


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--bundle', type=Path, required=True)
    parser.add_argument('--transport-dir', type=Path, required=True)
    parser.add_argument('--protected-root', action='append', required=True)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args(argv)
    from searchclinic.research_v5.__main__ import protect, read, write_once
    protect([*args.protected_root, args.bundle.resolve().parent/'private'])
    from searchclinic.research_v5.transport import private_path
    from searchclinic.research_v5.run_evidence import load_run
    from searchclinic.research_v5.grounding import derive_trials
    output = private_path(args.out)
    output.mkdir(parents=True, exist_ok=False)
    bundle = read(args.bundle)
    result = derive_trials(bundle, load_run(args.transport_dir, bundle, require_complete=True))
    write_once(output/'derivation.json', result)
    write_once(output/'trials.json', result['body']['trials'])
    print('Private development derivation saved; additional provider calls: 0.')


if __name__ == '__main__':
    main()
