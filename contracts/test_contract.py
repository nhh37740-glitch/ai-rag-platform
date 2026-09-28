"""Contract gate for the Dev Knowledge Agent.

The strict integration gate imports only target-platform extensions from the
registered artifact directories, compares their callable signatures with the
canonical schema, and replays each module's bundled contract test.

Usage:
    python -m pytest contracts/test_contract.py
    CONTRACT_STRICT=1 python contracts/test_contract.py

Without strict mode, compiled checks are skipped when the checkout does not
contain every registered binary. This keeps schema/helper tests usable before
the Linux Jenkins build creates the release artifacts.

Set CONTRACT_STATIC_ONLY=1 to run schema and regression checks without importing
any locally available compiled modules. Jenkins uses strict mode for delivery.
"""
from __future__ import annotations

import ast
import importlib
import importlib.machinery
import importlib.util
import inspect
import json
import os
import sys
import unittest
from pathlib import Path
from types import ModuleType


ROOT = Path(__file__).resolve().parents[1]
CONTRACTS = ROOT / "contracts"
REGISTRY = ROOT / "registry.json"
ARTIFACTS = ROOT / "artifacts"
STRICT = "--strict" in sys.argv or os.environ.get("CONTRACT_STRICT") == "1"
STATIC_ONLY = not STRICT and os.environ.get("CONTRACT_STATIC_ONLY") == "1"
_BINARY_RUNTIME_ACTIVE = False
_PUBLISHED_MODULES: dict[str, dict] = {}

# Make both `contracts.core_contracts` (root on path) and `core_contracts`
# (contracts dir on path) importable, matching the application runtime.
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(CONTRACTS))


def _load_json(path: Path) -> dict:
    with path.open("r", encoding="utf-8") as fh:
        return json.load(fh)


def _artifact_directory(entry: dict) -> Path:
    relative = str(entry.get("path", "")).replace("\\", "/")
    return (ROOT / relative).resolve()


def _has_target_extension(package_directory: Path) -> bool:
    if not package_directory.is_dir():
        return False
    suffixes = tuple(importlib.machinery.EXTENSION_SUFFIXES)
    return any(
        path.is_file()
        and path.name.startswith("__init__")
        and path.name.endswith(suffixes)
        for path in package_directory.iterdir()
    )


def _missing_published_extensions(registry: dict) -> list[str]:
    missing = []
    for module_id, entry in registry.get("modules", {}).items():
        if entry.get("status") != "published":
            continue
        package_directory = _artifact_directory(entry) / str(entry.get("name", ""))
        if not _has_target_extension(package_directory):
            missing.append(module_id)
    return missing


def setUpModule() -> None:
    """Establish the same binary-only import boundary used by the service."""
    global _BINARY_RUNTIME_ACTIVE, _PUBLISHED_MODULES

    registry = _load_json(REGISTRY)
    missing = _missing_published_extensions(registry)
    if STATIC_ONLY or (missing and not STRICT):
        return

    app_directory = str(ROOT / "apps" / "agent-server")
    if app_directory not in sys.path:
        sys.path.insert(0, app_directory)
    runtime_boundary = importlib.import_module("runtime_boundary")
    _PUBLISHED_MODULES = runtime_boundary.enforce_binary_runtime()
    _BINARY_RUNTIME_ACTIVE = True


def _annotation_node(node: ast.AST, *, union_member: bool = False) -> str:
    aliases = {
        "Any": "obj",
        "AsyncIterator": "async iterator",
        "Callable": "callable",
        "Dict": "dict",
        "EmbedFunction": "callable",
        "List": "list",
        "NoneType": "null",
        "Optional": "Optional",
        "Scope": "str|list[str]|null",
        "SearchHit": "tuple[str,str,float]",
        "Tuple": "tuple",
        "Union": "Union",
        "_TraceStore": "TraceStore",
        "null": "null",
    }

    if isinstance(node, ast.Name):
        if node.id == "None":
            return "null" if union_member else "None"
        return aliases.get(node.id, node.id)
    if isinstance(node, ast.Attribute):
        return aliases.get(node.attr, node.attr)
    if isinstance(node, ast.Constant):
        if node.value is None:
            return "null" if union_member else "None"
        return repr(node.value)
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.BitOr):
        parts: list[str] = []

        def append_union(item: ast.AST) -> None:
            if isinstance(item, ast.BinOp) and isinstance(item.op, ast.BitOr):
                append_union(item.left)
                append_union(item.right)
                return
            value = _annotation_node(item, union_member=True)
            parts.extend(part for part in _union_members(value) if part not in parts)

        append_union(node)
        return "|".join(parts)
    if isinstance(node, ast.Subscript):
        base = _annotation_node(node.value)
        raw_items = node.slice.elts if isinstance(node.slice, ast.Tuple) else [node.slice]
        items = [_annotation_node(item) for item in raw_items]
        if base == "Optional":
            return "|".join([*_union_members(items[0]), "null"])
        if base == "Union":
            parts: list[str] = []
            for item in items:
                parts.extend(
                    part
                    for part in _union_members(item.replace("None", "null"))
                    if part not in parts
                )
            return "|".join(parts)
        if base == "callable":
            return "callable"
        if base == "async iterator":
            return f"async iterator[{','.join(items)}]"
        return f"{base}[{','.join(items)}]"
    if isinstance(node, ast.Tuple):
        return ",".join(_annotation_node(item) for item in node.elts)
    return ast.unparse(node)


