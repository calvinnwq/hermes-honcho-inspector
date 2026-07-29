#!/usr/bin/env python3
"""Verify the exact Slice 3A release payload and its checksums."""

from __future__ import annotations

import hashlib
import json
import re
import stat
import subprocess
import sys
import tempfile
from pathlib import Path

import yaml

EXPECTED = {
    "INSTALL.md",
    "LICENSE",
    "SHA256SUMS",
    "compatibility.json",
    "desktop-plugins/honcho-inspector/plugin.js",
    "plugins/honcho-inspector/__init__.py",
    "plugins/honcho-inspector/dashboard/manifest.json",
    "plugins/honcho-inspector/dashboard/plugin_api.py",
    "plugins/honcho-inspector/plugin.yaml",
}
EXPECTED_DIRECTORIES = {
    "desktop-plugins",
    "desktop-plugins/honcho-inspector",
    "plugins",
    "plugins/honcho-inspector",
    "plugins/honcho-inspector/dashboard",
}
FORBIDDEN_BYTES = (
    b"/Users/",
    b"/home/",
    b"/private/var/folders/",
    b"\\Users\\",
    b"BEGIN PRIVATE KEY",
)
FORBIDDEN_PATTERNS = (
    re.compile(rb"\bgh[pousr]_[A-Za-z0-9]{20,}\b"),
    re.compile(rb"\bgithub_pat_[A-Za-z0-9_]{20,}\b"),
    re.compile(rb"\bsk-(?:proj-)?[A-Za-z0-9_-]{20,}\b"),
    re.compile(rb"\bAKIA[0-9A-Z]{16}\b"),
    re.compile(rb"\bxox[baprs]-[A-Za-z0-9-]{10,}\b"),
    re.compile(rb"\bxapp-[A-Za-z0-9-]{10,}\b"),
    re.compile(rb"/root/"),
    re.compile(rb"\bbearer\s+[A-Za-z0-9._~+/=-]{16,}", re.IGNORECASE),
    re.compile(
        rb"\b(?:api[_-]?key|authorization)\s*[:=]\s*[\"']?[A-Za-z0-9._~+/=-]{16,}",
        re.IGNORECASE,
    ),
)
VOLUME_PATH_PATTERN = re.compile(rb"/Volumes/[^\s\"'`,;:!?)}\]\r\n\x00]*")
PORTABLE_VOLUME_PREFIX = b"/Volumes/<external-volume>/"


def fail(message: str) -> None:
    raise SystemExit(f"release verification failed: {message}")


def contains_forbidden_content(payload: bytes) -> bool:
    return (
        contains_forbidden_volume_path(payload)
        or any(marker in payload for marker in FORBIDDEN_BYTES)
        or any(
            pattern.search(payload) for pattern in FORBIDDEN_PATTERNS
        )
    )


def contains_forbidden_volume_path(payload: bytes) -> bool:
    for match in VOLUME_PATH_PATTERN.finditer(payload):
        path = match.group()
        if not path.startswith(PORTABLE_VOLUME_PREFIX):
            return True
        remainder = path.removeprefix(PORTABLE_VOLUME_PREFIX)
        segments = remainder.split(b"/")
        if segments and segments[-1] == b"":
            segments.pop()
        if any(segment in {b"", b".", b".."} for segment in segments):
            return True
    return False


def load_unique_json(payload: bytes, label: str) -> object:
    def reject_duplicates(pairs: list[tuple[str, object]]) -> dict[str, object]:
        result: dict[str, object] = {}
        for key, value in pairs:
            if key in result:
                fail(f"duplicate manifest key in {label}: {key}")
            result[key] = value
        return result

    def reject_nonstandard_constant(value: str) -> object:
        fail(f"invalid JSON manifest {label}: nonstandard constant {value}")

    try:
        return json.loads(
            payload,
            object_pairs_hook=reject_duplicates,
            parse_constant=reject_nonstandard_constant,
        )
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        fail(f"invalid JSON manifest {label}: {error}")


def load_unique_yaml(payload: bytes, label: str) -> object:
    class UniqueKeyLoader(yaml.SafeLoader):
        pass

    def construct_mapping(
        loader: UniqueKeyLoader,
        node: yaml.nodes.MappingNode,
        deep: bool = False,
    ) -> dict[object, object]:
        result: dict[object, object] = {}
        for key_node, value_node in node.value:
            key = loader.construct_object(key_node, deep=deep)
            if key in result:
                fail(f"duplicate manifest key in {label}: {key}")
            result[key] = loader.construct_object(value_node, deep=deep)
        return result

    UniqueKeyLoader.add_constructor(
        yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG,
        construct_mapping,
    )
    try:
        return yaml.load(payload, Loader=UniqueKeyLoader)
    except (UnicodeDecodeError, yaml.YAMLError) as error:
        fail(f"invalid YAML manifest {label}: {error}")


