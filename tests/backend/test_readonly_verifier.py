import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
VERIFY = ROOT / "scripts/verify-readonly.py"
RUNTIME_FILES = (
    "__init__.py",
    "dashboard/plugin_api.py",
    "desktop/plugin.ts",
    "dist/desktop-plugins/honcho-inspector/plugin.js",
)


def copy_runtime(tmp_path: Path) -> Path:
    candidate = tmp_path / "candidate"
    for relative in RUNTIME_FILES:
        source = ROOT / relative
        target = candidate / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, target)
    return candidate


def run_verifier(candidate: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(VERIFY), str(candidate)],
        capture_output=True,
        text=True,
        check=False,
    )


def test_readonly_verifier_accepts_the_slice_one_handshake(tmp_path: Path) -> None:
    candidate = copy_runtime(tmp_path)

    result = run_verifier(candidate)

    assert result.returncode == 0, result.stderr or result.stdout


def test_readonly_verifier_rejects_executable_parameter_annotations(tmp_path: Path) -> None:
    candidate = copy_runtime(tmp_path)
    plugin = candidate / "__init__.py"
    plugin.write_text(
        plugin.read_text(encoding="utf-8").replace(
            "def register(ctx) -> None:",
            'def register(ctx: print("ANNOTATION_SIDE_EFFECT")) -> None:',
        ),
        encoding="utf-8",
    )

    result = run_verifier(candidate)

    assert result.returncode != 0
    assert "read-only verification failed" in result.stderr + result.stdout


@pytest.mark.parametrize(
    ("relative", "mutation"),
    [
        (
            "__init__.py",
            "\ndef register(ctx) -> None:\n    ctx.register_tool(object())\n",
        ),
        (
            "dashboard/plugin_api.py",
            '\nrouter.add_api_route("/write", lambda: None, methods=["POST"])\n',
        ),
        (
            "dashboard/plugin_api.py",
            '\nfrom urllib.request import urlopen\nurlopen("https://example.invalid")\n',
        ),
        (
            "dashboard/plugin_api.py",
            '\nfrom pathlib import Path\nPath("mutant.txt").write_text("mutation")\n',
        ),
        (
            "dashboard/plugin_api.py",
            '\nimport subprocess\nsubprocess.run(["false"], check=False)\n',
        ),
        ("desktop/plugin.ts", '\nglobalThis["fetch"]("https://example.invalid")\n'),
        ("desktop/plugin.ts", "\nnew XMLHttpRequest()\n"),
        (
            "desktop/plugin.ts",
            '\nnavigator.sendBeacon("https://example.invalid", "mutation")\n',
        ),
        ("desktop/plugin.ts", '\nlocalStorage.setItem("slice", "mutation")\n'),
        ("desktop/plugin.ts", '\ndocument.body.append("mutation")\n'),
        (
            "desktop/plugin.ts",
            '\nconst credential = "placeholder-value"\n',
        ),
        (
            "dist/desktop-plugins/honcho-inspector/plugin.js",
            '\nglobalThis["fetch"]("https://example.invalid");\n',
        ),
    ],
)
def test_readonly_verifier_rejects_runtime_capabilities(
    tmp_path: Path,
    relative: str,
    mutation: str,
) -> None:
    candidate = copy_runtime(tmp_path)
    target = candidate / relative
    target.write_text(target.read_text(encoding="utf-8") + mutation, encoding="utf-8")
    result = run_verifier(candidate)

    assert result.returncode != 0
    assert "read-only verification failed" in result.stderr + result.stdout


@pytest.mark.parametrize(
    ("approved", "mutation"),
    [
        ('@router.get("/capabilities"', '@router.post("/capabilities"'),
        ('@router.get("/capabilities"', '@router.get("/proxy"'),
        ('client.get("/health")', 'client.post("/health")'),
        ('client.get("/health")', 'client.get("/v3/chat")'),
        ("follow_redirects=False", "follow_redirects=True"),
        (
            "from plugins.memory.honcho.client import HonchoClientConfig",
            "from plugins.memory.honcho.client import get_honcho_client",
        ),
    ],
)
def test_readonly_verifier_rejects_handshake_contract_drift(
    tmp_path: Path,
    approved: str,
    mutation: str,
) -> None:
    candidate = copy_runtime(tmp_path)
    backend = candidate / "dashboard/plugin_api.py"
    source = backend.read_text(encoding="utf-8")
    assert approved in source
    backend.write_text(source.replace(approved, mutation, 1), encoding="utf-8")

    result = run_verifier(candidate)

    assert result.returncode != 0
    assert "read-only verification failed" in result.stderr + result.stdout
