"""Authenticated encrypted transfer of private V5 research evidence.

Only the public recipient and aggregate ciphertext receipt may be published.
Private keys and extracted evidence are confined to the ignored work directory.
"""
from __future__ import annotations

import base64
import hashlib
import io
import json
import os
from pathlib import Path, PurePosixPath
import re
import stat
import subprocess
import zipfile

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey, X25519PublicKey
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

WORK_ROOT = Path(__file__).resolve().parents[3] / 'work'
VERSION = 'v5-evidence-x25519-hkdf-sha256-aes256gcm-1'
MAX_BYTES = 100_000_000
MAX_FILES = 5000
WINDOWS = os.name == 'nt'


def _json(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()


def _b64(value):
    return base64.b64encode(value).decode('ascii')


def _decode(value):
    return base64.b64decode(value, validate=True)


def _private_path(path):
    target = Path(path).resolve()
    if WORK_ROOT.resolve() not in target.parents:
        raise ValueError('private outputs must be beneath ignored work/')
    return target


def windows_key_acl(path, *, secure=False):
    """Restrict/verify NTFS access to current user, SYSTEM and Administrators.

    Execute a constant PowerShell policy without echoing key contents. Set the
    ACL while the newly created file is still empty; fail closed if unavailable.
    """
    literal = str(Path(path).resolve()).replace("'", "''")
    script = "$ErrorActionPreference='Stop'; $p='" + literal + "'; "
    script += """
$current=[System.Security.Principal.WindowsIdentity]::GetCurrent().User
$allowed=@($current.Value,'S-1-5-18','S-1-5-32-544')
"""
    if secure:
        script += """
$acl=New-Object System.Security.AccessControl.FileSecurity
$acl.SetOwner($current)
$acl.SetAccessRuleProtection($true,$false)
foreach($sid in $allowed) {
 $identity=New-Object System.Security.Principal.SecurityIdentifier($sid)
 $rule=New-Object System.Security.AccessControl.FileSystemAccessRule($identity,'FullControl','Allow')
 $acl.AddAccessRule($rule)
}
Set-Acl -LiteralPath $p -AclObject $acl
"""
    script += """
$acl=Get-Acl -LiteralPath $p
if($acl.GetOwner([System.Security.Principal.SecurityIdentifier]).Value -ne $current.Value) { throw 'owner' }
if(-not $acl.AreAccessRulesProtected) { throw 'inheritance' }
$hasCurrent=$false
foreach($rule in $acl.GetAccessRules($true,$true,[System.Security.Principal.SecurityIdentifier])) {
 if($rule.AccessControlType -eq 'Allow') {
  if($allowed -notcontains $rule.IdentityReference.Value) { throw 'broad-access' }
  if($rule.IdentityReference.Value -eq $current.Value -and (($rule.FileSystemRights -band [System.Security.AccessControl.FileSystemRights]::ReadData) -ne 0)) { $hasCurrent=$true }
 }
}
if(-not $hasCurrent) { throw 'missing-user-read' }
"""
    encoded = base64.b64encode(script.encode('utf-16le')).decode('ascii')
    try:
        result = subprocess.run(['powershell.exe','-NoProfile','-NonInteractive','-EncodedCommand',encoded],
                                capture_output=True, timeout=30, check=False)
    except (OSError, subprocess.SubprocessError):
        raise ValueError('Windows private key ACL verification unavailable') from None
    if result.returncode != 0:
        raise ValueError('Windows private key ACL is not restricted')


def check_key_permissions(path):
    if WINDOWS:
        windows_key_acl(path)
    elif stat.S_IMODE(Path(path).stat().st_mode) & 0o077:
        raise ValueError('private key permissions must deny group and other access')


def _write(path, data, *, private_key=False):
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, 'wb') as stream:
        if private_key and WINDOWS:
            windows_key_acl(Path(path), secure=True)
        stream.write(data)
        stream.flush()
        os.fsync(stream.fileno())


