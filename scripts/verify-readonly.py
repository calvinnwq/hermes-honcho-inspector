#!/usr/bin/env python3
"""Verify the exact read-only runtime contract for the Slice 1 handshake."""

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
DASHBOARD_SOURCE_SHA256 = "cd09e404fb298d13be753730caf175e2c9610250d9401a7006c64578e11b863f"


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
    source = read_text("dashboard/plugin_api.py")
    if hashlib.sha256(source.encode("utf-8")).hexdigest() != DASHBOARD_SOURCE_SHA256:
        fail("dashboard backend differs from the approved Slice 1 handshake")

    tree = ast.parse(source)
    routes: list[tuple[str, str]] = []
    health_calls = 0
    config_imports = 0
    forbidden_modules = {"honcho", "os", "pathlib", "requests", "socket", "subprocess"}
    forbidden_client_methods = {
        "delete",
        "options",
        "patch",
        "post",
        "put",
        "request",
        "send",
        "stream",
    }

    for node in ast.walk(tree):
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            modules = (
                [alias.name for alias in node.names]
                if isinstance(node, ast.Import)
                else [node.module or ""]
            )
            if any(module.split(".", 1)[0] in forbidden_modules for module in modules):
                fail("dashboard backend imports a forbidden runtime module")
            if (
                isinstance(node, ast.ImportFrom)
                and node.module == "plugins.memory.honcho.client"
            ):
                imported = [(alias.name, alias.asname) for alias in node.names]
                if imported != [("HonchoClientConfig", None)]:
                    fail("dashboard backend may import only HonchoClientConfig")
                config_imports += 1

        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            for decorator in node.decorator_list:
                if (
                    isinstance(decorator, ast.Call)
                    and isinstance(decorator.func, ast.Attribute)
                    and isinstance(decorator.func.value, ast.Name)
                    and decorator.func.value.id == "router"
                ):
                    if (
                        len(decorator.args) != 1
                        or not isinstance(decorator.args[0], ast.Constant)
                        or not isinstance(decorator.args[0].value, str)
                    ):
                        fail("dashboard route path must be a fixed string")
                    routes.append((decorator.func.attr, decorator.args[0].value))

        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
            if node.func.attr in forbidden_client_methods:
                fail("dashboard backend contains a forbidden HTTP client method")
            if (
                node.func.attr == "get"
                and isinstance(node.func.value, ast.Name)
                and node.func.value.id == "client"
            ):
                if (
                    len(node.args) != 1
                    or not isinstance(node.args[0], ast.Constant)
                    or node.args[0].value != "/health"
                    or node.keywords
                ):
                    fail("Honcho health probe must remain a fixed GET /health")
                health_calls += 1

    if routes != [("get", "/capabilities")]:
        fail("dashboard backend must expose only GET /capabilities")
    if config_imports != 1:
        fail("dashboard backend must resolve only HonchoClientConfig")
    if health_calls != 1:
        fail("dashboard backend must issue exactly one fixed GET /health probe")


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
    print("read-only verification passed: exact Slice 1 capability handshake")


if __name__ == "__main__":
    main()
