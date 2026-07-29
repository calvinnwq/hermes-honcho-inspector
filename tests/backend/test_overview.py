from datetime import datetime
from typing import Any

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from dashboard import plugin_api


PRIVATE_ITEM = "synthetic-private-item-payload"


def make_app() -> FastAPI:
    app = FastAPI()
    app.include_router(plugin_api.router)
    return app


def install_connection(monkeypatch: Any) -> None:
    connection = plugin_api._Connection(
        base_url="https://honcho.example.invalid",
        workspace_label="synthetic workspace/with slash",
        target="self-hosted",
        headers={},
        timeout=3.0,
    )
    monkeypatch.setattr(plugin_api, "resolve_connection", lambda: connection)


def test_overview_returns_normalized_totals_and_processing_activity(
    monkeypatch: Any,
) -> None:
    install_connection(monkeypatch)
    requests: list[tuple[str, str, dict[str, Any]]] = []
    payloads = {
        "/health": {"status": "ok"},
        "/v3/workspaces/synthetic%20workspace%2Fwith%20slash/queue/status": {
            "total_work_units": 8,
            "completed_work_units": 5,
            "in_progress_work_units": 1,
            "pending_work_units": 2,
            "sessions": {PRIVATE_ITEM: {"total_work_units": 8}},
        },
        "/v3/workspaces/synthetic%20workspace%2Fwith%20slash/peers/list": {
            "items": [{"id": PRIVATE_ITEM}],
            "total": 12,
            "page": 1,
            "size": 1,
            "pages": 12,
        },
        "/v3/workspaces/synthetic%20workspace%2Fwith%20slash/sessions/list": {
            "items": [{"id": PRIVATE_ITEM}],
            "total": 7,
            "page": 1,
            "size": 1,
            "pages": 7,
        },
        "/v3/workspaces/synthetic%20workspace%2Fwith%20slash/conclusions/list": {
            "items": [{"id": PRIVATE_ITEM, "content": PRIVATE_ITEM}],
            "total": 23,
            "page": 1,
            "size": 1,
            "pages": 23,
        },
    }

    class FakeAsyncClient:
        def __init__(self, **_options: Any) -> None:
            pass

        async def __aenter__(self) -> "FakeAsyncClient":
            return self

        async def __aexit__(self, *_args: Any) -> None:
            return None

        async def get(self, path: str, **kwargs: Any) -> httpx.Response:
            requests.append(("GET", path, kwargs))
            return httpx.Response(
                200,
                json=payloads[path],
                request=httpx.Request("GET", f"https://honcho.example.invalid{path}"),
            )

        async def post(self, path: str, **kwargs: Any) -> httpx.Response:
            requests.append(("POST", path, kwargs))
            return httpx.Response(
                200,
                json=payloads[path],
                request=httpx.Request("POST", f"https://honcho.example.invalid{path}"),
            )

    monkeypatch.setattr(httpx, "AsyncClient", FakeAsyncClient)

    response = TestClient(make_app()).get(
        "/overview",
        params={
            "workspace": "attacker-workspace",
            "path": "/v3/chat",
            "method": "DELETE",
        },
    )

    assert response.status_code == 200
    body = response.json()
    observed_at = datetime.fromisoformat(body.pop("observed_at"))
    assert observed_at.tzinfo is not None
    assert body == {
        "state": "ready",
        "workspace_label": "synthetic workspace/with slash",
        "peer_total": 12,
        "session_total": 7,
        "conclusion_total": 23,
        "queue": {
            "total": 8,
            "completed": 5,
            "in_progress": 1,
            "pending": 2,
        },
        "warnings": ["processing-pending", "processing-in-progress"],
    }
    assert PRIVATE_ITEM not in response.text
    assert requests == [
        ("GET", "/health", {}),
        (
            "GET",
            "/v3/workspaces/synthetic%20workspace%2Fwith%20slash/queue/status",
            {},
        ),
        (
            "POST",
            "/v3/workspaces/synthetic%20workspace%2Fwith%20slash/peers/list",
            {"params": {"page": 1, "size": 1}, "json": {}},
        ),
        (
            "POST",
            "/v3/workspaces/synthetic%20workspace%2Fwith%20slash/sessions/list",
            {"params": {"page": 1, "size": 1}, "json": {}},
        ),
        (
            "POST",
            "/v3/workspaces/synthetic%20workspace%2Fwith%20slash/conclusions/list",
            {"params": {"page": 1, "size": 1}, "json": {}},
        ),
    ]


def test_overview_returns_connection_state_without_network(monkeypatch: Any) -> None:
    monkeypatch.setattr(
        plugin_api,
        "resolve_connection",
        lambda: plugin_api._capability("disabled"),
    )

    class FailIfConstructed:
        def __init__(self, **_options: Any) -> None:
            raise AssertionError("network client must not be constructed")

    monkeypatch.setattr(httpx, "AsyncClient", FailIfConstructed)

    response = TestClient(make_app()).get("/overview")

    assert response.status_code == 200
    body = response.json()
    assert body["state"] == "disabled"
    assert body["workspace_label"] is None
    assert body["peer_total"] is None
    assert body["session_total"] is None
    assert body["conclusion_total"] is None
    assert body["queue"] is None
    assert body["warnings"] == []
    assert datetime.fromisoformat(body["observed_at"]).tzinfo is not None


