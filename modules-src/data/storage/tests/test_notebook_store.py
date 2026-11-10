import sqlite3, tempfile, unittest
from pathlib import Path
from core_specifications import RequestContext
from storage import NotebookStore
CTX=RequestContext("t","r","owner")
class NotebookStoreTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
  self.store=NotebookStore(str(Path(self.tmp.name)/"one.sqlite")); self.addCleanup(self.store.close)
  self.store.register_user(CTX,"owner"); self.store.register_user(CTX,"alice"); self.store.register_user(CTX,"guest"); self.store._conn.execute("UPDATE users SET is_guest=1 WHERE id=?",("guest",))
  self.store.create_notebook(CTX,{"id":"book","owner_user_id":"owner","name":"中文","created_at":"now"})
 def test_six_table_schema_and_member_roles(self):
  names={r[0] for r in self.store._conn.execute("select name from sqlite_master where type='table' and name not like 'sqlite_%'")}
  self.assertEqual(names,{"users","notebooks","notebook_members","documents","conversations","agent_data"})
  self.store.put_member(CTX,"book","alice","editor"); self.assertEqual(self.store.list_members(CTX,"book"),[{"user_id":"alice","role":"editor"}])
  self.store.put_member(CTX,"book","alice","viewer"); self.assertEqual(self.store.membership_snapshot(CTX,"book")["members"][0]["role"],"viewer")
  with self.assertRaises(ValueError): self.store.put_member(CTX,"book","alice","manager")
  with self.assertRaises(ValueError): self.store.put_member(CTX,"book","missing","viewer")
  self.store.put_member(CTX,"book","guest","viewer")
  self.assertEqual(self.store.membership_snapshot(CTX,"book")["members"][-1],{"user_id":"guest","role":"viewer"})
  with self.assertRaises(ValueError): self.store.put_member(CTX,"book","guest","editor")
  with self.assertRaises(ValueError): self.store.create_notebook(CTX,{"id":"guest-book","owner_user_id":"guest","name":"guest"})
 def test_notebook_crud_and_foreign_keys(self):
  self.assertEqual(self.store.get_notebook(CTX,"book")["owner_user_id"],"owner")
  self.store.update_notebook(CTX,"book","new name"); self.assertEqual(self.store.get_notebook(CTX,"book")["name"],"new name")
  with self.assertRaises(ValueError): self.store.create_notebook(CTX,{"id":"bad","owner_user_id":"absent","name":"bad"})
  self.store.delete_notebook(CTX,"book"); self.assertIsNone(self.store.get_notebook(CTX,"book"))
 def test_matching_columns_but_wrong_check_constraint_rejected(self):
  self.store.close()
  conn=sqlite3.connect(self.store._conn if False else str(Path(self.tmp.name)/"one.sqlite"))
  conn.execute("PRAGMA foreign_keys=OFF")
  conn.execute("DROP TABLE notebook_members")
  conn.execute("CREATE TABLE notebook_members(notebook_id TEXT NOT NULL REFERENCES notebooks(id) ON DELETE CASCADE,user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,role TEXT NOT NULL CHECK(role IN ('editor','manager')),PRIMARY KEY(notebook_id,user_id))")
  conn.commit(); conn.close()
  with self.assertRaises(RuntimeError): NotebookStore(str(Path(self.tmp.name)/"one.sqlite"))
 def test_old_schema_rejected_without_alter(self):
  path=str(Path(self.tmp.name)/"legacy.sqlite")
  import sqlite3
  conn=sqlite3.connect(path); conn.execute("CREATE TABLE vectors(source_id TEXT,text TEXT,embedding TEXT)"); conn.commit(); conn.close()
  with self.assertRaises(RuntimeError): NotebookStore(path)
  conn=sqlite3.connect(path); self.assertEqual(conn.execute("select name from sqlite_master where type='table'").fetchall(),[("vectors",)]); conn.close()
if __name__=="__main__": unittest.main()
