"""Offline receive checks with real authenticated encryption, no remote calls."""
import base64
import hashlib
import io
import json
import os
import sys
from pathlib import Path
import zipfile

import pytest
from cryptography.exceptions import InvalidTag

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import capsule
import runner
import execute


class MemoryIO:
    def __init__(self, objects):
        self.objects = objects
        self.reads = []

    def get_bytes(self, path):
        self.reads.append(path)
        return self.objects[path]


def package(wire, run_id='123'):
    chunks = [wire[:40], wire[40:]]
    manifest = {'run_id': run_id, 'chunks': [
        {'name': f'chunk-{index:03d}', 'sha256': hashlib.sha256(part).hexdigest()}
        for index, part in enumerate(chunks)
    ], 'sha256': hashlib.sha256(wire).hexdigest()}
    io = MemoryIO({f'transfer/{run_id}/chunk-{index:03d}': base64.b64encode(part)
                   for index, part in enumerate(chunks)})
    return manifest, io


def test_receive_authenticated_ordered_chunks():
    private, public = capsule.keypair()
    wire = capsule.seal(public, b'private fixture data', b'input:123')
    manifest, io = package(wire)
    assert runner.receive(io, '123', private, manifest) == b'private fixture data'
    assert io.reads == ['transfer/123/chunk-000', 'transfer/123/chunk-001']


@pytest.mark.parametrize('fault', ['run_id', 'path', 'empty', 'chunk_hash', 'envelope_hash', 'invalid_base64'])
def test_receive_rejects_invalid_manifest_or_chunk(fault):
    private, public = capsule.keypair()
    manifest, io = package(capsule.seal(public, b'private fixture data', b'input:123'))
    if fault == 'run_id':
        manifest['run_id'] = '456'
    elif fault == 'path':
        manifest['chunks'][0]['name'] = 'chunk-../escape'
    elif fault == 'empty':
        manifest['chunks'] = []
    elif fault == 'chunk_hash':
        manifest['chunks'][0]['sha256'] = '0' * 64
    elif fault == 'envelope_hash':
        manifest['sha256'] = '0' * 64
    else:
        io.objects['transfer/123/chunk-000'] = b'!!!!'
    with pytest.raises(ValueError):
        runner.receive(io, '123', private, manifest)
    if fault in ('run_id', 'path', 'empty'):
        assert io.reads == []


@pytest.mark.parametrize('fault', ['wrong_recipient', 'tamper', 'wrong_context'])
def test_receive_authentication_rejects_even_matching_transport_hashes(fault):
    private, public = capsule.keypair()
    context = b'input:456' if fault == 'wrong_context' else b'input:123'
    wire = capsule.seal(public, b'private fixture data', context)
    if fault == 'wrong_recipient':
        private, _ = capsule.keypair()
    elif fault == 'tamper':
        wire = wire[:-1] + bytes([wire[-1] ^ 1])
    manifest, io = package(wire)
    with pytest.raises(InvalidTag):
        runner.receive(io, '123', private, manifest)


class CheckpointIO:
    def __init__(self, fail_at=None):
        self.objects = {}
        self.attempts = []
        self.fail_at = fail_at

    def put_bytes(self, path, data, message):
        self.attempts.append(path)
        if len(self.attempts) == self.fail_at:
            raise TimeoutError('fixture ambiguous checkpoint write')
        assert path not in self.objects
        self.objects[path] = data


def test_checkpoint_chunked_roundtrip_acknowledged_after_all_chunks(tmp_path):
    private, public = capsule.keypair()
    (tmp_path / 'out').mkdir()
    original = os.urandom(900_001)
    (tmp_path / 'out/evidence.bin').write_bytes(original)
    store = CheckpointIO()
    execute.Checkpointer(tmp_path, store, public, '123', 'test')()
    assert len(store.objects) >= 4
    assert store.attempts[-1].endswith('.json')
    manifest = json.loads(store.objects[store.attempts[-1]])
    parts = []
    for item in manifest['chunks']:
        encoded = store.objects[item['path']]
        assert len(encoded) < 1_000_000
        part = base64.b64decode(encoded, validate=True)
        assert len(part) <= 400_000
        assert hashlib.sha256(part).hexdigest() == item['sha256']
        parts.append(part)
    wire = b''.join(parts)
    assert hashlib.sha256(wire).hexdigest() == manifest['sha256']
    raw = capsule.unseal(private, wire, b'output:123')
    with zipfile.ZipFile(io.BytesIO(raw)) as archive:
        assert archive.namelist() == ['evidence.bin']
        assert archive.read('evidence.bin') == original


def test_checkpoint_failed_chunk_never_acknowledges_complete_snapshot(tmp_path):
    _, public = capsule.keypair()
    (tmp_path / 'out').mkdir()
    (tmp_path / 'out/evidence.bin').write_bytes(os.urandom(900_001))
    store = CheckpointIO(fail_at=2)
    with pytest.raises(TimeoutError):
        execute.Checkpointer(tmp_path, store, public, '123', 'test')()
    assert len(store.attempts) == 2
    assert not any(path.endswith('.json') for path in store.attempts)
