"""Authenticated research transfer; no API credentials or custom cryptography."""
import io
import os
from pathlib import Path,PurePosixPath
import stat
import zipfile
from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey,X25519PublicKey
from cryptography.hazmat.primitives.kdf.hkdf import HKDF
from cryptography.hazmat.primitives import hashes,serialization
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

MAGIC=b'KSC1'
def keypair():
 private=X25519PrivateKey.generate()
 return private,private.public_key().public_bytes(serialization.Encoding.Raw,serialization.PublicFormat.Raw)
def _key(private,public,context):
 shared=private.exchange(X25519PublicKey.from_public_bytes(public))
 return HKDF(algorithm=hashes.SHA256(),length=32,salt=None,info=b'ko-search-clinic/actions/v1/'+context).derive(shared)
def seal(public,data,context):
 ephemeral,epub=keypair();nonce=os.urandom(12)
 return MAGIC+epub+nonce+AESGCM(_key(ephemeral,public,context)).encrypt(nonce,data,context)
def unseal(private,wire,context):
 if len(wire)<64 or wire[:4]!=MAGIC:raise ValueError('invalid envelope')
 return AESGCM(_key(private,wire[4:36],context)).decrypt(wire[36:48],wire[48:],context)
def extract(data,destination):
 destination=Path(destination)
 if destination.exists():raise FileExistsError('archive destination exists')
 with zipfile.ZipFile(io.BytesIO(data)) as z:
  names=set();total=0
  for item in z.infolist():
   p=PurePosixPath(item.filename)
   if (p.is_absolute() or '..' in p.parts or '\\' in item.filename or ':' in item.filename
       or item.filename in names or stat.S_ISLNK(item.external_attr>>16)):
    raise ValueError('unsafe archive entry')
   names.add(item.filename);total+=item.file_size
   if total>100_000_000 or len(names)>5000:raise ValueError('archive limit')
  destination.mkdir(parents=True,mode=0o700)
  for item in z.infolist():
   target=destination/item.filename
   if item.is_dir():target.mkdir(parents=True,exist_ok=True);continue
   target.parent.mkdir(parents=True,exist_ok=True)
   with target.open('xb') as f:f.write(z.read(item))
   target.chmod(0o600)
def archive(root):
 root=Path(root);buffer=io.BytesIO()
 with zipfile.ZipFile(buffer,'w',zipfile.ZIP_DEFLATED) as z:
  for p in sorted(root.rglob('*')):
   if p.is_file() and not p.is_symlink():z.write(p,p.relative_to(root).as_posix())
 return buffer.getvalue()
