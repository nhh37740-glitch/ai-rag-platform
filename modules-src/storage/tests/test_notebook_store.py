import sqlite3
import tempfile
import unittest
from pathlib import Path
from core_specifications import RequestContext, NotebookStorePort
from storage import NotebookStore

CTX=RequestContext("trace","request")
ROLES={"viewer":["read","query"],"editor":["read","query","import_document"]}

class NotebookStoreTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.path=str(Path(self.temp.name)/"notebook.sqlite")
        self.store=NotebookStore(self.path);self.addCleanup(self.store.close)
        self.store.configure_roles(CTX,ROLES)
        for uid in ["owner","alice","bob"]:self.store.register_user(CTX,uid)
        self.meta={"id":"book-a","owner_user_id":"owner","name":"中文笔记本","description":"保留文档","created_at":"2026-10-11","is_public":False}
        self.store.create_notebook(CTX,self.meta)

    def test_relational_schema_constraints_and_transaction_rollback(self):
        self.assertIsInstance(self.store,NotebookStorePort)
        self.assertEqual(self.store._conn.execute('PRAGMA foreign_keys').fetchone()[0],1)
        self.assertGreaterEqual(len(self.store._conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()),7)
        for uid,role in [("unknown","viewer"),("alice","unknown")]:
            with self.assertRaises(ValueError):self.store.put_member(CTX,"book-a",uid,role,0)
            self.assertEqual(self.store.membership_snapshot(CTX,"book-a")["revision"],0)
        with self.assertRaises(ValueError):self.store.create_notebook(CTX,self.meta)
        self.assertEqual(len(self.store.list_notebooks(CTX)),1)

    def test_compare_and_swap_across_connections_and_closed_lifecycle(self):
        other=NotebookStore(self.path);self.addCleanup(other.close)
        snap=other.membership_snapshot(CTX,"book-a")
        self.assertTrue(self.store.put_member(CTX,"book-a","alice","viewer",0))
        self.assertFalse(other.put_member(CTX,"book-a","bob","editor",snap['revision']))
        self.assertTrue(other.put_member(CTX,"book-a","bob","editor",1))
        self.assertEqual(len(self.store.membership_snapshot(CTX,"book-a")['members']),2)
        other.close();other.close()
        with self.assertRaises(RuntimeError):other.list_notebooks(CTX)

    def test_legacy_migration_is_atomic_and_does_not_restore_revoked_member(self):
        meta={**self.meta,"id":"old-book"}
        with self.assertRaises(ValueError):self.store.migrate_notebook(CTX,meta,[{"user_id":"new-user","role":"bad-role"}])
        self.assertIsNone(self.store.get_notebook(CTX,"old-book"))
        self.assertNotIn('new-user',[u['user_id'] for u in self.store.list_users(CTX)])
        legacy=[{"user_id":"legacy-user","role":"viewer"}]
        self.store.migrate_notebook(CTX,meta,legacy)
        self.assertTrue(self.store.delete_member(CTX,"old-book","legacy-user",0))
        self.store.migrate_notebook(CTX,{**meta,"name":"旧名称"},legacy)
        self.assertEqual(self.store.get_notebook(CTX,"old-book")['name'],meta['name'])
        self.assertEqual(self.store.membership_snapshot(CTX,"old-book")['members'],[])

    def test_directory_edit_archive_preserves_members_and_seeded_roles(self):
        self.store.put_member(CTX,"book-a","alice","editor",0)
        self.store.update_notebook(CTX,"book-a","新名称","新说明")
        self.store.set_archived(CTX,"book-a",True)
        with self.assertRaises(ValueError):self.store.update_notebook(CTX,"book-a","x","")
        self.store.set_archived(CTX,"book-a",False)
        self.assertEqual(self.store.get_notebook(CTX,"book-a")['name'],"新名称")
        self.assertEqual(len(self.store.membership_snapshot(CTX,"book-a")['members']),1)
        self.store.configure_roles(CTX,{"viewer":["write"]})
        self.assertEqual(self.store.role_permissions(CTX,"viewer"),["query","read"])
        with self.assertRaises(ValueError):self.store.register_user(CTX,"alice' OR 1=1 --")
