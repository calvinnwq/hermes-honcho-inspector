import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_slice_zero_install_document_does_not_mutate_a_live_profile() -> None:
    instructions = (ROOT / "INSTALL.md").read_text(encoding="utf-8")

    assert "No release has been published" in instructions
    assert "Do not install Slice 0" in instructions
    assert "HERMES_HOME" not in instructions
    assert "cp -R" not in instructions
    assert "gateway restart" not in instructions.lower()
    assert "Desktop Settings" not in instructions


def test_package_exposes_the_canonical_typecheck_command() -> None:
    package = json.loads((ROOT / "package.json").read_text(encoding="utf-8"))

    assert package["scripts"]["typecheck"] == "tsc --noEmit"


def test_setup_docs_use_the_version_portable_python_command() -> None:
    for relative in ("README.md", "CONTRIBUTING.md", "AGENTS.md"):
        document = (ROOT / relative).read_text(encoding="utf-8")
        assert 'PYTHON="${PYTHON:-python3}"' in document
        assert '"$PYTHON" -m venv .venv' in document
        assert "Python 3.11+ required" in document
        assert ".venv/bin/python scripts/verify-release.py dist" in document
        assert ".venv/bin/python scripts/verify-readonly.py" in document
        assert "python3.11" not in document


def test_node_floor_matches_the_locked_toolchain() -> None:
    package = json.loads((ROOT / "package.json").read_text(encoding="utf-8"))
    lockfile = json.loads((ROOT / "package-lock.json").read_text(encoding="utf-8"))
    readme = (ROOT / "README.md").read_text(encoding="utf-8")

    assert package["engines"]["node"] == ">=22.12.0"
    assert lockfile["packages"][""]["engines"]["node"] == ">=22.12.0"
    assert "Node.js 22.12 or newer" in readme


def test_git_attributes_normalize_repository_text_to_lf() -> None:
    attributes = (ROOT / ".gitattributes").read_text(encoding="utf-8")

    assert "* text=auto eol=lf" in attributes.splitlines()
