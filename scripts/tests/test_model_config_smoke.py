"""The unified deployment checks model metadata without spending a query."""
import importlib.util
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / 'smoke_model_config.py'
spec = importlib.util.spec_from_file_location('smoke_model_config', SCRIPT)
smoke = importlib.util.module_from_spec(spec)
spec.loader.exec_module(smoke)


def model():
    return {'provider': 'openrouter', 'model': 'openrouter/free',
            'free_models_only': True, 'server_key_configured': True,
            'quota': {'scope': 'site', 'limit': 100, 'used': 3, 'remaining': 97}}


def test_current_model_metadata_is_accepted_without_chat_request(tmp_path):
    config = tmp_path / 'model.env'
    config.write_text('LLM_PROVIDER=openrouter\n')
    assert smoke.check(model(), config)['quota']['remaining'] == 97


@pytest.mark.parametrize('change', [
    {'provider': 'deepseek'}, {'model': 'paid/model'},
    {'quota': {'scope': 'site', 'limit': 20, 'used': 3, 'remaining': 17}},
    {'quota': {'scope': 'site', 'limit': 100, 'used': 3, 'remaining': 98}},
])
def test_wrong_model_or_quota_is_rejected(tmp_path, change):
    config = tmp_path / 'model.env'
    config.write_text('LLM_PROVIDER=openrouter\n')
    candidate = model(); candidate.update(change)
    with pytest.raises(AssertionError):
        smoke.check(candidate, config)
