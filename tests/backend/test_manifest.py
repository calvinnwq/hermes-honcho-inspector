import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
VERIFY_RELEASE = ROOT / "scripts/verify-release.py"


def _release_verifier():
    spec = importlib.util.spec_from_file_location("verify_release_manifest", VERIFY_RELEASE)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_general_plugin_manifest_is_explicit_standalone() -> None:
    manifest = _release_verifier().load_unique_yaml(
        (ROOT / "plugin.yaml").read_bytes(),
        "plugin.yaml",
    )

    assert manifest == {
        "manifest_version": 1,
        "name": "honcho-inspector",
        "version": "0.1.0",
        "description": "Read-only Honcho inspection for Hermes Desktop",
        "kind": "standalone",
    }


def test_dashboard_manifest_has_only_the_loader_contract() -> None:
    manifest = _release_verifier().load_unique_json(
        (ROOT / "dashboard/manifest.json").read_bytes(),
        "dashboard/manifest.json",
    )

    assert manifest == {
        "name": "honcho-inspector",
        "label": "Honcho Inspector",
        "version": "0.1.0",
        "api": "plugin_api.py",
    }
