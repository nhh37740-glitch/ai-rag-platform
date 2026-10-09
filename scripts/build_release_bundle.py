"""Package the compiled runtime as a versioned, checksummed ZIP.

Run only after compiling extensions and refreshing registry.json on the target
platform. The archive contains app and contract source, but no module source.
"""

from __future__ import annotations

import hashlib
import importlib.machinery
import json
import sysconfig
import tomllib
import zipfile
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
DIST = ROOT / "dist"
FIXED_ZIP_TIME = (2026, 1, 1, 0, 0, 0)


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _files_under(relative_directory: str) -> list[Path]:
    directory = ROOT / relative_directory
    if not directory.is_dir():
        raise RuntimeError(f"Missing release directory: {directory}")
    return [path for path in directory.rglob("*") if path.is_file()]


def release_files(registry: dict) -> list[Path]:
    files: list[Path] = []
    for directory in (
        "apps/agent-server",
        "apps/web",
        "specifications",
        "skills",
        "data/kb/cmrc2018-demo",
    ):
        files.extend(_files_under(directory))
    files.extend((ROOT / "registry.json", ROOT / "requirements-runtime.txt"))

    suffixes = tuple(importlib.machinery.EXTENSION_SUFFIXES)
    published = 0
    for module_id, spec in sorted(registry.get("modules", {}).items()):
        if spec.get("status") != "published":
            continue
        published += 1
        relative = Path(str(spec["path"]).replace("\\", "/"))
        directory = (ROOT / relative).resolve()
        if ROOT.resolve() not in directory.parents or not directory.is_dir():
            raise RuntimeError(f"Invalid artifact directory for {module_id}: {directory}")
        package_directory = directory / spec["name"]
        compiled = [
            path
            for path in package_directory.glob("__init__*")
            if path.is_file() and path.name.endswith(suffixes)
        ]
        if not compiled:
            raise RuntimeError(f"No target-platform extension for {module_id}")
        files.extend(path for path in directory.rglob("*") if path.is_file())
    if not published:
        raise RuntimeError("registry.json has no published modules")

    # Only selected runtime files leave the build stage. Keep tests, caches,
    # developer metadata and machine-specific scratch data out of the ZIP.
    excluded_parts = {"__pycache__", ".pytest_cache", "tests", ".git"}
    selected = {
        path.resolve()
        for path in files
        if not excluded_parts.intersection(path.relative_to(ROOT).parts)
        and not any(part.endswith(".egg-info") for part in path.relative_to(ROOT).parts)
        and path.suffix != ".pyc"
    }
    return sorted(selected, key=lambda path: path.relative_to(ROOT).as_posix())


def verify_archive(archive: Path) -> int:
    with zipfile.ZipFile(archive) as bundle:
        manifest = json.loads(bundle.read("release-manifest.json"))
        entries = manifest["files"]
        expected = {entry["path"] for entry in entries} | {"release-manifest.json"}
        if set(bundle.namelist()) != expected:
            raise RuntimeError("Release ZIP contents do not match its manifest")
        for entry in entries:
            data = bundle.read(entry["path"])
            if len(data) != entry["bytes"] or sha256(data) != entry["sha256"]:
                raise RuntimeError(f"Release checksum mismatch: {entry['path']}")
            if entry["path"].startswith("modules-src/") or "/.git/" in entry["path"]:
                raise RuntimeError(f"Module source or Git metadata in release: {entry['path']}")
        return len(entries)


def main() -> None:
    with (ROOT / "apps/agent-server/pyproject.toml").open("rb") as handle:
        version = tomllib.load(handle)["project"]["version"]
    registry = json.loads((ROOT / "registry.json").read_text(encoding="utf-8"))
    files = release_files(registry)
    platform_tag = sysconfig.get_platform().replace(" ", "-")
    name = f"ai-rag-platform-{version}-{platform_tag}"
    manifest = {
        "name": "ai-rag-platform",
        "version": version,
        "platform": platform_tag,
        "module_versions": {
            module_id: spec["version"]
            for module_id, spec in sorted(registry["modules"].items())
            if spec.get("status") == "published"
        },
        "files": [
            {
                "path": path.relative_to(ROOT).as_posix(),
                "bytes": path.stat().st_size,
                "sha256": sha256(path.read_bytes()),
            }
            for path in files
        ],
    }
    DIST.mkdir(exist_ok=True)
    manifest_bytes = (json.dumps(manifest, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
    (DIST / f"{name}.manifest.json").write_bytes(manifest_bytes)
    archive = DIST / f"{name}.zip"
    with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED) as bundle:
        for path in files:
            item = zipfile.ZipInfo(path.relative_to(ROOT).as_posix(), FIXED_ZIP_TIME)
            item.compress_type = zipfile.ZIP_DEFLATED
            bundle.writestr(item, path.read_bytes())
        item = zipfile.ZipInfo("release-manifest.json", FIXED_ZIP_TIME)
        item.compress_type = zipfile.ZIP_DEFLATED
        bundle.writestr(item, manifest_bytes)
    digest = sha256(archive.read_bytes())
    (DIST / f"{name}.zip.sha256").write_text(f"{digest}  {archive.name}\n", encoding="utf-8")
    count = verify_archive(archive)
    print(f"release={archive} files={count} sha256={digest}")


if __name__ == "__main__":
    main()
