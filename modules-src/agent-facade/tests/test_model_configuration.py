import unittest
from agent_facade import resolve_model_config
from core_specifications import RequestContext,ModelConfiguration

CTX=RequestContext("trace","request")
class ModelPolicyTests(unittest.TestCase):
    def test_free_default_and_explicit_free_variant_and_secret_repr(self):
        value=resolve_model_config(CTX,{"OPENROUTER_API_KEY":"private-test-sentinel"},True)
        self.assertIsInstance(value,ModelConfiguration)
        self.assertEqual(value.model,"openrouter/free")
        self.assertNotIn('private-test-sentinel',repr(value))
        self.assertEqual(value.base_url,'https://openrouter.ai/api/v1')
        for model in ['openrouter/auto','vendor/paid','vendor/model:free:nitro']:
            with self.assertRaises(ValueError):resolve_model_config(CTX,{'OPENROUTER_API_KEY':'placeholder','OPENROUTER_MODEL':model})
        self.assertEqual(resolve_model_config(CTX,{'OPENROUTER_API_KEY':'placeholder','OPENROUTER_MODEL':'vendor/model:free'}).model,'vendor/model:free')

    def test_mock_never_retains_key_and_missing_provider_secret_fails(self):
        self.assertEqual(resolve_model_config(CTX,{'LLM_PROVIDER':'mock','OPENROUTER_API_KEY':'unused'}).api_key,'')
        for provider in ['openrouter','deepseek','unknown']:
            with self.assertRaises(ValueError):resolve_model_config(CTX,{'LLM_PROVIDER':provider})
