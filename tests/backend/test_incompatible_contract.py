from typing import Any

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from dashboard import plugin_api


def make_app() -> FastAPI:
    app = FastAPI()
    app.include_router(plugin_api.router)
    return app


def install_connection(monkeypatch: Any) -> None:
    connection = plugin_api._Connection(
        base_url="https://honcho.example.invalid",
        workspace_label="synthetic-workspace",
        target="self-hosted",
        headers={},
        timeout=3.0,
    )
    monkeypatch.setattr(plugin_api, "resolve_connection", lambda: connection)


def install_http_result(
    monkeypatch: Any,
    *,
    status_code: int = 200,
    payload: Any = None,
) -> None:
    class FakeAsyncClient:
        def __init__(self, **_options: Any) -> None:
            pass

        async def __aenter__(self) -> "FakeAsyncClient":
            return self

        async def __aexit__(self, *_args: Any) -> None:
            return None

        async def get(self, path: str) -> httpx.Response:
            return httpx.Response(
                status_code,
                json=payload,
                request=httpx.Request("GET", f"https://honcho.example.invalid{path}"),
            )

    monkeypatch.setattr(httpx, "AsyncClient", FakeAsyncClient)


@pytest.mark.parametrize("status_code", [401, 403])
def test_capabilities_maps_auth_failures_to_unauthorized(
    monkeypatch: Any,
    status_code: int,
) -> None:
    install_connection(monkeypatch)
    install_http_result(
        monkeypatch,
        status_code=status_code,
        payload={"detail": "private upstream body"},
    )

    response = TestClient(make_app(), raise_server_exceptions=False).get("/capabilities")

    assert response.status_code == 200
    assert response.json()["state"] == "unauthorized"
    assert "private upstream body" not in response.text


def test_capabilities_maps_server_failure_to_unreachable(monkeypatch: Any) -> None:
    install_connection(monkeypatch)
    install_http_result(
        monkeypatch,
        status_code=503,
        payload={"detail": "private upstream body"},
    )

    response = TestClient(make_app(), raise_server_exceptions=False).get("/capabilities")

    assert response.status_code == 200
    assert response.json()["state"] == "unreachable"
    assert "private upstream body" not in response.text


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"status": "degraded"},
        {"status": "ok", "unexpected": "field"},
        ["status", "ok"],
    ],
)
def test_unversioned_health_success_does_not_claim_contract_verification(
    monkeypatch: Any,
    payload: Any,
) -> None:
    install_connection(monkeypatch)
    install_http_result(monkeypatch, payload=payload)

    response = TestClient(make_app(), raise_server_exceptions=False).get("/capabilities")

    assert response.status_code == 200
    assert response.json()["state"] == "ready"
    assert response.json()["supported_contract"] == "honcho-v3.0.11"
    assert response.json()["contract_verified"] is False
    assert "contract" not in response.json()
