import importlib.util
import json
import re
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
VERIFY_RELEASE = ROOT / "scripts/verify-release.py"
PLUGIN_ID = "honcho-inspector"
PLUGIN_VERSION = "0.1.0"
REPOSITORY_NAME = "hermes-honcho-inspector"


def _release_verifier():
    spec = importlib.util.spec_from_file_location("verify_release_contract", VERIFY_RELEASE)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _typescript_constant(source: str, name: str) -> str:
    match = re.search(rf'export const {name} = ["\']([^"\']+)["\']', source)
    assert match, f"missing exported constant {name}"
    return match.group(1)


def test_identity_and_version_match_across_components() -> None:
    verifier = _release_verifier()
    plugin_manifest = verifier.load_unique_yaml((ROOT / "plugin.yaml").read_bytes(), "plugin.yaml")
    dashboard_manifest = verifier.load_unique_json(
        (ROOT / "dashboard/manifest.json").read_bytes(),
        "dashboard/manifest.json",
    )
    compatibility = verifier.load_unique_json(
        (ROOT / "compatibility.json").read_bytes(),
        "compatibility.json",
    )
    desktop_source = (ROOT / "desktop/plugin.ts").read_text()

    assert plugin_manifest["name"] == PLUGIN_ID
    assert dashboard_manifest["name"] == PLUGIN_ID
    assert compatibility["plugin"]["id"] == PLUGIN_ID
    assert _typescript_constant(desktop_source, "PLUGIN_ID") == PLUGIN_ID

    assert plugin_manifest["version"] == PLUGIN_VERSION
    assert dashboard_manifest["version"] == PLUGIN_VERSION
    assert compatibility["plugin"]["version"] == PLUGIN_VERSION
    assert _typescript_constant(desktop_source, "PLUGIN_VERSION") == PLUGIN_VERSION


def test_package_metadata_matches_the_paired_product_version() -> None:
    package = json.loads((ROOT / "package.json").read_text(encoding="utf-8"))
    pyproject = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))

    assert package["name"] == REPOSITORY_NAME
    assert package["version"] == PLUGIN_VERSION
    assert package["private"] is True
    assert pyproject["project"]["name"] == REPOSITORY_NAME
    assert pyproject["project"]["version"] == PLUGIN_VERSION


def test_compatibility_record_is_narrow_and_evidence_backed() -> None:
    compatibility = _release_verifier().load_unique_json(
        (ROOT / "compatibility.json").read_bytes(),
        "compatibility.json",
    )

    assert compatibility["schema_version"] == 1
    assert compatibility["honcho"]["openapi_contract"] == "3.0.11"
    assert compatibility["honcho"]["hosted_smoke"] == "not-run"
    assert compatibility["hermes"]["minimum_release"] is None
    assert compatibility["hermes"]["development_commits"] == [
        "71e7eb3c168a49fdd3179efb8a921ad78f6e8e1d",
        "731aa0ccc9d0968bd61a0c6cee7911aa787c58b2",
    ]
