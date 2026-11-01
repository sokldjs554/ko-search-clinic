"""Offline RAG revalidation must never overwrite historical response evidence."""
from pathlib import Path
import subprocess
import sys


def test_revalidate_writes_new_evidence_only(tmp_path):
    root = Path(__file__).resolve().parents[1]
    historical = root/'docs/verification/alba-20261027/run/revalidated.json'
    before = historical.read_bytes()
    command = [sys.executable, str(root/'scripts/revalidate_alba.py'), '--out-dir', str(tmp_path/'new')]
    result = subprocess.run(command, capture_output=True, timeout=60)
    assert result.returncode == 0, result.stderr
    assert (tmp_path/'new/revalidated.json').is_file()
    assert historical.read_bytes() == before
    assert subprocess.run(command, capture_output=True, timeout=60).returncode != 0
