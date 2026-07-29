from types import SimpleNamespace
from typing import Any

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from dashboard import plugin_api
from _support import install_config_module


def test_capabilities_route_exists(monkeypatch: Any) -> None:
    monkeypatch.setattr(
        plugin_api,
        "resolve_connection",
        lambda: plugin_api._capability("missing-configuration"),
    )
    app = FastAPI()
    app.include_router(plugin_api.router)

    response = TestClient(app).get("/capabilities")

    assert response.status_code == 200
    assert response.json() == {
        "state": "missing-configuration",
        "workspace_label": None,
        "target": "unknown",
        "supported_contract": "honcho-v3.0.11",
        "contract_verified": False,
        "plugin_version": "0.1.0",
        "features": {
            "peer_cards": False,
            "conclusions": False,
            "sessions": False,
            "messages": False,
            "queue_status": False,
            "exact_source_provenance": False,
            "confidence": False,
            "premises": False,
        },
        "warnings": [],
    }


def test_capabilities_reports_ready_for_the_fixed_health_probe(monkeypatch: Any) -> None:
    install_config_module(
        monkeypatch,
        SimpleNamespace(
            enabled=True,
            explicitly_configured=True,
            workspace_id="synthetic-workspace",
            api_key=None,
            base_url="https://honcho.example.invalid",
            environment="local",
            timeout=3.0,
        ),
    )
    requests: list[tuple[str, str]] = []
    client_options: list[dict[str, Any]] = []

    class FakeAsyncClient:
        def __init__(self, **options: Any) -> None:
            client_options.append(options)

        async def __aenter__(self) -> "FakeAsyncClient":
            return self

        async def __aexit__(self, *_args: Any) -> None:
            return None

        async def get(self, path: str) -> httpx.Response:
            requests.append(("GET", path))
            return httpx.Response(
                200,
                json={"status": "ok"},
                request=httpx.Request("GET", f"https://honcho.example.invalid{path}"),
            )

    monkeypatch.setattr(httpx, "AsyncClient", FakeAsyncClient)
    app = FastAPI()
    app.include_router(plugin_api.router)

    response = TestClient(app).get(
        "/capabilities",
        params={
            "host": "https://attacker.example.invalid",
            "workspace": "attacker-workspace",
            "method": "POST",
            "path": "/v3/chat",
            "authorization": "Bearer attacker-token",
        },
    )

    assert response.status_code == 200
    assert response.json() == {
        "state": "ready",
        "workspace_label": "synthetic-workspace",
        "target": "self-hosted",
        "supported_contract": "honcho-v3.0.11",
        "contract_verified": False,
        "plugin_version": "0.1.0",
        "features": {
            "peer_cards": False,
            "conclusions": False,
            "sessions": False,
            "messages": False,
            "queue_status": False,
            "exact_source_provenance": False,
            "confidence": False,
            "premises": False,
        },
        "warnings": [],
    }
    assert requests == [("GET", "/health")]
    assert client_options == [
        {
            "base_url": "https://honcho.example.invalid",
            "headers": {},
            "timeout": 3.0,
            "follow_redirects": False,
        }
    ]


