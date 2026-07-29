"""Read-only Honcho capability reporting for Honcho Inspector."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Annotated, Any, Literal
from urllib.parse import quote, urlparse

import httpx
from fastapi import APIRouter
from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

PLUGIN_VERSION = "0.1.0"
HONCHO_SUPPORTED_CONTRACT = "honcho-v3.0.11"
HOSTED_BASE_URL = "https://api.honcho.dev"
DEFAULT_TIMEOUT_SECONDS = 10.0
MIN_TIMEOUT_SECONDS = 1.0
MAX_TIMEOUT_SECONDS = 30.0
MAX_SAFE_COUNT = 9_007_199_254_740_991

CapabilityState = Literal[
    "ready",
    "disabled",
    "missing-configuration",
    "unreachable",
    "unauthorized",
    "unsupported-contract",
]
ConnectionTarget = Literal["hosted", "self-hosted", "unknown"]
OverviewWarning = Literal[
    "processing-pending",
    "processing-in-progress",
    "identity-config-missing",
    "unsupported-contract",
]
SafeCount = Annotated[int, Field(strict=True, ge=0, le=MAX_SAFE_COUNT)]


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


class OverviewQueue(BaseModel):
    """Safe, aggregate queue counts for the Overview renderer."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    total: SafeCount
    completed: SafeCount
    in_progress: SafeCount
    pending: SafeCount


class OverviewResponse(BaseModel):
    """Public, secret-free workspace summary."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    state: CapabilityState
    workspace_label: str | None = None
    peer_total: SafeCount | None = None
    session_total: SafeCount | None = None
    conclusion_total: SafeCount | None = None
    queue: OverviewQueue | None = None
    observed_at: datetime
    warnings: tuple[OverviewWarning, ...] = ()


class _UpstreamPage(BaseModel):
    model_config = ConfigDict(extra="ignore", frozen=True)

    items: list[Any]
    total: SafeCount
    page: Annotated[int, Field(strict=True, ge=1)]
    size: Annotated[int, Field(strict=True, ge=1, le=100)]
    pages: SafeCount

    @model_validator(mode="after")
    def matches_size_one_request(self) -> _UpstreamPage:
        expected_items = min(self.total, 1)
        if (
            self.page != 1
            or self.size != 1
            or self.pages != self.total
            or len(self.items) != expected_items
        ):
            raise ValueError("pagination envelope does not match the fixed request")
        return self


class _UpstreamQueue(BaseModel):
    model_config = ConfigDict(extra="ignore", frozen=True)

    total_work_units: SafeCount
    completed_work_units: SafeCount
    in_progress_work_units: SafeCount
    pending_work_units: SafeCount

    @model_validator(mode="after")
    def counts_are_consistent(self) -> _UpstreamQueue:
        accounted = (
            self.completed_work_units
            + self.in_progress_work_units
            + self.pending_work_units
        )
        if accounted != self.total_work_units:
            raise ValueError("queue counts do not match the total")
        return self


@dataclass(frozen=True, slots=True)
class _Connection:
    base_url: str
    workspace_label: str
    target: Literal["hosted", "self-hosted"]
    headers: dict[str, str]
    timeout: float
    identity_configured: bool = True


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
    if not host_config and host.startswith("hermes_"):
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
        identity_configured=bool(
            getattr(config, "peer_name", None) and getattr(config, "ai_peer", None)
        ),
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
    except (httpx.RequestError, httpx.InvalidURL):
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


def _overview_state(
    state: CapabilityState,
    *,
    workspace_label: str | None = None,
    warnings: tuple[OverviewWarning, ...] = (),
) -> OverviewResponse:
    return OverviewResponse(
        state=state,
        workspace_label=workspace_label,
        observed_at=datetime.now(timezone.utc),
        warnings=warnings,
    )


def _status_state(status_code: int) -> CapabilityState | None:
    if status_code == 200:
        return None
    if status_code in {401, 403}:
        return "unauthorized"
    if 400 <= status_code < 500:
        return "unsupported-contract"
    return "unreachable"


def _overview_failure(
    state: CapabilityState,
    connection: _Connection,
) -> OverviewResponse:
    warnings: tuple[OverviewWarning, ...] = (
        ("unsupported-contract",) if state == "unsupported-contract" else ()
    )
    return _overview_state(
        state,
        workspace_label=connection.workspace_label,
        warnings=warnings,
    )


@router.get("/overview", response_model=OverviewResponse)
async def overview() -> OverviewResponse:
    """Return fixed workspace aggregates without exposing upstream records."""

    connection = resolve_connection()
    if isinstance(connection, CapabilityResponse):
        return _overview_state(connection.state)

    workspace_path = quote(connection.workspace_label, safe="")
    workspace_prefix = f"/v3/workspaces/{workspace_path}"

    try:
        async with httpx.AsyncClient(
            base_url=connection.base_url,
            headers=connection.headers,
            timeout=connection.timeout,
            follow_redirects=False,
        ) as client:
            health_response = await client.get("/health")
            state = _status_state(health_response.status_code)
            if state is not None:
                return _overview_failure(state, connection)

            queue_response = await client.get(f"{workspace_prefix}/queue/status")
            state = _status_state(queue_response.status_code)
            if state is not None:
                return _overview_failure(state, connection)
            queue = _UpstreamQueue.model_validate(queue_response.json())

            totals: list[int] = []
            for resource in ("peers", "sessions", "conclusions"):
                page_response = await client.post(
                    f"{workspace_prefix}/{resource}/list",
                    params={"page": 1, "size": 1},
                    json={},
                )
                state = _status_state(page_response.status_code)
                if state is not None:
                    return _overview_failure(state, connection)
                totals.append(_UpstreamPage.model_validate(page_response.json()).total)
    except (httpx.RequestError, httpx.InvalidURL):
        return _overview_failure("unreachable", connection)
    except (ValidationError, TypeError, ValueError):
        return _overview_failure("unsupported-contract", connection)

    warnings: list[OverviewWarning] = []
    if queue.pending_work_units > 0:
        warnings.append("processing-pending")
    if queue.in_progress_work_units > 0:
        warnings.append("processing-in-progress")
    if not connection.identity_configured:
        warnings.append("identity-config-missing")

    return OverviewResponse(
        state="ready",
        workspace_label=connection.workspace_label,
        peer_total=totals[0],
        session_total=totals[1],
        conclusion_total=totals[2],
        queue=OverviewQueue(
            total=queue.total_work_units,
            completed=queue.completed_work_units,
            in_progress=queue.in_progress_work_units,
            pending=queue.pending_work_units,
        ),
        observed_at=datetime.now(timezone.utc),
        warnings=tuple(warnings),
    )
