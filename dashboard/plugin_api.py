"""Read-only Honcho capability reporting for Honcho Inspector."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal
from urllib.parse import urlparse

import httpx
from fastapi import APIRouter
from pydantic import BaseModel, ConfigDict

PLUGIN_VERSION = "0.1.0"
HONCHO_SUPPORTED_CONTRACT = "honcho-v3.0.11"
HOSTED_BASE_URL = "https://api.honcho.dev"
DEFAULT_TIMEOUT_SECONDS = 10.0
MIN_TIMEOUT_SECONDS = 1.0
MAX_TIMEOUT_SECONDS = 30.0

CapabilityState = Literal[
    "ready",
    "disabled",
    "missing-configuration",
    "unreachable",
    "unauthorized",
]
ConnectionTarget = Literal["hosted", "self-hosted", "unknown"]


class CapabilityFeatures(BaseModel):
    """Inspector features proven available in the current release slice."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    peer_cards: bool = False
    conclusions: bool = False
    sessions: bool = False
    messages: bool = False
    queue_status: bool = False
    exact_source_provenance: bool = False
    confidence: bool = False
    premises: bool = False


class CapabilityResponse(BaseModel):
    """Public, secret-free connection capability response."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    state: CapabilityState
    workspace_label: str | None = None
    target: ConnectionTarget = "unknown"
    supported_contract: Literal["honcho-v3.0.11"] = HONCHO_SUPPORTED_CONTRACT
    contract_verified: Literal[False] = False
    plugin_version: Literal["0.1.0"] = PLUGIN_VERSION
    features: CapabilityFeatures = CapabilityFeatures()
    warnings: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class _Connection:
    base_url: str
    workspace_label: str
    target: Literal["hosted", "self-hosted"]
    headers: dict[str, str]
    timeout: float


def _capability(
    state: CapabilityState,
    *,
    workspace_label: str | None = None,
    target: ConnectionTarget = "unknown",
    warnings: tuple[str, ...] = (),
) -> CapabilityResponse:
    return CapabilityResponse(
        state=state,
        workspace_label=workspace_label,
        target=target,
        warnings=warnings,
    )


def _has_explicit_self_hosted_auth(config: object) -> bool:
    raw = getattr(config, "raw", None)
    host = str(getattr(config, "host", ""))
    if not isinstance(raw, dict):
        return False
    hosts = raw.get("hosts")
    if not isinstance(hosts, dict):
        return False
    host_config = hosts.get(host)
    if not isinstance(host_config, dict) and host.startswith("hermes_"):
        host_config = hosts.get(f"hermes.{host.removeprefix('hermes_')}")
    return isinstance(host_config, dict) and bool(host_config.get("apiKey"))


def resolve_connection() -> _Connection | CapabilityResponse:
    """Resolve the active profile's Honcho connection without creating a client."""

    try:
        from plugins.memory.honcho.client import HonchoClientConfig

        config = HonchoClientConfig.from_global_config()
    except Exception:
        return _capability("missing-configuration")

    try:
        if not bool(getattr(config, "enabled", False)):
            state: CapabilityState = (
                "disabled"
                if bool(getattr(config, "explicitly_configured", False))
                else "missing-configuration"
            )
            return _capability(state)

        workspace_label = str(getattr(config, "workspace_id", "")).strip()
        api_key = getattr(config, "api_key", None)
        configured_base_url = str(getattr(config, "base_url", "") or "").strip()
        environment = str(getattr(config, "environment", "production")).strip().lower()
        if not workspace_label or (not configured_base_url and not api_key):
            return _capability("missing-configuration")
        if not configured_base_url and environment != "production":
            return _capability("missing-configuration")

        target: Literal["hosted", "self-hosted"]
        if configured_base_url:
            parsed = urlparse(configured_base_url)
            try:
                _ = parsed.port
            except ValueError:
                return _capability("missing-configuration")
            if (
                parsed.scheme not in {"http", "https"}
                or parsed.hostname is None
                or parsed.username is not None
                or parsed.password is not None
                or parsed.params
                or parsed.query
                or parsed.fragment
                or (
                    parsed.path not in {"", "/"}
                    and re.fullmatch(r"/v\d+/?", parsed.path) is None
                )
            ):
                return _capability("missing-configuration")
            base_url = f"{parsed.scheme}://{parsed.netloc}"
            target = "self-hosted"
        else:
            base_url = HOSTED_BASE_URL
            target = "hosted"

        raw_timeout = getattr(config, "timeout", None)
        timeout = DEFAULT_TIMEOUT_SECONDS if raw_timeout is None else float(raw_timeout)
        timeout = min(max(timeout, MIN_TIMEOUT_SECONDS), MAX_TIMEOUT_SECONDS)
        send_api_key = bool(api_key) and (
            not configured_base_url or _has_explicit_self_hosted_auth(config)
        )
        headers = {"Authorization": f"Bearer {api_key}"} if send_api_key else {}
    except (AttributeError, TypeError, ValueError, OverflowError):
        return _capability("missing-configuration")

    return _Connection(
        base_url=base_url,
        workspace_label=workspace_label,
        target=target,
        headers=headers,
        timeout=timeout,
    )


router = APIRouter()


@router.get("/capabilities", response_model=CapabilityResponse)
async def capabilities() -> CapabilityResponse:
    """Report whether the configured Honcho connection passes the fixed health probe."""

    connection = resolve_connection()
    if isinstance(connection, CapabilityResponse):
        return connection

    try:
        async with httpx.AsyncClient(
            base_url=connection.base_url,
            headers=connection.headers,
            timeout=connection.timeout,
            follow_redirects=False,
        ) as client:
            response = await client.get("/health")
    except httpx.RequestError:
        return _capability(
            "unreachable",
            workspace_label=connection.workspace_label,
            target=connection.target,
        )

    if response.status_code in {401, 403}:
        return _capability(
            "unauthorized",
            workspace_label=connection.workspace_label,
            target=connection.target,
        )
    if response.status_code != 200:
        return _capability(
            "unreachable",
            workspace_label=connection.workspace_label,
            target=connection.target,
        )

    return _capability(
        "ready",
        workspace_label=connection.workspace_label,
        target=connection.target,
    )
