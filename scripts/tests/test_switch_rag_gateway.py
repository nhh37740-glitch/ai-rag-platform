"""RAG gateway changes only its own route and restores invalid reloads."""
import importlib.util
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / 'switch_rag_gateway.py'
spec = importlib.util.spec_from_file_location('switch_rag_gateway', SCRIPT)
gateway = importlib.util.module_from_spec(spec)
spec.loader.exec_module(gateway)

OLD = '''location /projects/ { proxy_pass http://127.0.0.1:8092/; }
include /etc/nginx/project-rag-admin-route.conf;
location ^~ /projects/apps/rag/ {
    proxy_pass http://127.0.0.1:18106/;
    client_max_body_size 16k;
    limit_except GET POST { deny all; }
}
location /projects/apps/go/ { proxy_pass http://127.0.0.1:18101/; }
'''


def test_switch_keeps_other_projects_and_allows_unified_api():
    new = gateway.updated_route(OLD)
    assert '127.0.0.1:18080/' in new
    assert 'project-rag-admin-route.conf' not in new
    assert 'client_max_body_size 20m;' in new
    assert 'limit_except GET POST' not in new
    assert '127.0.0.1:8092/' in new and '127.0.0.1:18101/' in new
    assert gateway.updated_route(new) == new


def test_unexpected_route_is_rejected():
    with pytest.raises(ValueError):
        gateway.updated_route(OLD.replace('127.0.0.1:18106/', '127.0.0.1:9999/'))


def test_failed_reload_restores_previous_route(tmp_path, monkeypatch):
    route = tmp_path / 'route.conf'; route.write_text(OLD)
    calls = []
    def run(command, check):
        calls.append(command)
        if len(calls) == 2:
            raise RuntimeError('synthetic reload failure')
    monkeypatch.setattr(gateway.subprocess, 'run', run)
    with pytest.raises(RuntimeError):
        gateway.switch(route)
    assert route.read_text() == OLD
    assert calls == [['nginx','-t'],['systemctl','reload','nginx'],
                     ['nginx','-t'],['systemctl','reload','nginx']]
