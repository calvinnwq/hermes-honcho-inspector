from types import SimpleNamespace
from typing import Any

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from dashboard import plugin_api
from _support import install_config_module

SECRET = "synthetic-secret-token-value"
PRIVATE_URL = "https://private-host.example.invalid"


def make_app() -> FastAPI:
    app = FastAPI()
    app.include_router(plugin_api.router)
    return app


@pytest.mark.parametrize(
    "base_url",
    [
        "http://127.0.0.1:8000",
        "http://honcho:8000",
        "http://honcho.local:8000",
        "http://host.docker.internal:8000",
        "https://self-hosted.example.invalid",
    ],
)
def test_inherited_cloud_key_is_not_sent_to_any_self_hosted_target(
    monkeypatch: Any,
    base_url: str,
) -> None:
    install_config_module(
        monkeypatch,
        SimpleNamespace(
            host="hermes",
            enabled=True,
            explicitly_configured=True,
            workspace_id="synthetic-workspace",
            api_key=SECRET,
            base_url=base_url,
            environment="local",
            timeout=3.0,
            raw={"apiKey": SECRET},
        ),
    )
    client_options: list[dict[str, Any]] = []

    class FakeAsyncClient:
        def __init__(self, **options: Any) -> None:
            client_options.append(options)

        async def __aenter__(self) -> "FakeAsyncClient":
            return self

        async def __aexit__(self, *_args: Any) -> None:
            return None

        async def get(self, path: str) -> httpx.Response:
            return httpx.Response(
                200,
                json={"status": "ok"},
                request=httpx.Request("GET", f"https://example.invalid{path}"),
            )

    monkeypatch.setattr(httpx, "AsyncClient", FakeAsyncClient)

    response = TestClient(make_app()).get("/capabilities")

    assert response.status_code == 200
    assert client_options[0]["headers"] == {}
    assert SECRET not in response.text


@pytest.mark.parametrize(
    "base_url",
    [
        "http://127.0.0.1:8000",
        "http://honcho:8000",
        "https://self-hosted.example.invalid",
    ],
)
def test_explicit_host_auth_key_is_sent_only_to_its_self_hosted_target(
    monkeypatch: Any,
    base_url: str,
) -> None:
    install_config_module(
        monkeypatch,
        SimpleNamespace(
            host="hermes",
            enabled=True,
            explicitly_configured=True,
            workspace_id="synthetic-workspace",
            api_key=SECRET,
            base_url=base_url,
            environment="local",
            timeout=3.0,
            raw={"hosts": {"hermes": {"apiKey": SECRET}}},
        ),
    )
    client_options: list[dict[str, Any]] = []

    class FakeAsyncClient:
        def __init__(self, **options: Any) -> None:
            client_options.append(options)

        async def __aenter__(self) -> "FakeAsyncClient":
            return self

        async def __aexit__(self, *_args: Any) -> None:
            return None

        async def get(self, path: str) -> httpx.Response:
            return httpx.Response(
                200,
                json={"status": "ok"},
                request=httpx.Request("GET", f"https://example.invalid{path}"),
            )

    monkeypatch.setattr(httpx, "AsyncClient", FakeAsyncClient)

    response = TestClient(make_app()).get("/capabilities")

    assert response.status_code == 200
    assert client_options[0]["headers"] == {"Authorization": f"Bearer {SECRET}"}
    assert SECRET not in response.text


def test_empty_profile_block_falls_back_to_legacy_host_auth(
    monkeypatch: Any,
) -> None:
    install_config_module(
        monkeypatch,
        SimpleNamespace(
            host="hermes_local",
            enabled=True,
            explicitly_configured=True,
            workspace_id="synthetic-workspace",
            api_key=SECRET,
            base_url=PRIVATE_URL,
            environment="local",
            timeout=3.0,
            raw={
                "hosts": {
                    "hermes_local": {},
                    "hermes.local": {"apiKey": SECRET},
                }
            },
        ),
    )

    connection = plugin_api.resolve_connection()

    assert isinstance(connection, plugin_api._Connection)
    assert connection.headers == {"Authorization": f"Bearer {SECRET}"}


def test_secret_bearing_transport_error_is_not_returned_or_logged(
    monkeypatch: Any,
    caplog: Any,
) -> None:
    connection = plugin_api._Connection(
        base_url=PRIVATE_URL,
        workspace_label="synthetic-workspace",
        target="self-hosted",
        headers={"Authorization": f"Bearer {SECRET}"},
        timeout=3.0,
    )
    monkeypatch.setattr(plugin_api, "resolve_connection", lambda: connection)

    class FakeAsyncClient:
        def __init__(self, **_options: Any) -> None:
            pass

        async def __aenter__(self) -> "FakeAsyncClient":
            return self

        async def __aexit__(self, *_args: Any) -> None:
            return None

        async def get(self, path: str) -> httpx.Response:
            request = httpx.Request("GET", f"{PRIVATE_URL}{path}")
            raise httpx.ConnectError(
                f"connection failed for {PRIVATE_URL} with {SECRET}",
                request=request,
            )

    monkeypatch.setattr(httpx, "AsyncClient", FakeAsyncClient)

    response = TestClient(make_app(), raise_server_exceptions=False).get("/capabilities")

    combined = response.text + caplog.text
    assert response.status_code == 200
    assert response.json()["state"] == "unreachable"
    assert SECRET not in combined
    assert PRIVATE_URL not in combined


def test_secret_bearing_config_error_is_not_returned_or_logged(
    monkeypatch: Any,
    caplog: Any,
) -> None:
    install_config_module(
        monkeypatch,
        SimpleNamespace(
            enabled=True,
            explicitly_configured=True,
            workspace_id="synthetic-workspace",
            api_key=SECRET,
            base_url=PRIVATE_URL,
            environment="local",
            timeout=object(),
        ),
    )

    response = TestClient(make_app(), raise_server_exceptions=False).get("/capabilities")

    combined = response.text + caplog.text
    assert response.status_code == 200
    assert response.json()["state"] == "missing-configuration"
    assert SECRET not in combined
    assert PRIVATE_URL not in combined
