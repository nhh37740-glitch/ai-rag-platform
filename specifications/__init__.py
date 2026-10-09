"""Shared contract layer.

Exposes the shared types (``specifications.core_specifications``) and acts as the single
source of truth for all module interfaces. Modules must import types from here;
if a module imports ``core_specifications`` directly it will resolve as long as this
directory is on ``sys.path``.
"""
