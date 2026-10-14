import importlib.util,sys,unittest,json,tempfile,hashlib
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
class ContractTests(unittest.TestCase):
 def m(self):
  self.assertIsNotNone(importlib.util.find_spec('execute'),'executor missing')
  import execute
  return execute
 def test_relocation_only_changes_root(self):
  old={'execution_root':'old','config':{'max_calls':7},'requests':[{'payload':'fixed'}]}
  new=dict(old,execution_root='new');self.m().compare_relocation(old,new)
  new['config']={'max_calls':8}
  with self.assertRaises(ValueError):self.m().compare_relocation(old,new)
 def test_manifest_changed_file_rejected(self):
  with tempfile.TemporaryDirectory() as d:
   p=Path(d);(p/'x').write_bytes(b'fixed')
   self.m().verify_files(p,{'x':hashlib.sha256(b'fixed').hexdigest()})
   (p/'x').write_bytes(b'changed')
   with self.assertRaises(ValueError):self.m().verify_files(p,{'x':hashlib.sha256(b'fixed').hexdigest()})
if __name__=='__main__':unittest.main()
