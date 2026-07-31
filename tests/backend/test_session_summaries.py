from datetime import datetime
from typing import Any

import httpx
from fastapi import FastAPI
from fastapi.testclient import TestClient

from dashboard import plugin_api


PRIVATE_ITEM = "synthetic-private-session-payload"


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


def test_public_summary_normalizes_honcho_summary_types() -> None:
    for upstream_type, public_type in (
        ("honcho_chat_summary_short", "short"),
        ("honcho_chat_summary_long", "long"),
    ):
        summary = plugin_api._UpstreamSummary.model_validate(
            {
                "content": "Synthetic generated context.",
                "message_id": "synthetic-source-message",
                "summary_type": upstream_type,
                "created_at": "2026-07-29T09:05:00Z",
                "token_count": 4,
            }
        )

        assert plugin_api._public_summary(summary).summary_type == public_type


def test_sessions_returns_recent_bounded_items_without_upstream_payload(
    monkeypatch: Any,
) -> None:
    install_connection(monkeypatch)
    requests: list[tuple[str, str, dict[str, Any]]] = []

    class FakeAsyncClient:
        def __init__(self, **_options: Any) -> None:
            pass

        async def __aenter__(self) -> "FakeAsyncClient":
            return self

        async def __aexit__(self, *_args: Any) -> None:
            return None

        async def post(self, path: str, **kwargs: Any) -> httpx.Response:
            requests.append(("POST", path, kwargs))
            return httpx.Response(
                200,
                json={
                    "items": [
                        {
                            "id": "synthetic-session-2",
                            "is_active": True,
                            "workspace_id": PRIVATE_ITEM,
                            "metadata": {PRIVATE_ITEM: PRIVATE_ITEM},
                            "configuration": {PRIVATE_ITEM: PRIVATE_ITEM},
                            "created_at": "2026-07-29T09:00:00Z",
                        },
                        {
                            "id": "synthetic-session-1",
                            "is_active": False,
                            "workspace_id": PRIVATE_ITEM,
                            "created_at": "2026-07-28T09:00:00Z",
                        },
                    ],
                    "total": 2,
                    "page": 1,
                    "size": 20,
                    "pages": 1,
                },
                request=httpx.Request("POST", f"https://honcho.example.invalid{path}"),
            )

    monkeypatch.setattr(httpx, "AsyncClient", FakeAsyncClient)

    response = TestClient(make_app()).get(
        "/sessions",
        params={"workspace": "attacker-workspace", "size": 100},
    )

    assert response.status_code == 200
    body = response.json()
    observed_at = datetime.fromisoformat(body.pop("observed_at"))
    assert observed_at.tzinfo is not None
    assert body["state"] == "ready"
    assert body["mode"] == "all"
    assert body["total"] == 2
    assert body["page"] == 1
    assert body["pages"] == 1
    assert body["warnings"] == []
    assert [item["session_key"] for item in body["items"]] == [
        "synthetic-session-2",
        "synthetic-session-1",
    ]
    assert body["items"][0]["is_active"] is True
    assert body["items"][1]["is_active"] is False
    assert datetime.fromisoformat(body["items"][0]["created_at"]).tzinfo is not None
    assert PRIVATE_ITEM not in response.text
    assert requests == [
        (
            "POST",
            "/v3/workspaces/synthetic%20workspace%2Fwith%20slash/sessions/list",
            {"params": {"reverse": True, "page": 1, "size": 20}, "json": {}},
        )
    ]


