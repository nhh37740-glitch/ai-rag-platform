"""Shared contract layer.

Exposes the shared types (``contracts.core_contracts``) and acts as the single
source of truth for all module interfaces. Modules must import types from here;
if a module imports ``core_contracts`` directly it will resolve as long as this
directory is on ``sys.path``.
"""
