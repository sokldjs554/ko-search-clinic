"""Evidence privacy, integrity and one-push authorization boundaries."""
import io
import json
import stat
import zipfile

import pytest

from searchclinic.research_v5 import evidence

PLAN = 'e916e357cd7426a6bb50180559b542b33b28f20dda0189dcfb37ae7ed9d6f99c'
RUN = '12345678'


@pytest.fixture
def work(tmp_path, monkeypatch):
    root = tmp_path / 'work'
    root.mkdir()
    monkeypatch.setattr(evidence, 'WORK_ROOT', root)
    return root


def package(work):
    recipient = evidence.create_recipient(work / 'key.json')
    source = work / 'source'
    source.mkdir()
    (source / 'raw.json').write_text('{"private":"secret model reasoning"}', encoding="utf-8")
    (source / 'private').mkdir()
    (source / 'private' / 'labels.json').write_text('{"answer":42}', encoding="utf-8")
    receipt = evidence.seal_directory(source, recipient, work / 'sealed', PLAN, RUN)
    return recipient, source, receipt


def test_roundtrip_preserves_raw_bytes_and_private_key_permissions(work):
    recipient, source, receipt = package(work)
    evidence.check_key_permissions(work / 'key.json')
    assert set(recipient) == {'version', 'public_key', 'recipient_sha256'}
    assert b'secret model reasoning' not in (work / 'sealed' / 'evidence.enc.json').read_bytes()
    assert 'private' not in json.dumps(receipt)
    evidence.decrypt_file(work / 'sealed' / 'evidence.enc.json', work / 'key.json', work / 'restored', PLAN, RUN)
    assert (work / 'restored' / 'raw.json').read_bytes() == (source / 'raw.json').read_bytes()
    assert (work / 'restored' / 'private' / 'labels.json').read_text(encoding="utf-8") == '{"answer":42}'
    if not evidence.WINDOWS:
        assert stat.S_IMODE((work / 'restored' / 'raw.json').stat().st_mode) == 0o600


@pytest.mark.parametrize('field', ['ciphertext', 'archive_sha256', 'plan_hash', 'run_id'])
def test_tampering_rejected_before_extraction(work, field):
    package(work)
    wire = work / 'sealed' / 'evidence.enc.json'
    envelope = json.loads(wire.read_text(encoding="utf-8"))
    value = envelope[field]
    envelope[field] = ('A' if value[0] != 'A' else 'B') + value[1:]
    wire.write_text(json.dumps(envelope), encoding="utf-8")
    with pytest.raises(ValueError):
        evidence.decrypt_file(wire, work / 'key.json', work / 'restored', PLAN, RUN)
    assert not (work / 'restored').exists()


def test_expected_binding_must_match(work):
    package(work)
    with pytest.raises(ValueError):
        evidence.decrypt_file(work / 'sealed' / 'evidence.enc.json', work / 'key.json', work / 'restored', PLAN, '999')


def test_never_overwrites_key_package_or_extraction(work):
    recipient, source, _ = package(work)
    original = (work / 'key.json').read_bytes()
    with pytest.raises(FileExistsError):
        evidence.create_recipient(work / 'key.json')
    assert (work / 'key.json').read_bytes() == original
    with pytest.raises(FileExistsError):
        evidence.seal_directory(source, recipient, work / 'sealed', PLAN, RUN)
    (work / 'restored').mkdir()
    (work / 'restored' / 'keep').write_text('untouched', encoding="utf-8")
    with pytest.raises(FileExistsError):
        evidence.decrypt_file(work / 'sealed' / 'evidence.enc.json', work / 'key.json', work / 'restored', PLAN, RUN)
    assert (work / 'restored' / 'keep').read_text(encoding="utf-8") == 'untouched'


def test_all_private_outputs_require_work_and_reject_symlink_escape(work):
    with pytest.raises(ValueError):
        evidence.create_recipient(work.parent / 'public-key.json')
    (work / 'escape').symlink_to(work.parent, target_is_directory=True)
    with pytest.raises(ValueError):
        evidence.create_recipient(work / 'escape' / 'key.json')
    package(work)
    with pytest.raises(ValueError):
        evidence.decrypt_file(work / 'sealed' / 'evidence.enc.json', work / 'key.json', work.parent / 'public-output', PLAN, RUN)