def _normalize_annotation(annotation: object) -> str | None:
    if annotation is inspect.Signature.empty:
        return None
    if annotation is None or annotation is type(None):
        return "None"
    source = annotation if isinstance(annotation, str) else str(annotation)
    source = source.strip().strip("'\"").replace("typing.", "").replace("collections.abc.", "")
    if source == "callable(decorator)":
        return "callable"
    source = source.replace("async iterator[", "AsyncIterator[")
    try:
        node = ast.parse(source, mode="eval").body
    except SyntaxError:
        return source.replace(" ", "")
    return _annotation_node(node)


def _union_members(annotation: str) -> list[str]:
    """Split a normalized annotation at top-level union bars only."""
    members: list[str] = []
    depth = 0
    start = 0
    for index, char in enumerate(annotation):
        if char == "[":
            depth += 1
        elif char == "]":
            depth -= 1
        elif char == "|" and depth == 0:
            members.append(annotation[start:index])
            start = index + 1
    members.append(annotation[start:])
    return members


def _return_types_match(actual: str | None, expected: str) -> bool:
    normalized_expected = _normalize_annotation(expected)
    if actual is None or normalized_expected is None:
        return False
    actual_members = _union_members(actual)
    expected_members = _union_members(normalized_expected)
    if len(actual_members) != len(expected_members):
        return False

    def member_matches(actual_member: str, expected_member: str) -> bool:
        if actual_member == expected_member:
            return True
        # A contract may intentionally promise a built-in container type while
        # the implementation carries a more specific generic annotation.
        return expected_member in {"dict", "list", "tuple"} and actual_member.startswith(
            expected_member + "["
        )

    unmatched = list(actual_members)
    for expected_member in expected_members:
        match = next(
            (item for item in unmatched if member_matches(item, expected_member)),
            None,
        )
        if match is None:
            return False
        unmatched.remove(match)
    return not unmatched


def _signature_mismatches(
    target: object,
    contract: dict,
    *,
    require_return: bool = False,
) -> list[str]:
    try:
        signature = inspect.signature(target)
    except (TypeError, ValueError) as exc:
        return [f"signature is not inspectable ({type(exc).__name__}: {exc})"]

    actual_parameters = list(signature.parameters)
    if actual_parameters and actual_parameters[0] in {"self", "cls"}:
        actual_parameters.pop(0)
    expected_parameters = list(contract.get("params", {}))
    mismatches = []
    if actual_parameters != expected_parameters:
        mismatches.append(
            f"parameter names {actual_parameters!r} != schema {expected_parameters!r}"
        )

    expected_return = contract.get("returns")
    if require_return and expected_return is None:
        mismatches.append("schema return type is missing")
    if expected_return is not None:
        actual_return = _normalize_annotation(signature.return_annotation)
        if actual_return is None:
            mismatches.append(f"return annotation is missing; schema says {expected_return!r}")
        elif not _return_types_match(actual_return, expected_return):
            mismatches.append(
                f"return type {actual_return!r} != schema {_normalize_annotation(expected_return)!r}"
            )
    return mismatches


def _assert_signature(
    testcase: unittest.TestCase,
    target: object,
    contract: dict,
    label: str,
    *,
    require_return: bool = False,
) -> None:
    mismatches = _signature_mismatches(target, contract, require_return=require_return)
    testcase.assertEqual(mismatches, [], f"{label}: " + "; ".join(mismatches))