def test_hosted_connection_uses_the_fixed_target_and_server_side_token(
    monkeypatch: Any,
) -> None:
    secret = "synthetic-hosted-token"
    install_config_module(
        monkeypatch,
        SimpleNamespace(
            enabled=True,
            explicitly_configured=True,
            workspace_id="synthetic-workspace",
            api_key=secret,
            base_url=None,
            environment="production",
            timeout=None,
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
                request=httpx.Request("GET", f"https://api.honcho.dev{path}"),
            )

    monkeypatch.setattr(httpx, "AsyncClient", FakeAsyncClient)
    app = FastAPI()
    app.include_router(plugin_api.router)

    response = TestClient(app).get("/capabilities")

    assert response.status_code == 200
    assert response.json()["target"] == "hosted"
    assert secret not in response.text
    assert "api.honcho.dev" not in response.text
    assert client_options == [
        {
            "base_url": "https://api.honcho.dev",
            "headers": {"Authorization": f"Bearer {secret}"},
            "timeout": 10.0,
            "follow_redirects": False,
        }
    ]


def test_local_environment_without_base_url_fails_closed_before_network(
    monkeypatch: Any,
) -> None:
    install_config_module(
        monkeypatch,
        SimpleNamespace(
            enabled=True,
            explicitly_configured=True,
            workspace_id="synthetic-workspace",
            api_key="must-not-trigger-cloud",
            base_url=None,
            environment="local",
            timeout=None,
        ),
    )

    class FailIfConstructed:
        def __init__(self, **_options: Any) -> None:
            raise AssertionError("network client must not be constructed")

    monkeypatch.setattr(httpx, "AsyncClient", FailIfConstructed)
    app = FastAPI()
    app.include_router(plugin_api.router)

    response = TestClient(app, raise_server_exceptions=False).get("/capabilities")

    assert response.status_code == 200
    assert response.json()["state"] == "missing-configuration"


@pytest.mark.parametrize("workspace_id", [".", "..", " . ", " .. "])
def test_dot_segment_workspace_fails_closed_before_network(
    monkeypatch: Any,
    workspace_id: str,
) -> None:
    install_config_module(
        monkeypatch,
        SimpleNamespace(
            enabled=True,
            explicitly_configured=True,
            workspace_id=workspace_id,
            api_key=None,
            base_url="https://honcho.example.invalid",
            environment="local",
            timeout=None,
            raw={},
            host="hermes",
        ),
    )

    class FailIfConstructed:
        def __init__(self, **_options: Any) -> None:
            raise AssertionError("network client must not be constructed")

    monkeypatch.setattr(httpx, "AsyncClient", FailIfConstructed)
    app = FastAPI()
    app.include_router(plugin_api.router)

    response = TestClient(app, raise_server_exceptions=False).get("/overview")

    assert response.status_code == 200
    assert response.json()["state"] == "missing-configuration"


@pytest.mark.parametrize(
    "base_url",
    [
        "not-a-url",
        "ftp://private-host.example.invalid",
        "https://user@private-host.example.invalid",
        "https://private-host.example.invalid?mode=debug",
        "https://private-host.example.invalid#fragment",
        "https://private-host.example.invalid:notaport",
        "https://private-host.example.invalid/custom-prefix",
        "https://private-host.example.invalid/v3;debug",
    ],
)
def test_invalid_self_hosted_base_url_fails_closed_before_network(
    monkeypatch: Any,
    base_url: str,
) -> None:
    install_config_module(
        monkeypatch,
        SimpleNamespace(
            enabled=True,
            explicitly_configured=True,
            workspace_id="synthetic-workspace",
            api_key=None,
            base_url=base_url,
            environment="local",
            timeout=None,
            raw={},
            host="hermes",
        ),
    )

    class FailIfConstructed:
        def __init__(self, **_options: Any) -> None:
            raise AssertionError("network client must not be constructed")

    monkeypatch.setattr(httpx, "AsyncClient", FailIfConstructed)
    app = FastAPI()
    app.include_router(plugin_api.router)

    response = TestClient(app, raise_server_exceptions=False).get("/capabilities")

    assert response.status_code == 200
    assert response.json()["state"] == "missing-configuration"


@pytest.mark.parametrize(
    "base_url",
    [
        "https://self-hosted.example.invalid",
        "https://self-hosted.example.invalid/",
        "https://self-hosted.example.invalid/v3",
        "https://self-hosted.example.invalid/v3/",
    ],
)
def test_health_probe_uses_root_path_with_real_httpx_url_joining(
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
            api_key=None,
            base_url=base_url,
            environment="local",
            timeout=3.0,
            raw={},
        ),
    )
    requested_urls: list[str] = []
    real_async_client = httpx.AsyncClient

    def handle(request: httpx.Request) -> httpx.Response:
        requested_urls.append(str(request.url))
        return httpx.Response(200, json={"status": "ok"}, request=request)

    def make_client(**options: Any) -> httpx.AsyncClient:
        return real_async_client(transport=httpx.MockTransport(handle), **options)

    monkeypatch.setattr(httpx, "AsyncClient", make_client)
    app = FastAPI()
    app.include_router(plugin_api.router)

    response = TestClient(app).get("/capabilities")

    assert response.status_code == 200
    assert response.json()["state"] == "ready"
    assert requested_urls == ["https://self-hosted.example.invalid/health"]


def test_disabled_connection_does_not_attempt_network_io(monkeypatch: Any) -> None:
    install_config_module(
        monkeypatch,
        SimpleNamespace(
            enabled=False,
            explicitly_configured=True,
            workspace_id="synthetic-workspace",
            api_key="unused-token",
            base_url=None,
            environment="production",
            timeout=None,
        ),
    )

    class FailIfConstructed:
        def __init__(self, **_options: Any) -> None:
            raise AssertionError("network client must not be constructed")

    monkeypatch.setattr(httpx, "AsyncClient", FailIfConstructed)
    app = FastAPI()
    app.include_router(plugin_api.router)

    response = TestClient(app).get("/capabilities")

    assert response.status_code == 200
    assert response.json()["state"] == "disabled"


def test_unknown_routes_and_methods_fail_before_network_io(monkeypatch: Any) -> None:
    class FailIfConstructed:
        def __init__(self, **_options: Any) -> None:
            raise AssertionError("network client must not be constructed")

    monkeypatch.setattr(httpx, "AsyncClient", FailIfConstructed)
    app = FastAPI()
    app.include_router(plugin_api.router)
    client = TestClient(app)

    assert client.post("/capabilities", json={"path": "/v3/chat"}).status_code == 405
    assert client.get("/proxy", params={"path": "/health"}).status_code == 404