@pytest.mark.parametrize('name', ['../escape', '/absolute', 'a/../../escape', 'a\\escape', 'C:escape'])
def test_unsafe_zip_entry_has_no_partial_extraction(work, name):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, 'w') as archive:
        archive.writestr('valid', 'safe')
        item = zipfile.ZipInfo('placeholder')
        # Preserve the wire name: Windows ZipInfo construction normalizes it.
        item.filename = item.orig_filename = name
        archive.writestr(item, 'unsafe')
    with pytest.raises(ValueError):
        evidence.extract_archive(buf.getvalue(), work / 'restored')
    assert not (work / 'restored').exists()


def test_zip_symlink_and_source_symlink_are_rejected(work):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, 'w') as archive:
        item = zipfile.ZipInfo('link')
        item.external_attr = (stat.S_IFLNK | 0o777) << 16
        archive.writestr(item, '../outside')
    with pytest.raises(ValueError):
        evidence.extract_archive(buf.getvalue(), work / 'restored')
    recipient, source, _ = package(work)
    (source / 'link').symlink_to(work / 'key.json')
    with pytest.raises(ValueError):
        evidence.seal_directory(source, recipient, work / 'other', PLAN, RUN)


def approval():
    return {'approved_code_commit': 'a'*40, 'transport_approval': {
        'approved': True, 'plan_hash': PLAN, 'model_id': 'gpt-4.1-mini-2025-04-14',
        'max_calls': 90, 'max_cost_usd': .72}}


def test_gate_requires_exact_code_marker_approval_only_push_and_first_attempt():
    valid = dict(approval=approval(), parent_commit='a'*40, changed_paths=['ops/v5-approved.json'],
                 commit_message='V5_APPROVED_PLAN='+PLAN, attempt='1', plan_hash=PLAN)
    assert evidence.validate_approval_gate(**valid) == approval()['transport_approval']
    mutations = [dict(attempt='2'), dict(parent_commit='b'*40), dict(commit_message='ordinary update'),
                 dict(changed_paths=['ops/v5-approved.json', 'src/changed.py']), dict(approval=None)]
    for mutation in mutations:
        with pytest.raises(ValueError):
            evidence.validate_approval_gate(**(valid | mutation))


def test_zip_conflicting_paths_rejected_before_writing(work):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, 'w') as archive:
        archive.writestr('parent', 'file')
        archive.writestr('parent/child', 'child')
    with pytest.raises(ValueError):
        evidence.extract_archive(buf.getvalue(), work / 'restored')
    assert not (work / 'restored').exists()


def test_low_order_recipient_rejected_before_archiving(work):
    import base64
    import hashlib
    recipient = {'version': evidence.VERSION, 'public_key': base64.b64encode(bytes(32)).decode(),
                 'recipient_sha256': hashlib.sha256(bytes(32)).hexdigest()}
    with pytest.raises(ValueError):
        evidence.seal_directory(work / 'missing', recipient, work / 'sealed', PLAN, RUN)
    assert not (work / 'sealed').exists()


def test_cli_keygen_never_prints_private_material_and_denies_overwrite(work, capsys):
    import importlib.util
    from pathlib import Path
    script = Path(__file__).resolve().parents[1] / 'scripts/package_v5_evidence.py'
    spec = importlib.util.spec_from_file_location('package_v5', script)
    cli = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(cli)
    assert cli.main(['keygen', '--private', str(work / 'cli-key.json')]) == 0
    printed = capsys.readouterr()
    public = json.loads(printed.out)
    private = json.loads((work / 'cli-key.json').read_text(encoding="utf-8"))
    assert 'private_key' not in public
    assert private['private_key'] not in printed.out + printed.err
    assert cli.main(['keygen', '--private', str(work / 'cli-key.json')]) == 2
    assert private['private_key'] not in str(capsys.readouterr())
    assert cli.main(['gate', '--approval', str(work / 'absent.json'), '--recipient', 'absent',
                     '--plan-hash', PLAN, '--out', str(work / 'approval.json')]) == 0
    assert capsys.readouterr().out.strip() == 'authorized=false'


@pytest.mark.parametrize('name', ['a\\escape', 'safe\x00hidden'])
def test_original_archive_names_are_checked_before_library_normalization(work, monkeypatch, name):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, 'w') as archive:
        item = zipfile.ZipInfo('placeholder')
        item.filename = item.orig_filename = name
        archive.writestr(item, 'unsafe')
    # Emulate the Windows ZIP reader on Linux too.
    monkeypatch.setattr(zipfile.os, 'sep', '\\')
    with pytest.raises(ValueError, match='unsafe archive entry'):
        evidence.extract_archive(buf.getvalue(), work / 'restored')
    assert not (work / 'restored').exists()