def _public(key):
    return key.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)


def create_recipient(private_path):
    path = _private_path(private_path)
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    private = X25519PrivateKey.generate()
    public = _public(private)
    recipient = {'version': VERSION, 'public_key': _b64(public),
                 'recipient_sha256': hashlib.sha256(public).hexdigest()}
    raw = private.private_bytes(serialization.Encoding.Raw, serialization.PrivateFormat.Raw,
                                serialization.NoEncryption())
    _write(path, _json({'version': VERSION, 'private_key': _b64(raw), **recipient}) + b'\n', private_key=True)
    return recipient


def validate_recipient(recipient):
    if set(recipient) != {'version', 'public_key', 'recipient_sha256'} or recipient['version'] != VERSION:
        raise ValueError('invalid recipient metadata')
    public = _decode(recipient['public_key'])
    if len(public) != 32 or hashlib.sha256(public).hexdigest() != recipient['recipient_sha256']:
        raise ValueError('invalid recipient fingerprint')
    # Reject low-order public keys before any provider work.
    X25519PrivateKey.generate().exchange(X25519PublicKey.from_public_bytes(public))
    return public


def _binding(plan_hash, run_id):
    if not isinstance(plan_hash, str) or not re.fullmatch('[0-9a-f]{64}', plan_hash):
        raise ValueError('invalid plan hash')
    if not isinstance(run_id, str) or not re.fullmatch('[0-9]+', run_id):
        raise ValueError('invalid run id')


def _key(private, public, aad):
    shared = private.exchange(X25519PublicKey.from_public_bytes(public))
    return HKDF(algorithm=hashes.SHA256(), length=32, salt=None,
                info=VERSION.encode() + b'/' + aad).derive(shared)


