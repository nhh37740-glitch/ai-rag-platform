"""Reject unsafe release metadata without spending another model query."""
import importlib.util
from pathlib import Path

import pytest

spec = importlib.util.spec_from_file_location('delivery_public_smoke', Path(__file__).parents[1] / 'smoke_public_demo.py')
public_smoke = importlib.util.module_from_spec(spec)
spec.loader.exec_module(public_smoke)


def responses(model='openrouter/free', limit=20):
    metadata = {'public_demo': True, 'read_only': True, 'provider': 'openrouter',
                'embedding': 'hash', 'model': model, 'free_models_only': True,
                'quota': {'scope': 'site', 'limit': limit, 'used': 3, 'remaining': 17,
                          'reset_at': '2026-10-11T00:00:00+08:00'},
                'suggested_questions': [{'question': 'question'}]}
    return {
        'api/demo': metadata,
        'api/auth/session': {'role': 'guest', 'permissions': ['read', 'query'],
                             'allowed_notebook_ids': ['cmrc2018-demo']},
        'api/notebooks': {'notebooks': [{'id': 'cmrc2018-demo'}]},
        'api/notebooks/cmrc2018-demo/documents': {'documents': [{'source_id': 'cmrc2018-demo/doc'}]},
        'api/demo/documents/doc': {'contexts': ['public context'], 'source_id': 'cmrc2018-demo/doc'},
        'api/trace/private-unknown': [],
    }


def mock_requests(monkeypatch, values):
    calls = []
    def request(base, path, method='GET', payload=None, headers=None):
        calls.append((path, method, payload, headers))
        if method == 'POST' and path == 'api/demo/chat':
            if headers:
                return 403, None
            return 422, None
        if path in values and method == 'GET':
            return 200, values[path]
        return 403, None
    monkeypatch.setattr(public_smoke, 'request', request)
    return calls


def test_live_metadata_checks_do_not_spend_query(monkeypatch):
    calls = mock_requests(monkeypatch, responses())
    public_smoke.smoke('http://local.invalid', 'openrouter', metadata_only=True)
    assert not any(path == 'api/demo/chat' and payload == {'question': 'question'} and not headers
                   for path, _, payload, headers in calls)


@pytest.mark.parametrize('model,limit', [('paid/model', 20), ('openrouter/free', 40)])
def test_release_checks_reject_paid_model_or_larger_budget(monkeypatch, model, limit):
    mock_requests(monkeypatch, responses(model=model, limit=limit))
    with pytest.raises(AssertionError):
        public_smoke.smoke('http://local.invalid', 'openrouter', metadata_only=True)
