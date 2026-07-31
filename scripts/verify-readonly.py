#!/usr/bin/env python3
"""Verify the fixed, read-only Slice 3A Session Summaries runtime contract."""

import ast
import hashlib
import re
import sys
from pathlib import Path
from typing import NoReturn

ROOT = Path(sys.argv[1] if len(sys.argv) > 1 else Path(__file__).resolve().parents[1]).resolve()
APPROVED_SHA256 = {
    "dashboard/plugin_api.py": "6fe45190290c15dcfab01a7a2a7c0b06a746546b46120e00fa717db6cbfe5bf8",
    "desktop/plugin.ts": "21c702ea84d8e2b60c6a8cb9f2a8b23f9e95baa218f8ff36f4c066d55e219a4d",
    "desktop/overview-model.ts": "598020e0a90d69e4b91cbe6be7d7880277751fce3afa875114d4b987a72a67f3",
    "desktop/session-model.ts": "5079576543fae14155847182b0c7024a42d7346dc3e635743d310fe4fcf0c5a2",
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
        fail(f"{relative} differs from the approved Slice 3A runtime")


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


def fixed_recent_sessions_post(call: ast.Call, source: str) -> bool:
    if len(call.args) != 1 or ast.get_source_segment(source, call.args[0]) != 'f"/v3/workspaces/{workspace_path}/sessions/list"':
        return False
    keywords = {keyword.arg: keyword.value for keyword in call.keywords if keyword.arg}
    if set(keywords) != {"params", "json"}:
        return False

    params = keywords["params"]
    body = keywords["json"]
    if not isinstance(params, ast.Dict) or not isinstance(body, ast.Dict) or body.keys or body.values:
        return False
    keys = [key.value for key in params.keys if isinstance(key, ast.Constant)]
    values = params.values
    return (
        keys == ["reverse", "page", "size"]
        and isinstance(values[0], ast.Constant)
        and values[0].value is True
        and isinstance(values[1], ast.Name)
        and values[1].id == "page"
        and isinstance(values[2], ast.Name)
        and values[2].id == "SESSION_LIST_SIZE"
    )


def http_client_bindings(tree: ast.AST) -> set[str]:
    bindings: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.AsyncWith):
            for item in node.items:
                expression = item.context_expr
                if (
                    isinstance(expression, ast.Call)
                    and isinstance(expression.func, ast.Attribute)
                    and isinstance(expression.func.value, ast.Name)
                    and expression.func.value.id == "httpx"
                    and expression.func.attr == "AsyncClient"
                    and isinstance(item.optional_vars, ast.Name)
                ):
                    bindings.add(item.optional_vars.id)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            for argument in node.args.args:
                annotation = argument.annotation
                if (
                    isinstance(annotation, ast.Attribute)
                    and isinstance(annotation.value, ast.Name)
                    and annotation.value.id == "httpx"
                    and annotation.attr == "AsyncClient"
                ):
                    bindings.add(argument.arg)

    changed = True
    while changed:
        changed = False
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.Assign)
                and len(node.targets) == 1
                and isinstance(node.targets[0], ast.Name)
                and isinstance(node.value, ast.Name)
                and node.value.id in bindings
                and node.targets[0].id not in bindings
            ):
                bindings.add(node.targets[0].id)
                changed = True
    return bindings