def test_sessions_fetches_a_requested_bounded_page(monkeypatch: Any) -> None:
    install_connection(monkeypatch)
    requests: list[tuple[str, str, dict[str, Any]]] = []

    class FakeAsyncClient:
        def __init__(self, **_options: Any) -> None:
            pass

        async def __aenter__(self) -> "FakeAsyncClient":
            return self

        async def __aexit__(self, *_args: Any) -> None:
            return None

        async def post(self, path: str, **kwargs: Any) -> httpx.Response:
            requests.append(("POST", path, kwargs))
            return httpx.Response(
                200,
                json={
                    "items": [
                        {
                            "id": "synthetic-session-21",
                            "is_active": False,
                            "created_at": "2026-07-20T09:00:00Z",
                        }
                    ],
                    "total": 21,
                    "page": 2,
                    "size": 20,
                    "pages": 2,
                },
                request=httpx.Request("POST", f"https://honcho.example.invalid{path}"),
            )

    monkeypatch.setattr(httpx, "AsyncClient", FakeAsyncClient)

    response = TestClient(make_app()).get("/sessions", params={"page": 2})

    assert response.status_code == 200
    body = response.json()
    assert body["state"] == "ready"
    assert body["page"] == 2
    assert body["pages"] == 2
    assert [item["session_key"] for item in body["items"]] == ["synthetic-session-21"]
    assert requests == [
        (
            "POST",
            "/v3/workspaces/synthetic%20workspace%2Fwith%20slash/sessions/list",
            {"params": {"reverse": True, "page": 2, "size": 20}, "json": {}},
        )
    ]


def test_sessions_rejects_an_upstream_page_outside_its_pagination_envelope(
    monkeypatch: Any,
) -> None:
    install_connection(monkeypatch)

    class FakeAsyncClient:
        def __init__(self, **_options: Any) -> None:
            pass

        async def __aenter__(self) -> "FakeAsyncClient":
            return self

        async def __aexit__(self, *_args: Any) -> None:
            return None

        async def post(self, path: str, **_kwargs: Any) -> httpx.Response:
            return httpx.Response(
                200,
                json={"items": [], "total": 20, "page": 2, "size": 20, "pages": 1},
                request=httpx.Request("POST", f"https://honcho.example.invalid{path}"),
            )

    monkeypatch.setattr(httpx, "AsyncClient", FakeAsyncClient)

    response = TestClient(make_app()).get("/sessions", params={"page": 2})

    assert response.status_code == 200
    assert response.json()["state"] == "unsupported-contract"


def test_summarized_sessions_returns_only_items_with_generated_summaries(
    monkeypatch: Any,
) -> None:
    install_connection(monkeypatch)
    requests: list[tuple[str, str, dict[str, Any]]] = []

    class FakeAsyncClient:
        def __init__(self, **_options: Any) -> None:
            pass

        async def __aenter__(self) -> "FakeAsyncClient":
            return self

        async def __aexit__(self, *_args: Any) -> None:
            return None

        async def post(self, path: str, **kwargs: Any) -> httpx.Response:
            requests.append(("POST", path, kwargs))
            return httpx.Response(
                200,
                json={
                    "items": [
                        {
                            "id": "synthetic-session-with-summary",
                            "is_active": False,
                            "created_at": "2026-07-29T09:00:00Z",
                        },
                        {
                            "id": "synthetic-session-without-summary",
                            "is_active": False,
                            "created_at": "2026-07-28T09:00:00Z",
                        },
                    ],
                    "total": 2,
                    "page": 1,
                    "size": 20,
                    "pages": 1,
                },
                request=httpx.Request("POST", f"https://honcho.example.invalid{path}"),
            )

        async def get(self, path: str, **_kwargs: Any) -> httpx.Response:
            requests.append(("GET", path, {}))
            if path.endswith("synthetic-session-without-summary/summaries"):
                return httpx.Response(
                    200,
                    json={
                        "id": "synthetic-session-without-summary",
                        "short_summary": None,
                        "long_summary": None,
                    },
                    request=httpx.Request("GET", f"https://honcho.example.invalid{path}"),
                )
            return httpx.Response(
                200,
                json={
                    "id": "synthetic-session-with-summary",
                    "short_summary": {
                        "content": "Synthetic generated context.",
                        "message_id": "synthetic-source-message",
                        "summary_type": "honcho_chat_summary_short",
                        "created_at": "2026-07-29T09:05:00Z",
                        "token_count": 4,
                    },
                    "long_summary": {
                        "content": "Synthetic long generated context.",
                        "message_id": "synthetic-source-message-long",
                        "summary_type": "honcho_chat_summary_long",
                        "created_at": "2026-07-29T09:06:00Z",
                        "token_count": 6,
                    },
                },
                request=httpx.Request("GET", f"https://honcho.example.invalid{path}"),
            )

    monkeypatch.setattr(httpx, "AsyncClient", FakeAsyncClient)

    response = TestClient(make_app()).get("/sessions-with-summaries")

    assert response.status_code == 200
    body = response.json()
    body.pop("observed_at")
    assert body["state"] == "ready"
    assert body["mode"] == "summarized"
    assert [item["session_key"] for item in body["items"]] == [
        "synthetic-session-with-summary",
    ]
    assert body["total"] == 2
    assert body["page"] == 1
    assert body["pages"] == 1
    assert "synthetic-source-message" not in response.text
    assert requests == [
        (
            "POST",
            "/v3/workspaces/synthetic%20workspace%2Fwith%20slash/sessions/list",
            {"params": {"reverse": True, "page": 1, "size": 20}, "json": {}},
        ),
        (
            "GET",
            "/v3/workspaces/synthetic%20workspace%2Fwith%20slash/sessions/synthetic-session-with-summary/summaries",
            {},
        ),
        (
            "GET",
            "/v3/workspaces/synthetic%20workspace%2Fwith%20slash/sessions/synthetic-session-without-summary/summaries",
            {},
        ),
    ]


