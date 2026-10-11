"""Compatibility adapter; model policy belongs to agent-facade."""
from typing import Mapping
from agent_facade import resolve_model_config
from core_specifications import RequestContext, ModelConfiguration


class ModelConfig:
    @classmethod
    def from_env(cls, env: Mapping[str, str], public: bool = False) -> ModelConfiguration:
        return resolve_model_config(RequestContext("model-config", "model-config"), dict(env), public)
