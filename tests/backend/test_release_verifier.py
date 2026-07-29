import hashlib
import importlib.util
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
DIST = ROOT / "dist"
VERIFY = ROOT / "scripts/verify-release.py"
BUILD = ROOT / "scripts/build-release.mjs"
BUILD_INPUTS = (
    "plugin.yaml",
    "__init__.py",
    "dashboard/manifest.json",
    "dashboard/plugin_api.py",
    "desktop/plugin.ts",
    "desktop/overview-model.ts",
    "desktop/session-model.ts",
    "INSTALL.md",
    "LICENSE",
    "compatibility.json",
)


def load_release_verifier_module():
    spec = importlib.util.spec_from_file_location("verify_release", VERIFY)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module", autouse=True)
def build_release() -> None:
    subprocess.run(["npm", "run", "build", "--silent"], cwd=ROOT, check=True)


def write_checksums(candidate: Path) -> None:
    lines = []
    for path in sorted(candidate.rglob("*")):
        if path.is_file() and path.name != "SHA256SUMS":
            relative = path.relative_to(candidate).as_posix()
            lines.append(f"{hashlib.sha256(path.read_bytes()).hexdigest()}  {relative}")
    (candidate / "SHA256SUMS").write_text("\n".join(lines) + "\n", encoding="utf-8")


def run_verifier(candidate: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(VERIFY), str(candidate)],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )


def copy_build_inputs(tmp_path: Path, source_root: Path | None = None) -> Path:
    source_root = source_root or tmp_path / "source"
    for relative in BUILD_INPUTS:
        source = ROOT / relative
        target = source_root / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, target)
    return source_root


def test_release_verifier_accepts_the_clean_build() -> None:
    result = run_verifier(DIST)

    assert result.returncode == 0, result.stderr or result.stdout