def reject_symlink_components(path: Path) -> Path:
    absolute = path.expanduser().absolute()
    current = Path(absolute.anchor)
    for component in absolute.parts[1:]:
        current /= component
        try:
            mode = current.lstat().st_mode
        except FileNotFoundError:
            break
        if stat.S_ISLNK(mode):
            fail(f"release path components must not be symlinks: {current}")
    return absolute


def inventory_release(dist: Path) -> tuple[set[str], set[str], dict[str, int]]:
    files: set[str] = set()
    directories: set[str] = set()
    modes = {".": stat.S_IMODE(dist.lstat().st_mode)}
    pending = [dist]

    while pending:
        directory = pending.pop()
        for path in directory.iterdir():
            relative = path.relative_to(dist).as_posix()
            mode = path.lstat().st_mode
            if stat.S_ISLNK(mode):
                fail(f"symlinks are not allowed: {relative}")
            if stat.S_ISDIR(mode):
                directories.add(relative)
                modes[relative] = stat.S_IMODE(mode)
                pending.append(path)
            elif stat.S_ISREG(mode):
                files.add(relative)
                modes[relative] = stat.S_IMODE(mode)
            else:
                fail(f"special filesystem entry is not allowed: {relative}")

    return files, directories, modes


def main() -> None:
    requested_dist = reject_symlink_components(
        Path(sys.argv[1] if len(sys.argv) > 1 else "dist")
    )
    dist = requested_dist.resolve()
    if not dist.is_dir():
        fail(f"missing directory: {dist}")

    actual, directories, modes = inventory_release(dist)
    if actual != EXPECTED:
        fail(f"unexpected payload: missing={sorted(EXPECTED - actual)} extra={sorted(actual - EXPECTED)}")
    if directories != EXPECTED_DIRECTORIES:
        fail(
            "unexpected directories: "
            f"missing={sorted(EXPECTED_DIRECTORIES - directories)} "
            f"extra={sorted(directories - EXPECTED_DIRECTORIES)}"
        )

    load_unique_yaml(
        (dist / "plugins/honcho-inspector/plugin.yaml").read_bytes(),
        "plugin.yaml",
    )
    load_unique_json(
        (dist / "plugins/honcho-inspector/dashboard/manifest.json").read_bytes(),
        "dashboard/manifest.json",
    )
    load_unique_json(
        (dist / "compatibility.json").read_bytes(),
        "compatibility.json",
    )

    recorded: dict[str, str] = {}
    for line in (dist / "SHA256SUMS").read_text(encoding="utf-8").splitlines():
        digest, relative = line.split("  ", 1)
        if relative in recorded:
            fail(f"duplicate checksum path: {relative}")
        recorded[relative] = digest

    expected_checksums = EXPECTED - {"SHA256SUMS"}
    if set(recorded) != expected_checksums:
        fail("checksum manifest does not cover the exact payload")

    for relative, expected_digest in recorded.items():
        payload = (dist / relative).read_bytes()
        actual_digest = hashlib.sha256(payload).hexdigest()
        if actual_digest != expected_digest:
            fail(f"checksum mismatch: {relative}")
        if contains_forbidden_content(payload):
            fail(f"private or secret-like content: {relative}")

    root = Path(__file__).resolve().parents[1]
    with tempfile.TemporaryDirectory(prefix="honcho-inspector-release-") as temporary:
        clean_dist = Path(temporary).resolve() / "dist"
        result = subprocess.run(
            ["node", str(root / "scripts/build-release.mjs"), str(clean_dist)],
            cwd=root,
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode != 0:
            fail(f"clean source build failed: {result.stderr.strip() or result.stdout.strip()}")
        _, _, clean_modes = inventory_release(clean_dist)
        for relative in sorted({".", *EXPECTED_DIRECTORIES}):
            if modes[relative] != clean_modes[relative]:
                fail(f"directory mode differs from clean source build: {relative}")
        for relative in sorted(EXPECTED):
            if (dist / relative).read_bytes() != (clean_dist / relative).read_bytes():
                fail(f"payload differs from clean source build: {relative}")
            clean_mode = stat.S_IMODE((clean_dist / relative).lstat().st_mode)
            if modes[relative] != clean_mode:
                fail(f"file mode differs from clean source build: {relative}")

    print(f"release verification passed: {len(actual)} files")


if __name__ == "__main__":
    main()
