import hashlib
import os
import stat
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
DIST = ROOT / "dist"
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


@pytest.fixture(scope="module", autouse=True)
def build_release() -> None:
    subprocess.run(["npm", "run", "build", "--silent"], cwd=ROOT, check=True)


def test_release_contains_only_reviewed_runtime_files() -> None:
    actual = {path.relative_to(DIST).as_posix() for path in DIST.rglob("*") if path.is_file()}
    assert actual == EXPECTED


@pytest.mark.skipif(os.name == "nt", reason="POSIX file modes are required")
def test_release_uses_deterministic_modes() -> None:
    for path in DIST.rglob("*"):
        expected = 0o755 if path.is_dir() else 0o644
        assert stat.S_IMODE(path.lstat().st_mode) == expected, path


def test_checksum_manifest_covers_every_other_release_file() -> None:
    lines = (DIST / "SHA256SUMS").read_text().splitlines()
    recorded = {}
    for line in lines:
        digest, relative = line.split("  ", 1)
        recorded[relative] = digest

    expected_paths = EXPECTED - {"SHA256SUMS"}
    assert set(recorded) == expected_paths

    for relative, digest in recorded.items():
        actual = hashlib.sha256((DIST / relative).read_bytes()).hexdigest()
        assert actual == digest