def _assert_binary_module(testcase: unittest.TestCase, package: str, module: ModuleType) -> None:
    published = _PUBLISHED_MODULES.get(package)
    testcase.assertIsNotNone(published, f"{package} is not registered as a published module")
    module_file = getattr(module, "__file__", None)
    testcase.assertIsNotNone(module_file, f"{package} has no __file__")
    module_path = Path(module_file).resolve()
    testcase.assertTrue(
        module_path.name.endswith(tuple(importlib.machinery.EXTENSION_SUFFIXES)),
        f"{package} loaded source instead of an extension: {module_path}",
    )
    expected_directory = (published["directory"] / package).resolve()
    testcase.assertEqual(
        module_path.parent,
        expected_directory,
        f"{package} loaded from {module_path.parent}, expected {expected_directory}",
    )


def _run_bundled_contract(testcase: unittest.TestCase, module_id: str, contract_file: Path) -> None:
    loader_name = "_artifact_contract_" + module_id.replace("-", "_")
    spec = importlib.util.spec_from_file_location(loader_name, contract_file)
    testcase.assertIsNotNone(spec, f"cannot load bundled contract: {contract_file}")
    testcase.assertIsNotNone(spec.loader, f"bundled contract has no loader: {contract_file}")
    contract_module = importlib.util.module_from_spec(spec)
    sys.modules[loader_name] = contract_module
    try:
        spec.loader.exec_module(contract_module)
        suite = unittest.defaultTestLoader.loadTestsFromModule(contract_module)
        result = unittest.TestResult()
        suite.run(result)
    finally:
        sys.modules.pop(loader_name, None)

    details = [message for _, message in result.failures + result.errors]
    executed = result.testsRun - len(result.skipped)
    testcase.assertGreater(executed, 0, f"{module_id} bundled contract ran no tests")
    testcase.assertTrue(
        result.wasSuccessful(),
        f"{module_id} bundled contract failed: " + "\n".join(details),
    )


class ContractHelperRegressionTests(unittest.TestCase):
    """Prove the gate catches signature drift before checking built artifacts."""

    def test_parameter_and_return_drift_are_reported(self):
        def implementation(ctx, prompt) -> str:
            return prompt

        mismatches = _signature_mismatches(
            implementation,
            {"params": {"ctx": "RequestContext", "message": "str"}, "returns": "int"},
        )
        self.assertEqual(len(mismatches), 2)
        self.assertIn("parameter names", mismatches[0])
        self.assertIn("return type", mismatches[1])

    def test_typing_aliases_normalize_to_contract_types(self):
        def implementation() -> "List[SearchHit]":
            return []

        actual = _normalize_annotation(inspect.signature(implementation).return_annotation)
        self.assertTrue(_return_types_match(actual, "list[tuple[str,str,float]]"))
        self.assertTrue(_return_types_match("dict[str,obj]|null", "dict|null"))

    def test_missing_return_type_in_schema_is_reported(self):
        def implementation() -> None:
            return None

        mismatches = _signature_mismatches(
            implementation,
            {"params": {}},
            require_return=True,
        )
        self.assertEqual(mismatches, ["schema return type is missing"])

    def test_packaged_contract_rejects_source_module(self):
        from scripts.package_release_artifacts import _contract_test

        package = "_contract_fixture_source_only"
        artifact = ROOT / "artifacts" / "contract-test-fixture"
        contract_file = artifact / "test_contract.py"
        loader_name = "_artifact_contract_source_fixture"
        source_module = ModuleType(package)
        source_module.__file__ = str(artifact / package / "__init__.py")
        contract_module = ModuleType(loader_name)
        contract_module.__file__ = str(contract_file)
        sys.modules[package] = source_module
        sys.modules[loader_name] = contract_module
        try:
            exec(compile(_contract_test(package), str(contract_file), "exec"), contract_module.__dict__)
            suite = unittest.defaultTestLoader.loadTestsFromModule(contract_module)
            result = unittest.TestResult()
            suite.run(result)
        finally:
            sys.modules.pop(loader_name, None)
            sys.modules.pop(package, None)
            artifact_path = str(artifact)
            while artifact_path in sys.path:
                sys.path.remove(artifact_path)

        self.assertEqual(result.testsRun, 1)
        self.assertEqual(len(result.failures), 1)
        self.assertIn("loaded source instead of a compiled extension", result.failures[0][1])


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
        for mid, spec in schema["modules"].items():
            self.assertIn("package", spec, f"{mid} missing package")
            self.assertIn("delivery", spec, f"{mid} missing delivery")
            for name, declaration in spec.get("facade", {}).items():
                if declaration.get("kind") == "function":
                    self.assertIn("returns", declaration, f"{mid}.{name} missing return contract")
                if declaration.get("kind") in {"class", "protocol"}:
                    for method_name, method_contract in declaration.get("methods", {}).items():
                        self.assertIn(
                            "returns",
                            method_contract,
                            f"{mid}.{name}.{method_name} missing return contract",
                        )


