import importlib.util
from pathlib import Path
import sys,unittest,tempfile,io,zipfile
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
class CapsuleTests(unittest.TestCase):
 def module(self):
  self.assertIsNotNone(importlib.util.find_spec('capsule'),'capsule missing')
  import capsule
  return capsule
 def test_private_roundtrip(self):
  c=self.module();key,pub=c.keypair();data=b'private-query-labels'
  wire=c.seal(pub,data,b'input:1');self.assertNotIn(data,wire)
  self.assertEqual(c.unseal(key,wire,b'input:1'),data)
 def test_wrong_recipient_and_wrong_binding_rejected(self):
  c=self.module();k,p=c.keypair();k2,_=c.keypair();wire=c.seal(p,b'private',b'input:1')
  with self.assertRaises(Exception):c.unseal(k2,wire,b'input:1')
  with self.assertRaises(Exception):c.unseal(k,wire,b'output:1')
 def test_tampering_rejected(self):
  c=self.module();k,p=c.keypair();wire=bytearray(c.seal(p,b'private',b'ctx'));wire[-1]^=1
  with self.assertRaises(Exception):c.unseal(k,bytes(wire),b'ctx')
 def test_archive_escape_rejected_before_any_write(self):
  c=self.module();b=io.BytesIO()
  with zipfile.ZipFile(b,'w') as z:z.writestr('good',b'ok');z.writestr('../outside',b'bad')
  with tempfile.TemporaryDirectory() as d:
   with self.assertRaises(ValueError):c.extract(b.getvalue(),Path(d)/'out')
   self.assertFalse((Path(d)/'out/good').exists())
 def test_extract_refuses_existing_target(self):
  c=self.module()
  with tempfile.TemporaryDirectory() as d:
   with self.assertRaises(FileExistsError):c.extract(b'',Path(d))
if __name__=='__main__':unittest.main()