def verify_dashboard_plugin() -> None:
    verify_approved_hash("dashboard/plugin_api.py")
    source = read_text("dashboard/plugin_api.py")
    tree = ast.parse(source)
    client_bindings = http_client_bindings(tree)
    routes: list[tuple[str, str]] = []
    client_gets: list[str] = []
    list_posts = 0
    recent_session_posts = 0
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
            if any(
                module == "urllib.request" or module.split(".", 1)[0] in forbidden_modules
                for module in modules
            ):
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
            if (
                isinstance(node.func.value, ast.Name)
                and node.func.value.id == "httpx"
                and node.func.attr != "AsyncClient"
            ):
                fail("dashboard backend contains an unapproved direct HTTP operation")
            if (
                isinstance(node.func.value, ast.Name)
                and node.func.value.id == "router"
                and node.func.attr == "add_api_route"
            ):
                fail("dashboard backend may register only declarative fixed routes")
            if node.func.attr in forbidden_client_methods:
                fail("dashboard backend contains a forbidden HTTP client method")
            if isinstance(node.func.value, ast.Name) and node.func.value.id in client_bindings:
                if node.func.attr == "get":
                    if len(node.args) != 1 or node.keywords:
                        fail("Honcho GET operations must have fixed argument shapes")
                    client_gets.append(ast.get_source_segment(source, node.args[0]) or "")
                elif node.func.attr == "post":
                    if fixed_list_post(node, source):
                        list_posts += 1
                    elif fixed_recent_sessions_post(node, source):
                        recent_session_posts += 1
                    else:
                        fail("Honcho POST operations differ from the fixed read-only contracts")
                else:
                    fail("dashboard backend contains an unapproved HTTP operation")

    if routes != [
        ("get", "/capabilities"),
        ("get", "/overview"),
        ("get", "/sessions"),
        ("get", "/sessions-with-summaries"),
        ("get", "/session-summary"),
    ]:
        fail("dashboard backend must expose only fixed read-only Inspector routes")
    if config_imports != 1:
        fail("dashboard backend must resolve only HonchoClientConfig")
    if client_gets.count('"/health"') != 2 or client_gets.count(
        'f"{workspace_prefix}/queue/status"'
    ) != 1 or client_gets.count(
        'f"/v3/workspaces/{workspace_path}/sessions/{session_path}/summaries"'
    ) != 1 or len(client_gets) != 4:
        fail("Honcho GET operations differ from the approved read-only probes")
    if list_posts != 1 or recent_session_posts != 1 or list_resource_loops != 1:
        fail("Honcho list operations differ from the approved bounded contracts")
    if (
        'quote(connection.workspace_label, safe="")' not in source
        or 'quote(session_id, safe="")' not in source
        or "MAX_SESSION_PAGE = 1_000" not in source
        or "Query(ge=1, le=MAX_SESSION_PAGE)" not in source
    ):
        fail("workspace and session paths must remain server-resolved and safely encoded")
    if (
        "OVERVIEW_BUDGET_SECONDS = 55.0" not in source
        or "async with asyncio.timeout(OVERVIEW_BUDGET_SECONDS)" not in source
        or source.count("follow_redirects=False") != 5
        or "follow_redirects=True" in source
    ):
        fail("read-only backend requests must retain fixed deadlines and redirect policy")


def verify_desktop_plugin() -> None:
    for relative in (
        "desktop/plugin.ts",
        "desktop/overview-model.ts",
        "desktop/session-model.ts",
    ):
        verify_approved_hash(relative)

    source = read_text("desktop/plugin.ts")
    model = read_text("desktop/overview-model.ts")
    session_model = read_text("desktop/session-model.ts")
    bundle = read_text("dist/desktop-plugins/honcho-inspector/plugin.js")
    combined = "\n".join((source, model, session_model, bundle))
    forbidden = (
        "host.request",
        "globalThis[\"fetch\"]",
        "XMLHttpRequest",
        "sendBeacon(",
        "localStorage.",
        "document.",
        "ctx.socket(",
        "const credential",
        "api_key",
        "apiKey",
        "Bearer ",
    )
    if any(token in combined for token in forbidden):
        fail("Desktop runtime contains an unapproved capability")
    if re.search(r"(?<![\w$])fetch\s*(?:<[^>]*>)?\s*\(", combined):
        fail("Desktop runtime contains an unapproved capability")
    required = (
        "const OVERVIEW_BUDGET_MS = 55_000",
        "const OVERVIEW_TIMEOUT_MS = OVERVIEW_BUDGET_MS + 10_000",
        "const SESSION_VIEW_TIMEOUT_MS = 30_000",
        'ctx.rest<unknown>("/overview", { timeoutMs: OVERVIEW_TIMEOUT_MS })',
        "sessionListPath(page, summarizedOnly)",
        "`/session-summary?session_id=${encodeURIComponent(selectedSessionKey)}`",
        'queryKey: [PLUGIN_ID, "overview", profile]',
        'queryKey: [PLUGIN_ID, "sessions", profile, page, summarizedOnly ? "summarized" : "all"]',
        'queryKey: [PLUGIN_ID, "session-summary", profile, selectedSessionKey]',
        "function SessionPagination",
        "function SessionSummaryModal",
        "dialog.showModal()",
        "onCancel:",
        "autoFocus: true",
        "returnFocusRef.current?.focus()",
        'role: "dialog"',
        '"aria-modal": true',
        "bg-(--ui-chat-bubble-background)",
        "border-(--stroke-nous)",
        "shadow-nous",
        "Derived summary",
        "Evidence: ${EVIDENCE_COPY[status]}",
        "exact claim-to-message attribution",
        "jsx(SessionSummaries, { ctx, profile }, profile)",
        "useValue(host.state.profile)",
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
    print("read-only verification passed: fixed Slice 3A Session Summaries contract")


if __name__ == "__main__":
    main()
