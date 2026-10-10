import unittest

from model_config import ModelConfig


class ModelConfigurationTests(unittest.TestCase):
    def test_openrouter_key_selects_free_router_and_never_exposes_key(self):
        config = ModelConfig.from_env({"OPENROUTER_API_KEY": "private-sentinel", "DEMO_PROVIDER": "mock"}, public=True)
        self.assertEqual(config.provider, "openrouter")
        self.assertEqual(config.model, "openrouter/free")
        self.assertEqual(config.base_url, "https://openrouter.ai/api/v1")
        self.assertNotIn("private-sentinel", repr(config))

    def test_paid_auto_and_suffixed_variants_cannot_be_selected(self):
        for model in ["openrouter/auto", "deepseek/deepseek-chat", "vendor/model:free:nitro", "vendor/model:free,paid", ""]:
            with self.subTest(model=model), self.assertRaises(ValueError):
                ModelConfig.from_env({"OPENROUTER_API_KEY": "inert-placeholder", "OPENROUTER_MODEL": model})
        self.assertEqual(ModelConfig.from_env({"OPENROUTER_API_KEY": "placeholder", "OPENROUTER_MODEL": "vendor/model:free"}).model, "vendor/model:free")

    def test_explicit_mock_disables_real_calls_and_missing_server_key_fails(self):
        self.assertEqual(ModelConfig.from_env({"LLM_PROVIDER": "mock", "OPENROUTER_API_KEY": "unused"}).api_key, "")
        with self.assertRaises(ValueError):
            ModelConfig.from_env({"LLM_PROVIDER": "openrouter"})