class FacadeSignatureTests(unittest.TestCase):
    """Validate the published binary facade and replay its packaged contract."""

    def _registered_modules(self) -> dict:
        return _load_json(REGISTRY).get("modules", {})

    def test_registry_entries_match_schema(self):
        schema = _load_json(CONTRACTS / "API_SCHEMA.json")
        reg = self._registered_modules()
        for mid in schema["modules"]:
            self.assertIn(mid, reg, f"module {mid} not registered in registry.json")
            self.assertIn("version", reg[mid])
            self.assertIn("checksum", reg[mid])
            self.assertIn("status", reg[mid])
            if reg[mid]["status"] == "published":
                self.assertEqual(
                    schema["modules"][mid]["version"],
                    reg[mid]["version"],
                    f"{mid} schema version does not match registry.json",
                )
        declared_published = {
            mid
            for mid in schema["modules"]
            if (reg.get(mid) or {}).get("status") == "published"
        }
        registered_published = {
            mid for mid, entry in reg.items() if entry.get("status") == "published"
        }
        self.assertEqual(
            declared_published,
            registered_published,
            "published registry modules and canonical schema modules differ",
        )

    def test_importable_facade_signatures(self):
        if not _BINARY_RUNTIME_ACTIVE:
            self.skipTest("compiled artifact set is absent; Jenkins strict mode checks binary signatures")

        schema = _load_json(CONTRACTS / "API_SCHEMA.json")
        reg = self._registered_modules()
        for mid, module_spec in schema["modules"].items():
            entry = reg.get(mid, {})
            if entry.get("status") != "published":
                continue
            package = module_spec["package"]
            module = importlib.import_module(package)
            _assert_binary_module(self, package, module)

            for name, declaration in module_spec.get("facade", {}).items():
                with self.subTest(module=mid, symbol=name):
                    self.assertTrue(hasattr(module, name), f"{package} missing {name}")
                    target = getattr(module, name)
                    self.assertTrue(callable(target), f"{package}.{name} is not callable")
                    kind = declaration.get("kind")
                    if kind == "function":
                        _assert_signature(
                            self,
                            target,
                            declaration,
                            f"{package}.{name}",
                            require_return=True,
                        )
                    elif kind in {"class", "protocol"}:
                        if "init" in declaration:
                            _assert_signature(
                                self,
                                target,
                                {"params": declaration["init"]},
                                f"{package}.{name}.__init__",
                            )
                        for method_name, method_contract in declaration.get("methods", {}).items():
                            self.assertTrue(
                                hasattr(target, method_name),
                                f"{package}.{name} missing method {method_name}",
                            )
                            _assert_signature(
                                self,
                                getattr(target, method_name),
                                method_contract,
                                f"{package}.{name}.{method_name}",
                                require_return=True,
                            )

    def test_every_published_artifact_has_contract_metadata(self):
        for module_id, entry in self._registered_modules().items():
            if entry.get("status") != "published":
                continue
            slot = _artifact_directory(entry)
            for filename in ("INTERFACE.md", "API_SCHEMA.json", "checksum.sha256", "test_contract.py"):
                with self.subTest(module=module_id, file=filename):
                    self.assertTrue((slot / filename).is_file(), f"{module_id} missing {filename}")

    def test_packaged_artifact_contracts_replay_against_binary(self):
        if not _BINARY_RUNTIME_ACTIVE:
            self.skipTest("compiled artifact set is absent; Jenkins strict mode replays bundled contracts")

        for module_id, entry in self._registered_modules().items():
            if entry.get("status") != "published":
                continue
            with self.subTest(module=module_id):
                _run_bundled_contract(
                    self,
                    module_id,
                    _artifact_directory(entry) / "test_contract.py",
                )


if __name__ == "__main__":
    if STRICT:
        missing = _missing_published_extensions(_load_json(REGISTRY))
        if missing:
            raise SystemExit(
                "registered modules lack target-platform extensions: " + ", ".join(missing)
            )
    unittest.main(verbosity=2)