def test_session_summary_returns_derived_context_without_source_provenance(
    monkeypatch: Any,
) -> None:
    install_connection(monkeypatch)
    requests: list[tuple[str, str]] = []

    class FakeAsyncClient:
        def __init__(self, **_options: Any) -> None:
            pass

        async def __aenter__(self) -> "FakeAsyncClient":
            return self

        async def __aexit__(self, *_args: Any) -> None:
            return None

        async def get(self, path: str, **_kwargs: Any) -> httpx.Response:
            requests.append(("GET", path))
            return httpx.Response(
                200,
                json={
                    "id": "synthetic-session/with?unsafe",
                    "short_summary": {
                        "content": "Honcho derived context for a synthetic session.",
                        "summary_type": "honcho_chat_summary_short",
                        "created_at": "2026-07-29T09:05:00Z",
                        "token_count": 12,
                        "message_id": "synthetic-source-message",
                        "workspace_id": PRIVATE_ITEM,
                        "metadata": {PRIVATE_ITEM: PRIVATE_ITEM},
                    },
                    "long_summary": None,
                    "credentials": {PRIVATE_ITEM: PRIVATE_ITEM},
                },
                request=httpx.Request("GET", f"https://honcho.example.invalid{path}"),
            )

    monkeypatch.setattr(httpx, "AsyncClient", FakeAsyncClient)

    response = TestClient(make_app()).get(
        "/session-summary",
        params={"session_id": "synthetic-session/with?unsafe"},
    )

    assert response.status_code == 200
    body = response.json()
    observed_at = datetime.fromisoformat(body.pop("observed_at"))
    assert observed_at.tzinfo is not None
    assert body == {
        "state": "ready",
        "summary": {
            "content": "Honcho derived context for a synthetic session.",
            "summary_type": "short",
            "created_at": "2026-07-29T09:05:00Z",
            "token_count": 12,
            "evidence_status": "context",
            "truncated": False,
        },
        "evidence_status": "context",
        "warnings": [],
    }
    assert PRIVATE_ITEM not in response.text
    assert "synthetic-source-message" not in response.text
    assert requests == [
        (
            "GET",
            "/v3/workspaces/synthetic%20workspace%2Fwith%20slash/sessions/synthetic-session%2Fwith%3Funsafe/summaries",
        )
    ]


