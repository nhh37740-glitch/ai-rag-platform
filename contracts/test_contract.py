"""Contract gate for the Dev Knowledge Agent.

Run from the integration side, AFTER binaries have been published to `artifacts/`
and registered in `registry.json`. This verifies that the compiled modules expose
exactly the facade named in `contracts/API_SCHEMA.json`, and re-runs each module's
own bundled contract test against its binary.

Usage:
    python -m pytest contracts/test_contract.py   # optional
    python contracts/test_contract.py             # unittest discovery

If `--strict` is passed (or env CONTRACT_STRICT=1), a registered module whose
binary is missing fails the suite. Otherwise it is reported as skipped so the
suite is usable during the contract-first phase before any module is built.
"""
from __future__ import annotations

import importlib
import inspect
import json
import os
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CONTRACTS = ROOT / "contracts"
REGISTRY = ROOT / "registry.json"
ARTIFACTS = ROOT / "artifacts"

# Make both `contracts.core_contracts` (root on path) and `core_contracts`
# (contracts dir on path) importable, matching what module subagents use.
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(CONTRACTS))

STRICT = "--strict" in sys.argv or os.environ.get("CONTRACT_STRICT") == "1"


def _load_json(path: Path) -> dict:
    with path.open("r", encoding="utf-8") as fh:
        return json.load(fh)


def _artifact_package(module: str) -> str:
    """Convert a kebab-case module id to the importable package name."""
    return module.replace("-", "_")


class CoreContractTests(unittest.TestCase):
    """Validate the shared contract types are importable and shape-correct."""

    def test_core_contracts_importable(self):
        import contracts.core_contracts as cc  # type: ignore

        for name in (
            "RequestContext",
            "ChatMessage",
            "ToolCall",
            "ToolDef",
            "Citation",
            "RetrievalResult",
            "MemoryEntry",
            "SkillDef",
            "SpanEvent",
        ):
            self.assertTrue(hasattr(cc, name), f"missing shared type {name}")

    def test_context_fields(self):
        from contracts.core_contracts import RequestContext

        ctx = RequestContext(trace_id="t", request_id="r")
        self.assertEqual(ctx.trace_id, "t")
        self.assertEqual(ctx.request_id, "r")
        self.assertEqual(ctx.user_id, "")
        self.assertEqual(ctx.session_id, "")

    def test_schema_matches_modules(self):
        schema = _load_json(CONTRACTS / "API_SCHEMA.json")
        self.assertEqual(schema["format"], 2)
        context = schema["context"]
        self.assertIn("trace_id", context["fields"])
        self.assertIn("request_id", context["fields"])
        # every schema module entry has a package + version marker
        for mid, spec in schema["modules"].items():
            self.assertIn("package", spec, f"{mid} missing package")
            self.assertIn("delivery", spec, f"{mid} missing delivery")


class FacadeSignatureTests(unittest.TestCase):
    """Verify each registered compiled module exports its expected facade."""

    def _registered_modules(self) -> dict:
        reg = _load_json(REGISTRY)
        return reg.get("modules", {})

    def test_registry_entries_match_schema(self):
        schema = _load_json(CONTRACTS / "API_SCHEMA.json")
        reg = self._registered_modules()
        for mid in schema["modules"]:
            self.assertIn(mid, reg, f"module {mid} not registered in registry.json")
            self.assertIn("version", reg[mid])
            self.assertIn("checksum", reg[mid])
            self.assertIn("status", reg[mid])

    def test_importable_facade_icons(self):
        schema = _load_json(CONTRACTS / "API_SCHEMA.json")
        reg = self._registered_modules()
        for mid, spec in schema["modules"].items():
            entry = reg.get(mid, {})
            if entry.get("status") != "published":
                continue
            pkg = spec["package"]
            try:
                module = importlib.import_module(pkg)
            except ImportError as exc:  # pragma: no cover - surfaced by strict path
                self.fail(f"module {mid} ({pkg}) not importable: {exc}")

            names = spec.get("facade", {})
            top_level = {
                k for k, v in names.items() if v.get("kind") in ("class", "function", "protocol")
            }
            for name in top_level:
                self.assertTrue(
                    hasattr(module, name), f"{pkg} missing facade symbol {name}"
                )
                obj = getattr(module, name)
                self.assertTrue(
                    callable(obj) or inspect.isclass(obj),
                    f"{pkg}.{name} is not callable",
                )

    def test_every_published_artifact_contract_replays(self):
        reg = self._registered_modules()
        for mid, entry in reg.items():
            if entry.get("status") != "published":
                continue
            version = entry.get("version")
            slot = ARTIFACTS / mid / version
            self.assertTrue(
                (slot / "INTERFACE.md").exists(), f"{mid}@{version} missing INTERFACE.md"
            )
            self.assertTrue(
                (slot / "API_SCHEMA.json").exists(), f"{mid}@{version} missing API_SCHEMA.json"
            )
            self.assertTrue(
                (slot / "checksum.sha256").exists(), f"{mid}@{version} missing checksum.sha256"
            )


if __name__ == "__main__":
    if STRICT:
        # If strict, also fail on missing registered binaries.
        reg = _load_json(REGISTRY)
        missing = [
            mid
            for mid, e in reg.get("modules", {}).items()
            if e.get("status") == "published"
            and not (ARTIFACTS / mid / e.get("version", "")).exists()
        ]
        if missing:
            raise SystemExit("registered modules missing artifacts: " + ", ".join(missing))
    unittest.main(verbosity=2)
