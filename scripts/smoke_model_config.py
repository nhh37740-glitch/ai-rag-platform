"""Check server model settings without spending a daily query or printing secrets."""
import json
import sys
import urllib.request
from pathlib import Path


def check(model, env_file):
    settings = dict(line.split('=', 1) for line in Path(env_file).read_text().splitlines()
                    if '=' in line and not line.startswith('#'))
    expected = settings.get('LLM_PROVIDER', '').strip()
    if expected:
        assert model['provider'] == expected, 'runtime provider does not match release configuration'
    if expected == 'openrouter':
        assert model['model'] == 'openrouter/free' and model['free_models_only'] is True
        assert model['server_key_configured'] is True
        quota = model['quota']
        assert quota['scope'] == 'site' and quota['limit'] == 20
        assert 0 <= quota['used'] <= 20 and quota['remaining'] == 20 - quota['used']
    return model


if __name__ == '__main__':
    with urllib.request.urlopen(sys.argv[1].rstrip('/') + '/api/llm/config', timeout=15) as response:
        model = check(json.load(response), sys.argv[2])
    print(json.dumps({'model_config_smoke': 'passed', 'provider': model['provider'],
                      'model': model['model'], 'quota': model.get('quota')}))
