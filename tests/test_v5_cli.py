"""Command boundary and immutable output evidence."""
import json
import subprocess
import sys


def run(*args):
    return subprocess.run([sys.executable, '-m', 'searchclinic.research_v5', *map(str, args)],
                          text=True, encoding='utf-8', capture_output=True, timeout=20)


def test_label_file_and_evaluator_import_are_denied(tmp_path):
    secret = tmp_path / 'private.json'
    secret.write_text('{"qrels": {}}', encoding='utf-8')
    result = run('probe', '--protected-root', secret)
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout) == {'label_read': 'denied', 'evaluator_import': 'denied'}


def test_freeze_is_write_once_and_detects_corruption(tmp_path):
    source, out = tmp_path/'body.json', tmp_path/'seal.json'
    source.write_text('{"x": 1}', encoding='utf-8')
    result = run('freeze', source, '--out', out)
    assert result.returncode == 0, result.stderr
    initial = out.read_bytes()
    assert run('freeze', source, '--out', out).returncode != 0
    assert out.read_bytes() == initial
    value = json.loads(initial)
    value['body']['x'] = 2
    out.write_text(json.dumps(value), encoding='utf-8')
    assert run('verify', out).returncode != 0


def test_request_export_preserves_generation_failure_without_retry(tmp_path):
    from test_v5_pipeline import bundle
    from searchclinic.research_v5.pipeline import freeze
    raw = bundle()
    raw['records'][0].update(generation_error='provider timed out', candidates=[])
    source, out = tmp_path/'bundle.json', tmp_path/'requests.json'
    source.write_text(json.dumps(freeze(raw)), encoding='utf-8')
    result = run('requests', source, '--out', out, '--protected-root', tmp_path/'private')
    assert result.returncode == 0, result.stderr
    exported = json.loads(out.read_text(encoding='utf-8'))['body']
    assert exported['generation_errors']['q1'] == 'provider timed out'
    assert exported['requests']['q1'] == []
    assert exported['generation_calls'] == 0