def _archive(source):
    source = _private_path(source)
    if not source.is_dir():
        raise ValueError('missing evidence directory')
    buffer = io.BytesIO()
    count, total = 0, 0
    with zipfile.ZipFile(buffer, 'w', zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(source.rglob('*')):
            if path.is_symlink():
                raise ValueError('symlink in evidence directory')
            if path.is_dir():
                continue
            if not path.is_file():
                raise ValueError('nonregular evidence entry')
            count += 1
            total += path.stat().st_size
            if count > MAX_FILES or total > MAX_BYTES:
                raise ValueError('archive limit exceeded')
            archive.write(path, path.relative_to(source).as_posix())
    return buffer.getvalue(), count


def seal_directory(source, recipient, output, plan_hash, run_id):
    _binding(plan_hash, run_id)
    public = validate_recipient(recipient)
    output = _private_path(output)
    if output.exists():
        raise FileExistsError('package output exists')
    if Path(source).resolve() == output or Path(source).resolve() in output.parents:
        raise ValueError('package output must be outside evidence source')
    raw, count = _archive(source)
    header = {'version': VERSION, 'plan_hash': plan_hash, 'run_id': run_id,
              'archive_sha256': hashlib.sha256(raw).hexdigest(),
              'recipient_sha256': recipient['recipient_sha256']}
    aad = _json(header)
    ephemeral, nonce = X25519PrivateKey.generate(), os.urandom(12)
    ciphertext = AESGCM(_key(ephemeral, public, aad)).encrypt(nonce, raw, aad)
    wire = _json({**header, 'ephemeral_public_key': _b64(_public(ephemeral)),
                  'nonce': _b64(nonce), 'ciphertext': _b64(ciphertext)}) + b'\n'
    receipt = {**header, 'encrypted': True, 'archive_files': count,
               'archive_bytes': len(raw), 'envelope_sha256': hashlib.sha256(wire).hexdigest()}
    output.mkdir(parents=True, mode=0o700)
    _write(output / 'evidence.enc.json', wire)
    _write(output / 'receipt.json', _json(receipt) + b'\n')
    return receipt


def extract_archive(data, destination):
    """Validate all entries and their CRCs before creating any destination."""
    destination = _private_path(destination)
    if destination.exists():
        raise FileExistsError('archive destination exists')
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        names, contents, total = set(), [], 0
        for item in archive.infolist():
            path = PurePosixPath(item.filename)
            mode = item.external_attr >> 16
            if (not item.filename or path.is_absolute() or '..' in path.parts
                    or '\\' in item.filename or ':' in item.filename or path.as_posix() != item.filename.rstrip('/')
                    or path.as_posix() in names or stat.S_ISLNK(mode)
                    or stat.S_IFMT(mode) not in (0, stat.S_IFREG, stat.S_IFDIR)):
                raise ValueError('unsafe archive entry')
            names.add(path.as_posix())
            total += item.file_size
            if total > MAX_BYTES or len(names) > MAX_FILES:
                raise ValueError('archive limit exceeded')
            contents.append((path, item.is_dir(), archive.read(item)))
        files = {path for path, is_dir, _ in contents if not is_dir}
        if any(parent in files for path, _, _ in contents for parent in path.parents):
            raise ValueError('conflicting archive paths')
    destination.mkdir(parents=True, mode=0o700)
    for path, is_dir, content in contents:
        target = destination / path
        if is_dir:
            target.mkdir(parents=True, exist_ok=True, mode=0o700)
        else:
            target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            _write(target, content)


def decrypt_file(envelope_path, private_path, destination, plan_hash, run_id):
    _binding(plan_hash, run_id)
    destination = _private_path(destination)
    if destination.exists():
        raise FileExistsError('archive destination exists')
    envelope = json.loads(Path(envelope_path).read_bytes())
    private_path = _private_path(private_path)
    check_key_permissions(private_path)
    private = json.loads(private_path.read_bytes())
    key = X25519PrivateKey.from_private_bytes(_decode(private['private_key']))
    header_keys = ('version', 'plan_hash', 'run_id', 'archive_sha256', 'recipient_sha256')
    header = {name: envelope[name] for name in header_keys}
    if (header['version'] != VERSION or header['plan_hash'] != plan_hash or header['run_id'] != run_id
            or header['recipient_sha256'] != hashlib.sha256(_public(key)).hexdigest()):
        raise ValueError('evidence identity mismatch')
    aad = _json(header)
    try:
        raw = AESGCM(_key(key, _decode(envelope['ephemeral_public_key']), aad)).decrypt(
            _decode(envelope['nonce']), _decode(envelope['ciphertext']), aad)
    except InvalidTag as exc:
        raise ValueError('evidence authentication failed') from exc
    if hashlib.sha256(raw).hexdigest() != header['archive_sha256']:
        raise ValueError('archive checksum mismatch')
    extract_archive(raw, destination)
    return {'status': 'decrypted', 'plan_hash': plan_hash, 'run_id': run_id,
            'archive_sha256': header['archive_sha256']}


def validate_approval_gate(*, approval, parent_commit, changed_paths, commit_message, attempt, plan_hash):
    """An approval-only child commit authorizes exactly its reviewed parent code."""
    expected = {'approved': True, 'plan_hash': plan_hash,
                'model_id': 'gpt-4.1-mini-2025-04-14', 'max_calls': 90, 'max_cost_usd': .72}
    if (attempt != '1' or commit_message.strip() != 'V5_APPROVED_PLAN=' + plan_hash
            or changed_paths != ['ops/v5-approved.json'] or not isinstance(approval, dict)
            or set(approval) != {'approved_code_commit', 'transport_approval'}
            or not re.fullmatch('[0-9a-f]{40}', parent_commit)
            or approval['approved_code_commit'] != parent_commit
            or approval['transport_approval'] != expected
            or approval['transport_approval'].get('approved') is not True
            or type(approval['transport_approval'].get('max_calls')) is not int):
        raise ValueError('separate exact-code paid approval required')
    return expected