def test_session_summary_rejects_a_summary_for_a_different_session(
    monkeypatch: Any,
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
                200,
                json={
                    "id": "synthetic-other-session",
                    "short_summary": {
                        "content": "Synthetic generated context.",
                        "message_id": "synthetic-source-message",
                        "summary_type": "short",
                        "created_at": "2026-07-29T09:05:00Z",
                        "token_count": 4,
                    },
                    "long_summary": None,
                },
                request=httpx.Request("GET", f"https://honcho.example.invalid{path}"),
            )

    monkeypatch.setattr(httpx, "AsyncClient", FakeAsyncClient)

    response = TestClient(make_app()).get(
        "/session-summary",
        params={"session_id": "synthetic-requested-session"},
    )

    assert response.status_code == 200
    assert response.json()["state"] == "unsupported-contract"


def test_session_summary_marks_missing_summary_unavailable(monkeypatch: Any) -> None:
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
                200,
                json={
                    "id": "synthetic-session-without-summary",
                    "short_summary": None,
                    "long_summary": None,
                },
                request=httpx.Request("GET", f"https://honcho.example.invalid{path}"),
            )

    monkeypatch.setattr(httpx, "AsyncClient", FakeAsyncClient)

    response = TestClient(make_app()).get(
        "/session-summary",
        params={"session_id": "synthetic-session-without-summary"},
    )

    assert response.status_code == 200
    body = response.json()
    body.pop("observed_at")
    assert body == {
        "state": "ready",
        "summary": None,
        "evidence_status": "unavailable",
        "warnings": [],
    }


def test_session_summary_truncates_public_summary_content(monkeypatch: Any) -> None:
    install_connection(monkeypatch)
    long_content = "x" * (plugin_api.MAX_PUBLIC_SUMMARY_CHARS + 1)

    class FakeAsyncClient:
        def __init__(self, **_options: Any) -> None:
            pass

        async def __aenter__(self) -> "FakeAsyncClient":
            return self

        async def __aexit__(self, *_args: Any) -> None:
            return None

        async def get(self, path: str, **_kwargs: Any) -> httpx.Response:
            return httpx.Response(
                200,
                json={
                    "id": "synthetic-session-with-long-summary",
                    "short_summary": {
                        "content": long_content,
                        "summary_type": "honcho_chat_summary_short",
                        "created_at": "2026-07-29T09:05:00Z",
                        "token_count": 12,
                        "message_id": "synthetic-source-message",
                    },
                    "long_summary": None,
                },
                request=httpx.Request("GET", f"https://honcho.example.invalid{path}"),
            )

    monkeypatch.setattr(httpx, "AsyncClient", FakeAsyncClient)

    response = TestClient(make_app()).get(
        "/session-summary",
        params={"session_id": "synthetic-session-with-long-summary"},
    )

    assert response.status_code == 200
    body = response.json()
    assert len(body["summary"]["content"]) == plugin_api.MAX_PUBLIC_SUMMARY_CHARS
    assert body["summary"]["truncated"] is True


def test_session_summary_does_not_return_upstream_error_body(monkeypatch: Any) -> None:
    install_connection(monkeypatch)
    private_error = "synthetic-upstream-secret-error-body"

    class FakeAsyncClient:
        def __init__(self, **_options: Any) -> None:
            pass

        async def __aenter__(self) -> "FakeAsyncClient":
            return self

        async def __aexit__(self, *_args: Any) -> None:
            return None

        async def get(self, path: str, **_kwargs: Any) -> httpx.Response:
            return httpx.Response(
                502,
                content=private_error.encode(),
                request=httpx.Request("GET", f"https://honcho.example.invalid{path}"),
            )

    monkeypatch.setattr(httpx, "AsyncClient", FakeAsyncClient)

    response = TestClient(make_app()).get(
        "/session-summary",
        params={"session_id": "synthetic-session"},
    )

    assert response.status_code == 200
    assert response.json()["state"] == "unreachable"
    assert private_error not in response.text
