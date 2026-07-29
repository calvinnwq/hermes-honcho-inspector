#!/usr/bin/env python3
"""Verify the fixed, read-only Slice 2 Overview runtime contract."""

import ast
import hashlib
import sys
from pathlib import Path
from typing import NoReturn

ROOT = Path(sys.argv[1] if len(sys.argv) > 1 else Path(__file__).resolve().parents[1]).resolve()
APPROVED_SHA256 = {
    "dashboard/plugin_api.py": "394fcfd3816c9a45b25feab5b532854b221dcdcf1ec53d227e3a439ffc4e4918",
    "desktop/plugin.ts": "502b9b8b0bdeaf9cde19b239ee5c546c81bbccafa61e87501462ef3096319a51",
    "desktop/overview-model.ts": "598020e0a90d69e4b91cbe6be7d7880277751fce3afa875114d4b987a72a67f3",
    "dist/desktop-plugins/honcho-inspector/plugin.js": "ee847a03243c96f7448b0290fba950589b423873aead38f773f6b4af589e6dbc",
}


def fail(message: str) -> NoReturn:
    raise SystemExit(f"read-only verification failed: {message}")


def read_bytes(relative: str) -> bytes:
    try:
        return (ROOT / relative).read_bytes()
    except OSError as error:
        fail(f"cannot read {relative}: {error}")


def read_text(relative: str) -> str:
    try:
        return read_bytes(relative).decode("utf-8")
    except UnicodeError as error:
        fail(f"cannot decode {relative}: {error}")


def verify_approved_hash(relative: str) -> None:
    digest = hashlib.sha256(read_bytes(relative)).hexdigest()
    if digest != APPROVED_SHA256[relative]:
        fail(f"{relative} differs from the approved Slice 2 runtime")


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


def fixed_list_post(call: ast.Call, source: str) -> bool:
    if len(call.args) != 1:
        return False
    path = ast.get_source_segment(source, call.args[0])
    if path != 'f"{workspace_prefix}/{resource}/list"':
        return False
    keywords = {keyword.arg: keyword.value for keyword in call.keywords if keyword.arg}
    if set(keywords) != {"params", "json"}:
        return False

    params = keywords["params"]
    body = keywords["json"]
    return (
        isinstance(params, ast.Dict)
        and [key.value for key in params.keys if isinstance(key, ast.Constant)]
        == ["page", "size"]
        and [value.value for value in params.values if isinstance(value, ast.Constant)]
        == [1, 1]
        and isinstance(body, ast.Dict)
        and not body.keys
        and not body.values
    )


def verify_dashboard_plugin() -> None:
    verify_approved_hash("dashboard/plugin_api.py")
    source = read_text("dashboard/plugin_api.py")
    tree = ast.parse(source)
    routes: list[tuple[str, str]] = []
    client_gets: list[str] = []
    list_posts = 0
    list_resource_loops = 0
    config_imports = 0
    forbidden_modules = {"honcho", "os", "pathlib", "requests", "socket", "subprocess"}
    forbidden_client_methods = {
        "delete",
        "options",
        "patch",
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
            if isinstance(node, ast.ImportFrom) and node.module == "plugins.memory.honcho.client":
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

        if (
            isinstance(node, ast.For)
            and isinstance(node.target, ast.Name)
            and node.target.id == "resource"
            and isinstance(node.iter, ast.Tuple)
            and [item.value for item in node.iter.elts if isinstance(item, ast.Constant)]
            == ["peers", "sessions", "conclusions"]
        ):
            list_resource_loops += 1

        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
            if node.func.attr in forbidden_client_methods:
                fail("dashboard backend contains a forbidden HTTP client method")
            if isinstance(node.func.value, ast.Name) and node.func.value.id == "client":
                if node.func.attr == "get":
                    if len(node.args) != 1 or node.keywords:
                        fail("Honcho GET operations must have fixed argument shapes")
                    client_gets.append(ast.get_source_segment(source, node.args[0]) or "")
                elif node.func.attr == "post":
                    if not fixed_list_post(node, source):
                        fail("Honcho list operation must remain a fixed size-one POST")
                    list_posts += 1
                else:
                    fail("dashboard backend contains an unapproved HTTP operation")

    if routes != [("get", "/capabilities"), ("get", "/overview")]:
        fail("dashboard backend must expose only GET /capabilities and GET /overview")
    if config_imports != 1:
        fail("dashboard backend must resolve only HonchoClientConfig")
    if client_gets.count('"/health"') != 2 or client_gets.count(
        'f"{workspace_prefix}/queue/status"'
    ) != 1 or len(client_gets) != 3:
        fail("Honcho GET operations differ from the approved health and queue probes")
    if list_posts != 1 or list_resource_loops != 1:
        fail("Honcho totals must use one fixed peers/sessions/conclusions list loop")
    if 'quote(connection.workspace_label, safe="")' not in source:
        fail("workspace path must remain server-resolved and safely encoded")


def verify_desktop_plugin() -> None:
    for relative in (
        "desktop/plugin.ts",
        "desktop/overview-model.ts",
        "dist/desktop-plugins/honcho-inspector/plugin.js",
    ):
        verify_approved_hash(relative)

    source = read_text("desktop/plugin.ts")
    model = read_text("desktop/overview-model.ts")
    bundle = read_text("dist/desktop-plugins/honcho-inspector/plugin.js")
    combined = "\n".join((source, model, bundle))
    forbidden = (
        "host.request",
        "globalThis[\"fetch\"]",
        "XMLHttpRequest",
        "sendBeacon(",
        "localStorage.",
        "document.",
        "ctx.socket(",
    )
    if any(token in combined for token in forbidden):
        fail("Desktop runtime contains an unapproved capability")
    required = (
        'ctx.rest<unknown>("/overview", { timeoutMs: OVERVIEW_TIMEOUT_MS })',
        "useValue(host.state.profile)",
        'queryKey: [PLUGIN_ID, "overview", profile]',
        "ctx.registerMany(",
        "area: ROUTES_AREA",
        "area: SIDEBAR_NAV_AREA",
        "area: PALETTE_AREA",
        'const OVERVIEW_PATH = "/honcho-inspector"',
        "defaultEnabled: false",
    )
    if any(token not in source for token in required):
        fail("Desktop source differs from the fixed Overview contribution contract")


def main() -> None:
    verify_general_plugin()
    verify_dashboard_plugin()
    verify_desktop_plugin()
    print("read-only verification passed: exact Slice 2 Overview contract")


if __name__ == "__main__":
    main()
