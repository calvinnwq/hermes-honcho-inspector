#!/usr/bin/env python3
"""Verify the exact inert runtime contract for the Slice 0 scaffold."""

import ast
import hashlib
import sys
from pathlib import Path
from typing import NoReturn

ROOT = Path(sys.argv[1] if len(sys.argv) > 1 else Path(__file__).resolve().parents[1]).resolve()
DESKTOP_SOURCE = '''export const PLUGIN_ID = "honcho-inspector"
export const PLUGIN_VERSION = "0.1.0"

const plugin = {
  id: PLUGIN_ID,
  name: "Honcho Inspector",
  defaultEnabled: false,
  register() {
    // Slice 0 proves the install and release contract without product behavior.
  }
}

export default plugin
'''
DESKTOP_BUNDLE_SHA256 = "9d03b6d9bf00800b4a8f45d4efbe5d2c24693fe06d44e08bd606d15a35750e42"


def fail(message: str) -> NoReturn:
    raise SystemExit(f"read-only verification failed: {message}")


def read_text(relative: str) -> str:
    try:
        return (ROOT / relative).read_text(encoding="utf-8")
    except (OSError, UnicodeError) as error:
        fail(f"cannot read {relative}: {error}")


def is_docstring(statement: ast.stmt) -> bool:
    return (
        isinstance(statement, ast.Expr)
        and isinstance(statement.value, ast.Constant)
        and isinstance(statement.value.value, str)
    )


def verify_general_plugin() -> None:
    tree = ast.parse(read_text("__init__.py"))
    if len(tree.body) != 2 or not is_docstring(tree.body[0]):
        fail("general plugin must contain only its docstring and register function")

    function = tree.body[1]
    if not isinstance(function, ast.FunctionDef) or function.name != "register":
        fail("general plugin must expose only register(ctx)")
    arguments = function.args
    if (
        function.decorator_list
        or len(arguments.args) != 1
        or arguments.args[0].arg != "ctx"
        or arguments.args[0].annotation is not None
        or arguments.posonlyargs
        or arguments.kwonlyargs
        or arguments.vararg
        or arguments.kwarg
        or arguments.defaults
        or arguments.kw_defaults
        or getattr(function, "type_params", [])
        or not isinstance(function.returns, ast.Constant)
        or function.returns.value is not None
        or len(function.body) != 1
        or not is_docstring(function.body[0])
    ):
        fail("general plugin register(ctx) must remain an exact no-op")


def verify_dashboard_plugin() -> None:
    tree = ast.parse(read_text("dashboard/plugin_api.py"))
    if len(tree.body) != 3 or not is_docstring(tree.body[0]):
        fail("dashboard backend must contain only its docstring, APIRouter import, and empty router")

    import_statement = tree.body[1]
    assignment = tree.body[2]
    valid_import = (
        isinstance(import_statement, ast.ImportFrom)
        and import_statement.module == "fastapi"
        and import_statement.level == 0
        and len(import_statement.names) == 1
        and import_statement.names[0].name == "APIRouter"
        and import_statement.names[0].asname is None
    )
    valid_assignment = (
        isinstance(assignment, ast.Assign)
        and len(assignment.targets) == 1
        and isinstance(assignment.targets[0], ast.Name)
        and assignment.targets[0].id == "router"
        and isinstance(assignment.value, ast.Call)
        and isinstance(assignment.value.func, ast.Name)
        and assignment.value.func.id == "APIRouter"
        and not assignment.value.args
        and not assignment.value.keywords
    )
    if not valid_import or not valid_assignment:
        fail("dashboard backend must expose only an empty APIRouter")


def verify_desktop_plugin() -> None:
    if read_text("desktop/plugin.ts") != DESKTOP_SOURCE:
        fail("Desktop source differs from the approved inert Slice 0 entry point")

    try:
        bundle = (ROOT / "dist/desktop-plugins/honcho-inspector/plugin.js").read_bytes()
    except OSError as error:
        fail(f"cannot read Desktop bundle: {error}")
    if hashlib.sha256(bundle).hexdigest() != DESKTOP_BUNDLE_SHA256:
        fail("Desktop bundle differs from the approved inert Slice 0 artifact")


def main() -> None:
    verify_general_plugin()
    verify_dashboard_plugin()
    verify_desktop_plugin()
    print("read-only verification passed: exact inert Slice 0 runtime contract")


if __name__ == "__main__":
    main()