@pytest.mark.parametrize("route", ["/capabilities", "/overview"])
def test_routes_normalize_invalid_transport_urls(monkeypatch: Any, route: str) -> None:
    install_connection(monkeypatch)

    class InvalidClient:
        def __init__(self, **_options: Any) -> None:
            raise httpx.InvalidURL(PRIVATE_ITEM)

    monkeypatch.setattr(httpx, "AsyncClient", InvalidClient)

    response = TestClient(make_app(), raise_server_exceptions=False).get(route)

    assert response.status_code == 200
    assert response.json()["state"] == "unreachable"
    assert PRIVATE_ITEM not in response.text


@pytest.mark.parametrize(
    "invalid_payload",
    [
        {"items": [], "total": "12", "page": 1, "size": 1, "pages": 0},
        {"items": "private upstream body", "total": 12},
        {"items": [], "total": -1},
        {"items": [], "total": 12},
        {"items": [], "total": 12, "page": 1, "size": 1, "pages": 11},
        {"items": [], "total": 12, "page": 1, "size": 1, "pages": 12},
        {"items": [{}, {}], "total": 12, "page": 1, "size": 1, "pages": 12},
        {
            "items": [{}],
            "total": 9_007_199_254_740_992,
            "page": 1,
            "size": 1,
            "pages": 9_007_199_254_740_992,
        },
    ],
)
def test_overview_fails_closed_on_incompatible_list_shape(
    monkeypatch: Any,
    invalid_payload: Any,
) -> None:
    install_connection(monkeypatch)

    class FakeAsyncClient:
        def __init__(self, **_options: Any) -> None:
            pass

        async def __aenter__(self) -> "FakeAsyncClient":
            return self

        async def __aexit__(self, *_args: Any) -> None:
            return None

        async def get(self, path: str, **_kwargs: Any) -> httpx.Response:
            payload = (
                {"status": "ok"}
                if path == "/health"
                else {
                    "total_work_units": 0,
                    "completed_work_units": 0,
                    "in_progress_work_units": 0,
                    "pending_work_units": 0,
                }
            )
            return httpx.Response(
                200,
                json=payload,
                request=httpx.Request("GET", f"https://honcho.example.invalid{path}"),
            )

        async def post(self, path: str, **_kwargs: Any) -> httpx.Response:
            return httpx.Response(
                200,
                json=invalid_payload,
                request=httpx.Request("POST", f"https://honcho.example.invalid{path}"),
            )

    monkeypatch.setattr(httpx, "AsyncClient", FakeAsyncClient)

    response = TestClient(make_app(), raise_server_exceptions=False).get("/overview")

    assert response.status_code == 200
    assert response.json()["state"] == "unsupported-contract"
    assert response.json()["warnings"] == ["unsupported-contract"]
    assert "private upstream body" not in response.text


@pytest.mark.parametrize(
    "queue_payload",
    [
        {
            "total_work_units": 8,
            "completed_work_units": 5,
            "in_progress_work_units": 1,
            "pending_work_units": 3,
        },
        {
            "total_work_units": 8,
            "completed_work_units": -1,
            "in_progress_work_units": 1,
            "pending_work_units": 2,
        },
        {
            "total_work_units": 9_007_199_254_740_992,
            "completed_work_units": 9_007_199_254_740_992,
            "in_progress_work_units": 0,
            "pending_work_units": 0,
        },
    ],
)
def test_overview_fails_closed_on_inconsistent_queue_counts(
    monkeypatch: Any,
    queue_payload: dict[str, int],
) -> None:
    install_connection(monkeypatch)

    class FakeAsyncClient:
        def __init__(self, **_options: Any) -> None:
            pass

        async def __aenter__(self) -> "FakeAsyncClient":
            return self

        async def __aexit__(self, *_args: Any) -> None:
            return None

        async def get(self, path: str, **_kwargs: Any) -> httpx.Response:
            payload = {"status": "ok"} if path == "/health" else queue_payload
            return httpx.Response(
                200,
                json=payload,
                request=httpx.Request("GET", f"https://honcho.example.invalid{path}"),
            )

        async def post(self, *_args: Any, **_kwargs: Any) -> httpx.Response:
            raise AssertionError("list requests must not run after invalid queue data")

    monkeypatch.setattr(httpx, "AsyncClient", FakeAsyncClient)

    response = TestClient(make_app(), raise_server_exceptions=False).get("/overview")

    assert response.status_code == 200
    assert response.json()["state"] == "unsupported-contract"
    assert response.json()["queue"] is None


@pytest.mark.parametrize(
    ("status_code", "expected_state"),
    [(401, "unauthorized"), (403, "unauthorized"), (404, "unsupported-contract"), (503, "unreachable")],
)
def test_overview_maps_upstream_failures_to_safe_states(
    monkeypatch: Any,
    status_code: int,
    expected_state: str,
) -> None:
    install_connection(monkeypatch)

    class FakeAsyncClient:
        def __init__(self, **_options: Any) -> None:
            pass

        async def __aenter__(self) -> "FakeAsyncClient":
            return self

        async def __aexit__(self, *_args: Any) -> None:
            return None

        async def get(self, path: str, **_kwargs: Any) -> httpx.Response:
            return httpx.Response(
                status_code,
                json={"detail": PRIVATE_ITEM},
                request=httpx.Request("GET", f"https://honcho.example.invalid{path}"),
            )

    monkeypatch.setattr(httpx, "AsyncClient", FakeAsyncClient)

    response = TestClient(make_app(), raise_server_exceptions=False).get("/overview")

    assert response.status_code == 200
    assert response.json()["state"] == expected_state
    assert PRIVATE_ITEM not in response.text
