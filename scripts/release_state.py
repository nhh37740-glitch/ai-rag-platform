"""Snapshot stopped RAG volumes and restore images plus data on release failure.

Run as root on the Docker host. Shared quota and model cache are never restored.
"""
from __future__ import annotations
import argparse
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import shutil
import subprocess
import tarfile
import time

PROFILES = {
    'private': ('ai-rag', 'compose.yaml', 'ai-rag-platform:local', ['ai-rag-agent-1'],
                ['ai-rag_agent-state', 'ai-rag_user-notebooks', 'ai-rag_agent-files']),
    'public': ('ai-rag-public', 'compose.public-demo.yaml', 'ai-rag-public:local', ['ai-rag-public-agent-1'],
               ['ai-rag-public_public-demo-state']),
    'admin': ('ai-rag-admin', 'compose.admin.yaml', 'ai-rag-admin:local', ['ai-rag-admin-agent-1', 'ai-rag-admin-login-1'],
              ['ai-rag-admin_admin-state', 'ai-rag-admin_admin-notebooks', 'ai-rag-admin_admin-files']),
}
BACKUP_ROOT = Path('/home/ubuntu/backups/ai-rag')

def docker(*args):
    return subprocess.check_output(['docker', *args], text=True).strip()

def digest(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest() if hasattr(hashlib, 'file_digest') else _hash(stream)

def _hash(stream):
    value=hashlib.sha256()
    for block in iter(lambda: stream.read(1024*1024), b''): value.update(block)
    return value.hexdigest()

def volume_path(name):
    allowed={name for profile in PROFILES.values() for name in profile[4]}
    if name not in allowed: raise ValueError('Volume outside release scope')
    root=Path(docker('info','--format','{{.DockerRootDir}}')).resolve()
    data=json.loads(docker('volume','inspect',name))[0]
    expected=root/'volumes'/name/'_data'
    actual=Path(data['Mountpoint'])
    if data['Driver']!='local' or actual.resolve()!=expected or actual.is_symlink():
        raise ValueError('Unexpected volume path or driver')
    return actual

def validate_member(member):
    name=PurePosixPath(member.name)
    if name.is_absolute() or '..' in name.parts or not name.parts or name.parts[0]!='data':
        raise ValueError('Unsafe snapshot path')
    if not (member.isfile() or member.isdir()):
        raise ValueError('Snapshot contains links or special files; stop before release')
    return member

def archive_volume(source, target):
    with tarfile.open(target, 'x') as archive:
        archive.add(source, arcname='data', recursive=True, filter=validate_member)
    with target.open('rb') as stream: os.fsync(stream.fileno())
    return digest(target)

def restore_volume(target, archive_path, expected_digest):
    if digest(archive_path)!=expected_digest: raise ValueError('Snapshot checksum mismatch')
    with tarfile.open(archive_path) as archive:
        for member in archive.getmembers(): validate_member(member)
        for item in target.iterdir():
            if item.is_dir() and not item.is_symlink(): shutil.rmtree(item)
            else: item.unlink()
        # Files came from our regular-file-only snapshot. Keep numeric UID/GID.
        for member in archive.getmembers():
            if member.name=='data':
                os.chmod(target,member.mode)
                if os.geteuid()==0: os.chown(target,member.uid,member.gid)
                continue
            member.name=member.name[len('data/'):]
            archive.extract(member, target, set_attrs=True, numeric_owner=True)

def environment(profile, container):
    labels=container['Config'].get('Labels') or {}
    if profile=='private':
        return {'RAG_MODEL_ENV_FILE':labels['dev-knowledge.model-env-file']}
    if profile=='public':
        return {'PUBLIC_DEMO_ENV_FILE':labels['dev-knowledge.public-env-file'],
                'PUBLIC_DEMO_PROVIDER':labels['dev-knowledge.public-provider']}
    return {'RAG_ADMIN_ENV_FILE':labels['dev-knowledge.admin-env-file'],
            'RAG_MODEL_ENV_FILE':labels['dev-knowledge.admin-model-env-file']}

def backup(directory, targets):
    if directory.exists(): raise ValueError('Snapshot already exists; never overwrite')
    directory.mkdir(parents=True,mode=0o700)
    if shutil.disk_usage(directory).free<64*1024*1024: raise RuntimeError('Insufficient backup disk space')
    manifest={'targets':targets,'profiles':{},'volumes':{}}
    stopped=[]
    try:
        for target in targets:
            project,compose,tag,names,volumes=PROFILES[target]
            containers=[json.loads(docker('inspect',name))[0] for name in names]
            if any(c['State']['Status']!='running' or c['State'].get('Paused') for c in containers):
                raise ValueError('Release requires currently running unpaused containers')
            agent=containers[0]
            mounted={m.get('Name') for m in agent['Mounts'] if m['Type']=='volume'}
            if not set(volumes)<=mounted: raise ValueError('Unexpected production mounts')
            manifest['profiles'][target]={'image':agent['Image'],'env':environment(target,agent)}
            docker('image','tag',agent['Image'],tag.split(':')[0]+':state-rollback-'+directory.name)
            for name in names:
                docker('stop','--time','30',name);stopped.append(name)
        for target in targets:
            for name in PROFILES[target][4]:
                manifest['volumes'][name]=archive_volume(volume_path(name),directory/(name+'.tar'))
        temporary=directory/'manifest.tmp'
        temporary.write_text(json.dumps(manifest),encoding='utf-8')
        temporary.replace(directory/'manifest.json')
    except BaseException:
        for name in stopped: docker('start',name)
        raise
    print(json.dumps({'snapshot':'ready','directory':str(directory),'volumes':len(manifest['volumes']),
                      'services_stopped_for_migration':True,'quota_restored':False}))

def restore(directory):
    marker=directory/'manifest.json'
    if not marker.exists():
        print('No completed pre-release snapshot; production untouched by recovery');return
    if (directory/'restored.json').exists(): raise ValueError('Recovery already performed; inspect before repeating')
    manifest=json.loads(marker.read_text())
    if set(manifest['targets'])-set(PROFILES): raise ValueError('Unknown recovery target')
    expected={name for t in manifest['targets'] for name in PROFILES[t][4]}
    if set(manifest['volumes'])!=expected: raise ValueError('Snapshot volume scope mismatch')
    paths={name:volume_path(name) for name in expected}
    # Validate all archives before stopping any service or changing any data.
    for name,checksum in manifest['volumes'].items():
        archive=directory/(name+'.tar')
        if digest(archive)!=checksum: raise ValueError('Snapshot checksum mismatch')
        with tarfile.open(archive) as stream:
            for member in stream.getmembers(): validate_member(member)
    for target in manifest['targets']:
        for name in PROFILES[target][3]: docker('stop','--time','30',name)
    for name,checksum in manifest['volumes'].items(): restore_volume(paths[name],directory/(name+'.tar'),checksum)
    for target in manifest['targets']:
        project,compose,tag,_,_=PROFILES[target]
        prior=manifest['profiles'][target]
        docker('image','tag',prior['image'],tag)
        subprocess.run(['docker','compose','-f',compose,'--project-name',project,'up','-d','--no-build','--force-recreate'],
                       env={**os.environ,**prior['env']},check=True)
        for name in PROFILES[target][3]:
            deadline=time.monotonic()+180
            while time.monotonic()<deadline:
                state=json.loads(docker('inspect',name))[0]['State']
                if state.get('Health',{}).get('Status')=='healthy': break
                if state.get('Health',{}).get('Status')=='unhealthy': raise RuntimeError('Recovered container is unhealthy')
                time.sleep(3)
            else: raise RuntimeError('Recovered container health timed out')
    (directory/'restored.json').write_text(json.dumps({'restored':True,'quota_restored':False}))
    print('Pre-release images and data restored; shared quota preserved')

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('operation',choices=['backup','restore'])
    parser.add_argument('--build',required=True)
    parser.add_argument('--targets',nargs='+',choices=list(PROFILES))
    args=parser.parse_args()
    if not args.build.isdecimal() or os.geteuid()!=0: raise ValueError('Root and numeric Jenkins build are required')
    os.umask(0o077)
    directory=BACKUP_ROOT/('build-'+args.build)
    if args.operation=='backup':
        if not args.targets or len(set(args.targets))!=len(args.targets): raise ValueError('Unique release targets required')
        backup(directory,args.targets)
    else: restore(directory)

if __name__=='__main__': main()
