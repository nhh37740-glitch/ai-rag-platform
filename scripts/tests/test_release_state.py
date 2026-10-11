"""Verify data rollback restores roles/documents and rejects unsafe snapshots."""
import importlib.util
from pathlib import Path
import sqlite3
import tarfile
import io
import os
import json
from types import SimpleNamespace
import pytest

pytestmark=pytest.mark.skipif(os.name!='posix',reason='Production snapshot operations require a POSIX Docker host')

spec=importlib.util.spec_from_file_location('release_state',Path(__file__).resolve().parents[1]/'release_state.py')
release=importlib.util.module_from_spec(spec);spec.loader.exec_module(release)

def test_snapshot_restores_database_and_documents(tmp_path):
    source=tmp_path/'source';source.mkdir()
    database=source/'notebook.sqlite'
    with sqlite3.connect(database) as connection:
        connection.execute('CREATE TABLE notebook_members(user_id TEXT PRIMARY KEY,role TEXT)')
        connection.execute("INSERT INTO notebook_members VALUES ('synthetic-user','viewer')")
    (source/'legacy.md').write_text('Synthetic migration document',encoding='utf-8')
    archive=tmp_path/'snapshot.tar'
    checksum=release.archive_volume(source,archive)
    with sqlite3.connect(database) as connection:
        connection.execute("UPDATE notebook_members SET role='manager'")
    (source/'legacy.md').unlink();(source/'new.md').write_text('After release')
    release.restore_volume(source,archive,checksum)
    with sqlite3.connect(database) as connection:
        assert connection.execute('SELECT role FROM notebook_members').fetchone()==('viewer',)
        assert connection.execute('PRAGMA integrity_check').fetchone()==('ok',)
    assert (source/'legacy.md').read_text()=='Synthetic migration document'
    assert not (source/'new.md').exists()

def test_corrupt_snapshot_preserves_live_data(tmp_path):
    source=tmp_path/'source';source.mkdir();(source/'live.md').write_text('Preserve me')
    archive=tmp_path/'snapshot.tar';checksum=release.archive_volume(source,archive)
    with archive.open('ab') as stream: stream.write(b'corruption')
    with pytest.raises(ValueError,match='checksum'): release.restore_volume(source,archive,checksum)
    assert (source/'live.md').read_text()=='Preserve me'

@pytest.mark.parametrize('name,kind',[('../escape',tarfile.REGTYPE),('data/../../escape',tarfile.REGTYPE),
                                     ('data/link',tarfile.SYMTYPE),('data/device',tarfile.CHRTYPE)])
def test_unsafe_archive_is_rejected_before_deleting_live_files(tmp_path,name,kind):
    source=tmp_path/'source';source.mkdir();(source/'live.md').write_text('Preserve me')
    archive=tmp_path/'bad.tar'
    with tarfile.open(archive,'w') as stream:
        item=tarfile.TarInfo(name);item.type=kind;stream.addfile(item,io.BytesIO())
    with pytest.raises(ValueError): release.restore_volume(source,archive,release.digest(archive))
    assert (source/'live.md').read_text()=='Preserve me'

def test_shared_quota_and_cache_are_outside_restore_scope():
    names={name for profile in release.PROFILES.values() for name in profile[4]}
    assert 'ai-rag-web-quota' not in names and 'ai-rag_model-cache' not in names
    with pytest.raises(ValueError,match='scope'): release.volume_path('ai-rag-web-quota')

def test_complete_snapshot_restores_selected_service_only(tmp_path,monkeypatch):
    monkeypatch.setattr(release.shutil,'disk_usage',lambda path:SimpleNamespace(free=1024**3))
    volumes={name:tmp_path/name for name in release.PROFILES['private'][4]}
    for path in volumes.values(): path.mkdir();(path/'old.txt').write_text('Before migration')
    calls=[];commands=[]
    def docker(*args):
        calls.append(args)
        if args[0]=='inspect':
            return json.dumps([{'Image':'sha256:old','State':{'Status':'running','Health':{'Status':'healthy'}},
              'Mounts':[{'Type':'volume','Name':name} for name in volumes],
              'Config':{'Labels':{'dev-knowledge.model-env-file':'/private/model.env'}}}])
        return ''
    monkeypatch.setattr(release,'docker',docker)
    monkeypatch.setattr(release,'volume_path',lambda name:volumes[name])
    monkeypatch.setattr(release.subprocess,'run',lambda cmd,**kw:commands.append((cmd,kw)))
    snapshot=tmp_path/'build-101'
    release.backup(snapshot,['private'])
    assert [c for c in calls if c[0]=='stop']==[('stop','--time','30','ai-rag-agent-1')]
    with pytest.raises(ValueError,match='exists'): release.backup(snapshot,['private'])
    for path in volumes.values(): (path/'old.txt').write_text('After migration')
    release.restore(snapshot)
    assert all((path/'old.txt').read_text()=='Before migration' for path in volumes.values())
    assert ('image','tag','sha256:old','ai-rag-platform:local') in calls
    assert len(commands)==1 and 'ai-rag' in commands[0][0] and commands[0][1]['env']['RAG_MODEL_ENV_FILE']=='/private/model.env'
    assert (snapshot/'restored.json').exists()
    with pytest.raises(ValueError,match='already'): release.restore(snapshot)

def test_partial_snapshot_failure_restarts_original_container(tmp_path,monkeypatch):
    monkeypatch.setattr(release.shutil,'disk_usage',lambda path:SimpleNamespace(free=1024**3))
    calls=[]
    def docker(*args):
        calls.append(args)
        if args[0]=='inspect':
            return json.dumps([{'Image':'sha256:old','State':{'Status':'running'},
              'Mounts':[{'Type':'volume','Name':name} for name in release.PROFILES['private'][4]],
              'Config':{'Labels':{'dev-knowledge.model-env-file':'/private/model.env'}}}])
        return ''
    monkeypatch.setattr(release,'docker',docker)
    def missing(name): raise OSError('Synthetic backup read failure')
    monkeypatch.setattr(release,'volume_path',missing)
    snapshot=tmp_path/'build-102'
    with pytest.raises(OSError): release.backup(snapshot,['private'])
    assert ('start','ai-rag-agent-1') in calls and not (snapshot/'manifest.json').exists()
