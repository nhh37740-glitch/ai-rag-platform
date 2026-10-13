"""Move only the RAG web route to the unified service after it is healthy."""
from __future__ import annotations

import os
from pathlib import Path
import subprocess
import tempfile

ROUTE = Path('/etc/nginx/project-apps-route.conf')
OLD_INCLUDE = 'include /etc/nginx/project-rag-admin-route.conf;\n'
OLD_UPSTREAM = 'proxy_pass http://127.0.0.1:18106/;'
NEW_UPSTREAM = 'proxy_pass http://127.0.0.1:18080/;'
RAG_LOCATION = 'location ^~ /projects/apps/rag/ {'


def updated_route(text: str) -> str:
    start = text.index(RAG_LOCATION)
    end = text.index('\n}', start) + 2
    block = text[start:end]
    if OLD_INCLUDE not in text and NEW_UPSTREAM in block and OLD_UPSTREAM not in block:
        return text
    if text.count(OLD_INCLUDE) != 1 or block.count(OLD_UPSTREAM) != 1:
        raise ValueError('RAG gateway layout differs; no route changed')
    block = block.replace(OLD_UPSTREAM, NEW_UPSTREAM)
    block = block.replace('client_max_body_size 16k;', 'client_max_body_size 20m;')
    block = block.replace('    limit_except GET POST { deny all; }\n', '')
    return text[:start].replace(OLD_INCLUDE, '') + block + text[end:]


def atomic_write(path: Path, content: str, mode: int) -> None:
    with tempfile.NamedTemporaryFile('w', encoding='utf-8', dir=path.parent,
                                     prefix='.rag-route-', delete=False) as stream:
        temporary = Path(stream.name)
        stream.write(content)
        stream.flush()
        os.fsync(stream.fileno())
    try:
        os.chmod(temporary, mode)
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def switch(route: Path = ROUTE) -> bool:
    old = route.read_text(encoding='utf-8')
    new = updated_route(old)
    if new == old:
        return False
    mode = route.stat().st_mode & 0o777
    atomic_write(route, new, mode)
    try:
        subprocess.run(['nginx', '-t'], check=True)
        subprocess.run(['systemctl', 'reload', 'nginx'], check=True)
    except Exception:
        atomic_write(route, old, mode)
        subprocess.run(['nginx', '-t'], check=True)
        subprocess.run(['systemctl', 'reload', 'nginx'], check=True)
        raise
    return True


if __name__ == '__main__':
    print('RAG gateway switched' if switch() else 'RAG gateway already uses unified service')