@pytest.mark.parametrize("relative", ["plugin.yaml", "desktop/overview-model.ts"])
def test_release_builder_rejects_symlinked_source_inputs(
    tmp_path: Path,
    relative: str,
) -> None:
    source_root = copy_build_inputs(tmp_path)
    source_input = source_root / relative
    external = tmp_path / f"external-{source_input.name}"
    external.write_text(source_input.read_text(encoding="utf-8"), encoding="utf-8")
    source_input.unlink()
    source_input.symlink_to(external)

    result = subprocess.run(
        ["node", str(BUILD), str(tmp_path / "dist"), str(source_root)],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode != 0
    assert "source input must be a regular file" in result.stderr + result.stdout


def test_release_builder_rejects_symlinked_source_root(tmp_path: Path) -> None:
    source_root = copy_build_inputs(tmp_path)
    linked_source = tmp_path / "linked-source"
    linked_source.symlink_to(source_root, target_is_directory=True)

    result = subprocess.run(
        ["node", str(BUILD), str(tmp_path / "dist"), str(linked_source)],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode != 0
    assert "source path components must not be symlinks" in result.stderr + result.stdout


def test_release_builder_rejects_unsafe_output_directory(tmp_path: Path) -> None:
    source_root = copy_build_inputs(tmp_path)

    result = subprocess.run(
        ["node", str(BUILD), str(tmp_path / "output"), str(source_root)],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode != 0
    assert "output directory must be named dist" in result.stderr + result.stdout


def test_release_builder_rejects_source_inside_output_without_deleting_it(tmp_path: Path) -> None:
    output = tmp_path / "dist"
    source_root = copy_build_inputs(tmp_path, output / "source")
    sentinel = source_root / "plugin.yaml"

    result = subprocess.run(
        ["node", str(BUILD), str(output), str(source_root)],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode != 0
    assert "output directory must not contain a source root" in result.stderr + result.stdout
    assert sentinel.is_file()


def test_release_builder_rejects_symlinked_source_directory(tmp_path: Path) -> None:
    source_root = copy_build_inputs(tmp_path)
    dashboard = source_root / "dashboard"
    external = tmp_path / "external-dashboard"
    dashboard.rename(external)
    dashboard.symlink_to(external, target_is_directory=True)

    result = subprocess.run(
        ["node", str(BUILD), str(tmp_path / "dist"), str(source_root)],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode != 0
    assert "source path components must not be symlinks" in result.stderr + result.stdout


def test_release_builder_rejects_symlinked_output_parent_without_deleting_target(
    tmp_path: Path,
) -> None:
    source_root = copy_build_inputs(tmp_path)
    external = tmp_path / "external-output"
    output = external / "dist"
    output.mkdir(parents=True)
    sentinel = output / "sentinel"
    sentinel.write_text("preserve", encoding="utf-8")
    linked_parent = tmp_path / "linked-output"
    linked_parent.symlink_to(external, target_is_directory=True)

    result = subprocess.run(
        ["node", str(BUILD), str(linked_parent / "dist"), str(source_root)],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode != 0
    assert "output path components must not be symlinks" in result.stderr + result.stdout
    assert sentinel.read_text(encoding="utf-8") == "preserve"


def test_release_builder_is_independent_of_source_root_path(tmp_path: Path) -> None:
    source_root = copy_build_inputs(tmp_path)
    candidate = tmp_path / "dist"

    subprocess.run(
        ["node", str(BUILD), str(candidate), str(source_root)],
        cwd=ROOT,
        check=True,
    )

    expected_bundle = DIST / "desktop-plugins/honcho-inspector/plugin.js"
    actual_bundle = candidate / "desktop-plugins/honcho-inspector/plugin.js"
    assert actual_bundle.read_bytes() == expected_bundle.read_bytes()


@pytest.mark.parametrize(
    "secret",
    [
        "gh" + "p_" + "A" * 36,
        "github_pat_" + "A" * 82,
        "sk-" + "proj-" + "A" * 24,
        "xapp-1-" + "A" * 20 + "-" + "B" * 20,
        "C:" + "\\\\Users\\Example\\secret.txt",
        "/private/var/" + "folders/example/private.txt",
        "/" + "root" + "/.ssh/id_ed25519",
        "/" + "Volumes" + "/ExamplePrivate/secrets/token.txt",
    ],
)
def test_release_verifier_reports_secret_like_source_payloads(tmp_path: Path, secret: str) -> None:
    source_root = copy_build_inputs(tmp_path)
    install = source_root / "INSTALL.md"
    install.write_text(install.read_text(encoding="utf-8") + f"\n{secret}\n", encoding="utf-8")
    candidate = tmp_path / "dist"
    subprocess.run(
        ["node", str(BUILD), str(candidate), str(source_root)],
        cwd=ROOT,
        check=True,
    )

    result = run_verifier(candidate)

    assert result.returncode != 0
    assert "private or secret-like content: INSTALL.md" in result.stderr + result.stdout


def test_release_verifier_rejects_self_checksummed_runtime_substitution(tmp_path: Path) -> None:
    candidate = tmp_path / "candidate"
    shutil.copytree(DIST, candidate)
    bundle = candidate / "desktop-plugins/honcho-inspector/plugin.js"
    bundle.write_text(
        bundle.read_text(encoding="utf-8") + '\nglobalThis["fetch"]("https://example.invalid");\n',
        encoding="utf-8",
    )
    write_checksums(candidate)

    result = run_verifier(candidate)

    assert result.returncode != 0
    assert "release verification failed" in result.stderr + result.stdout


@pytest.mark.parametrize(
    ("relative", "duplicate_key"),
    [
        ("plugins/honcho-inspector/plugin.yaml", "name: attacker-controlled\n"),
        (
            "plugins/honcho-inspector/dashboard/manifest.json",
            '  "name": "attacker-controlled",\n',
        ),
        ("compatibility.json", '  "schema_version": 999,\n'),
    ],
)
def test_release_verifier_rejects_duplicate_manifest_keys(
    tmp_path: Path,
    relative: str,
    duplicate_key: str,
) -> None:
    candidate = tmp_path / "candidate"
    shutil.copytree(DIST, candidate)
    manifest = candidate / relative
    original = manifest.read_text(encoding="utf-8")
    if manifest.suffix == ".yaml":
        manifest.write_text(duplicate_key + original, encoding="utf-8")
    else:
        manifest.write_text(original.replace("{\n", "{\n" + duplicate_key, 1), encoding="utf-8")
    write_checksums(candidate)

    result = run_verifier(candidate)

    assert result.returncode != 0
    assert "duplicate manifest key" in result.stderr + result.stdout


def test_release_verifier_rejects_nonstandard_json_constants(tmp_path: Path) -> None:
    candidate = tmp_path / "candidate"
    shutil.copytree(DIST, candidate)
    manifest = candidate / "plugins/honcho-inspector/dashboard/manifest.json"
    original = manifest.read_text(encoding="utf-8")
    manifest.write_text(
        original.replace('"label": "Honcho Inspector"', '"label": NaN'),
        encoding="utf-8",
    )
    write_checksums(candidate)

    result = run_verifier(candidate)

    assert result.returncode != 0
    assert "invalid JSON manifest" in result.stderr + result.stdout


def test_release_verifier_rejects_unexpected_directory(tmp_path: Path) -> None:
    candidate = tmp_path / "candidate"
    shutil.copytree(DIST, candidate)
    (candidate / "unexpected-directory").mkdir()

    result = run_verifier(candidate)

    assert result.returncode != 0
    assert "unexpected directories" in result.stderr + result.stdout


@pytest.mark.skipif(not hasattr(os, "mkfifo"), reason="FIFO creation is unavailable")
def test_release_verifier_rejects_special_files(tmp_path: Path) -> None:
    candidate = tmp_path / "candidate"
    shutil.copytree(DIST, candidate)
    os.mkfifo(candidate / "unexpected.fifo")

    result = run_verifier(candidate)

    assert result.returncode != 0
    assert "special filesystem entry" in result.stderr + result.stdout


@pytest.mark.skipif(os.name == "nt", reason="POSIX file modes are required")
def test_release_verifier_rejects_file_mode_tampering(tmp_path: Path) -> None:
    candidate = tmp_path / "candidate"
    shutil.copytree(DIST, candidate)
    bundle = candidate / "desktop-plugins/honcho-inspector/plugin.js"
    bundle.chmod(0o755)

    result = run_verifier(candidate)

    assert result.returncode != 0
    assert "file mode differs from clean source build" in result.stderr + result.stdout


@pytest.mark.skipif(os.name == "nt", reason="POSIX directory modes are required")
@pytest.mark.parametrize("relative", [".", "plugins/honcho-inspector/dashboard"])
def test_release_verifier_rejects_directory_mode_tampering(
    tmp_path: Path,
    relative: str,
) -> None:
    candidate = tmp_path / "candidate"
    shutil.copytree(DIST, candidate)
    (candidate / relative).chmod(0o777)

    result = run_verifier(candidate)

    assert result.returncode != 0
    assert "directory mode differs from clean source build" in result.stderr + result.stdout


def test_release_verifier_rejects_symlinked_parent_directory(tmp_path: Path) -> None:
    physical_parent = tmp_path / "physical-parent"
    candidate = physical_parent / "candidate"
    shutil.copytree(DIST, candidate)
    alias_parent = tmp_path / "alias-parent"
    alias_parent.symlink_to(physical_parent, target_is_directory=True)

    result = run_verifier(alias_parent / "candidate")

    assert result.returncode != 0
    assert "release path components must not be symlinks" in result.stderr + result.stdout


@pytest.mark.parametrize(
    ("payload", "forbidden"),
    [
        (b"Portable example: /Volumes/<external-volume>/repo", False),
        (b"Portable root: /Volumes/<external-volume>/", False),
        (b"Malformed root: /" + b"Volumes" + b"/<external-volume>", True),
        (b"Malformed: /" + b"Volumes" + b"/<external-volumeX>/repo", True),
        (b"Concrete root: /" + b"Volumes" + b"/ExamplePrivate", True),
        (b"Concrete: /" + b"Volumes" + b"/ExamplePrivate/repo", True),
        (b"Doubled separator: /" + b"Volumes" + b"//ExamplePrivate/repo", True),
        (
            b"Traversal: /Volumes/<external-volume>/../" + b"ExamplePrivate/repo",
            True,
        ),
        (b"Malformed portable: /Volumes/<external-volume>//repo", True),
    ],
)
def test_release_privacy_scanner_handles_volume_placeholders(
    payload: bytes,
    forbidden: bool,
) -> None:
    verifier = load_release_verifier_module()

    assert verifier.contains_forbidden_content(payload) is forbidden
