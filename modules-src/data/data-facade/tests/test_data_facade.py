import sqlite3, tempfile, unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from core_specifications import DataServicePort, RequestContext
from data_facade import DataService
CTX=RequestContext("t","r","alice","s")
OTHER=RequestContext("t","r","bob","s")
class DataServiceTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
  self.path=str(Path(self.tmp.name)/"state.sqlite"); self.data=DataService(self.path); self.addCleanup(self.data.close,CTX)
 def test_one_connection_one_file_six_tables(self):
  self.assertIsInstance(self.data,DataServicePort)
  stores=[self.data.memory_store(CTX),self.data.vector_store(CTX),self.data.state_db(CTX),self.data.notebook_store(CTX)]
  self.assertEqual(len({id(s._conn) for s in stores}),1)
  self.assertEqual(len({id(s._lock) for s in stores}),1)
  names={r[0] for r in stores[0]._conn.execute("select name from sqlite_master where type='table' and name not like 'sqlite_%'")}
  self.assertEqual(names,{"users","notebooks","notebook_members","documents","conversations","agent_data"})
  self.assertEqual([p.name for p in Path(self.tmp.name).iterdir()],["state.sqlite"])
 def test_user_crud_and_active(self):
  self.data.create_user(CTX,{"id":"alice","username":"Alice","password_hash":"hash"})
  self.assertEqual(self.data.get_user(CTX,"alice")["username"],"Alice")
  self.assertEqual(self.data.get_user_by_username(CTX,"Alice")["id"],"alice")
  self.assertNotIn("password_hash",self.data.list_users(CTX)[0])
  self.assertEqual(len(self.data.list_users(CTX)),1)
  self.data.set_user_active(CTX,"alice",False); self.assertEqual(self.data.get_user(CTX,"alice")["is_active"],0)
  self.assertEqual(self.data.list_users(CTX),[])
  self.assertEqual(len(self.data.list_users(CTX,active_only=False)),1)
 def test_quota_aggregates_all_users_and_atomic_limit(self):
  self.data.create_user(CTX,{"id":"alice","username":"alice"}); self.data.create_user(CTX,{"id":"bob","username":"bob"})
  def reserve(i): return self.data.reserve_site_quota(CTX if i%2==0 else OTHER,"2026-10-11",20)
  with ThreadPoolExecutor(max_workers=8) as pool: results=list(pool.map(reserve,range(64)))
  self.assertEqual(sorted(x for x in results if x is not None),list(range(1,21)))
  self.assertEqual(self.data.site_quota_used(CTX,"2026-10-11"),20)
  self.assertEqual(self.data.reserve_site_quota(CTX,"2026-10-12",1),1)
  self.assertEqual(self.data.site_quota_used(CTX,"2026-10-12"),1)
 def test_conversation_crud_user_scope(self):
  self.data.create_user(CTX,{"id":"alice","username":"alice"}); self.data.create_user(CTX,{"id":"bob","username":"bob"})
  value={"id":"c1","title":"中文","notebook_id":["b","a"],"messages":[{"role":"user","content":"hello"}]}
  self.data.save_conversation(CTX,value)
  self.data.save_conversation(CTX,{"id":"c2","title":"other scope","notebook_id":["c"],"messages":[]})
  self.assertEqual(self.data.get_conversation(CTX,"c1","alice")["notebook_id"],["a","b"])
  self.assertEqual(len(self.data.list_conversations(CTX,"alice")),2)
  self.assertEqual(len(self.data.list_conversations(CTX,"alice",'["a", "b"]')),1)
  with self.assertRaises(PermissionError): self.data.get_conversation(CTX,"c1","bob")
  self.data.delete_conversation(CTX,"c1","alice"); self.assertIsNone(self.data.get_conversation(CTX,"c1","alice"))
 def test_shared_agent_data_memory_state_vector_and_reopen(self):
  self.data.create_user(CTX,{"id":"alice","username":"alice"})
  self.data.memory_store(CTX).write(CTX,"session","x","remember me")
  self.data.state_db(CTX).set(CTX,"theme",{"x":1})
  self.data.set_agent_data(CTX,"agent","key",'{"value":2}')
  self.data.vector_store(CTX).add("book/doc",["chunk"],[[1,0]])
  self.data.create_notebook(CTX,{"id":"book","owner_user_id":"alice","name":"Book"})
  self.data.close(CTX); self.data=DataService(self.path)
  self.assertEqual(self.data.memory_store(CTX).get(CTX,"session","x").content,"remember me")
  self.assertEqual(self.data.state_db(CTX).get(CTX,"theme"),{"x":1})
  self.assertEqual(self.data.get_agent_data(CTX,"agent","key")["content"],'{"value":2}')
  self.assertEqual(self.data.vector_store(CTX).document_chunks("book/doc"),["chunk"])
  self.assertEqual(self.data.get_notebook(CTX,"book")["name"],"Book")
 def test_old_schema_rejected_without_mutation(self):
  old=str(Path(self.tmp.name)/"old.sqlite"); c=sqlite3.connect(old); c.execute("CREATE TABLE state(user_id TEXT,key TEXT,payload TEXT)"); c.commit(); c.close()
  with self.assertRaises(RuntimeError): DataService(old).initialize(CTX)
  c=sqlite3.connect(old); self.assertEqual(c.execute("select name from sqlite_master where type='table'").fetchall(),[("state",)]); c.close()
 def test_close_before_initialize_and_lifecycle(self):
  self.data.close(CTX); self.data.close(CTX)
  with self.assertRaises(RuntimeError): self.data.initialize(CTX)
if __name__=="__main__": unittest.main()
