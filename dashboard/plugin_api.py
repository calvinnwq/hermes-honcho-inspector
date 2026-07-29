"""Read-only Honcho capability reporting for Honcho Inspector."""

from __future__ import annotations

import asyncio
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Annotated, Any, Literal
from urllib.parse import quote, urlparse

import httpx
from fastapi import APIRouter, Query
from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

PLUGIN_VERSION = "0.1.0"
HONCHO_SUPPORTED_CONTRACT = "honcho-v3.0.11"
HOSTED_BASE_URL = "https://api.honcho.dev"
DEFAULT_TIMEOUT_SECONDS = 10.0
MIN_TIMEOUT_SECONDS = 1.0
MAX_TIMEOUT_SECONDS = 30.0
OVERVIEW_BUDGET_SECONDS = 55.0
SESSION_LIST_SIZE = 20
MAX_SESSION_PAGE = 1_000
SESSION_VIEW_BUDGET_SECONDS = 20.0
MAX_SESSION_ID_CHARS = 200
MAX_UPSTREAM_SUMMARY_CHARS = 100_000
MAX_PUBLIC_SUMMARY_CHARS = 8_000
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
    "unsupported-contract",
]
SafeCount = Annotated[int, Field(strict=True, ge=0, le=MAX_SAFE_COUNT)]
EvidenceStatus = Literal["verified", "context", "unavailable"]


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


class SessionItem(BaseModel):
    """Safe session selector data for the Session Summaries view."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    session_key: Annotated[str, Field(strict=True, min_length=1, max_length=MAX_SESSION_ID_CHARS)]
    is_active: bool
    created_at: datetime


class SessionListResponse(BaseModel):
    """Bounded, secret-free recent session list."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    state: CapabilityState
    mode: Literal["all", "summarized"]
    items: tuple[SessionItem, ...] = ()
    total: SafeCount | None = None
    page: SafeCount | None = None
    pages: SafeCount | None = None
    observed_at: datetime
    warnings: tuple[str, ...] = ()


class SessionSummaryItem(BaseModel):
    """A bounded Honcho summary with explicit evidence semantics."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    content: str
    summary_type: Literal["short", "long"]
    created_at: datetime
    token_count: SafeCount
    evidence_status: Literal["context"] = "context"
    truncated: bool = False


class SessionSummaryResponse(BaseModel):
    """A single session summary without raw messages or source identifiers."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    state: CapabilityState
    summary: SessionSummaryItem | None = None
    evidence_status: EvidenceStatus = "unavailable"
    observed_at: datetime
    warnings: tuple[str, ...] = ()


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


class _UpstreamSession(BaseModel):
    model_config = ConfigDict(extra="ignore", frozen=True)

    id: Annotated[str, Field(strict=True, min_length=1, max_length=MAX_SESSION_ID_CHARS)]
    is_active: bool = Field(strict=True)
    created_at: datetime


class _UpstreamSessionPage(BaseModel):
    model_config = ConfigDict(extra="ignore", frozen=True)

    items: list[_UpstreamSession]
    total: SafeCount
    page: Annotated[int, Field(strict=True, ge=1)]
    size: Annotated[int, Field(strict=True, ge=1, le=100)]
    pages: SafeCount

    @model_validator(mode="after")
    def matches_fixed_recent_request(self) -> _UpstreamSessionPage:
        expected_pages = (
            0 if self.total == 0 else (self.total + SESSION_LIST_SIZE - 1) // SESSION_LIST_SIZE
        )
        page_offset = (self.page - 1) * SESSION_LIST_SIZE
        expected_items = max(0, min(SESSION_LIST_SIZE, self.total - page_offset))
        if (
            self.size != SESSION_LIST_SIZE
            or self.pages != expected_pages
            or self.page > max(self.pages, 1)
            or len(self.items) != expected_items
        ):
            raise ValueError("session pagination envelope does not match the fixed request")
        return self


class _UpstreamSummary(BaseModel):
    model_config = ConfigDict(extra="ignore", frozen=True)

    content: Annotated[str, Field(strict=True, min_length=1, max_length=MAX_UPSTREAM_SUMMARY_CHARS)]
    message_id: Annotated[str, Field(strict=True, min_length=1, max_length=MAX_SESSION_ID_CHARS)]
    summary_type: Literal["short", "long"]
    created_at: datetime
    token_count: SafeCount


class _UpstreamSummaryEnvelope(BaseModel):
    model_config = ConfigDict(extra="ignore", frozen=True)

    id: Annotated[str, Field(strict=True, min_length=1, max_length=MAX_SESSION_ID_CHARS)]
    short_summary: _UpstreamSummary | None = None
    long_summary: _UpstreamSummary | None = None


@dataclass(frozen=True, slots=True)
class _SessionPageFetch:
    page: _UpstreamSessionPage | None = None
    state: CapabilityState | None = None


@dataclass(frozen=True, slots=True)
class _SummaryFetch:
    envelope: _UpstreamSummaryEnvelope | None = None
    state: CapabilityState | None = None


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
        if (
            not workspace_label
            or workspace_label in {".", ".."}
            or (not configured_base_url and not api_key)
        ):
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
    if status_code in {408, 425, 429}:
        return "unreachable"
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
        async with asyncio.timeout(OVERVIEW_BUDGET_SECONDS):
            async with httpx.AsyncClient(
                base_url=connection.base_url,
                headers=connection.headers,
                timeout=connection.timeout,
                follow_redirects=False,
            ) as client:
                health_response, queue_response = await asyncio.gather(
                    client.get("/health"),
                    client.get(f"{workspace_prefix}/queue/status"),
                )
                for initial_response in (health_response, queue_response):
                    state = _status_state(initial_response.status_code)
                    if state is not None:
                        return _overview_failure(state, connection)
                queue = _UpstreamQueue.model_validate(queue_response.json())

                list_requests = []
                for resource in ("peers", "sessions", "conclusions"):
                    list_requests.append(
                        client.post(
                            f"{workspace_prefix}/{resource}/list",
                            params={"page": 1, "size": 1},
                            json={},
                        )
                    )
                page_responses = await asyncio.gather(*list_requests)
                for page_response in page_responses:
                    state = _status_state(page_response.status_code)
                    if state is not None:
                        return _overview_failure(state, connection)
                totals = [
                    _UpstreamPage.model_validate(response.json()).total
                    for response in page_responses
                ]
    except (httpx.RequestError, httpx.InvalidURL, TimeoutError):
        return _overview_failure("unreachable", connection)
    except (ValidationError, TypeError, ValueError):
        return _overview_failure("unsupported-contract", connection)

    warnings: list[OverviewWarning] = []
    if queue.pending_work_units > 0:
        warnings.append("processing-pending")
    if queue.in_progress_work_units > 0:
        warnings.append("processing-in-progress")

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


def _session_list_failure(
    state: CapabilityState,
    *,
    mode: Literal["all", "summarized"],
) -> SessionListResponse:
    warnings = ("unsupported-contract",) if state == "unsupported-contract" else ()
    return SessionListResponse(
        state=state,
        mode=mode,
        observed_at=datetime.now(timezone.utc),
        warnings=warnings,
    )


async def _fetch_session_page(
    client: httpx.AsyncClient,
    workspace_path: str,
    page: int,
) -> _SessionPageFetch:
    response = await client.post(
        f"/v3/workspaces/{workspace_path}/sessions/list",
        params={"reverse": True, "page": page, "size": SESSION_LIST_SIZE},
        json={},
    )
    state = _status_state(response.status_code)
    if state is not None:
        return _SessionPageFetch(state=state)
    upstream_page = _UpstreamSessionPage.model_validate(response.json())
    if upstream_page.page != page:
        raise ValueError("session response page does not match the request")
    return _SessionPageFetch(page=upstream_page)


async def _fetch_session_summary(
    client: httpx.AsyncClient,
    workspace_path: str,
    session_id: str,
) -> _SummaryFetch:
    session_path = quote(session_id, safe="")
    response = await client.get(
        f"/v3/workspaces/{workspace_path}/sessions/{session_path}/summaries"
    )
    if response.status_code == 404:
        return _SummaryFetch()
    state = _status_state(response.status_code)
    if state is not None:
        return _SummaryFetch(state=state)
    envelope = _UpstreamSummaryEnvelope.model_validate(response.json())
    if envelope.id != session_id:
        raise ValueError("summary response does not match the requested session")
    return _SummaryFetch(envelope=envelope)


@router.get("/sessions", response_model=SessionListResponse)
async def sessions(
    page: Annotated[int, Query(ge=1, le=MAX_SESSION_PAGE)] = 1,
) -> SessionListResponse:
    """Return one fixed, bounded page of recent sessions."""

    connection = resolve_connection()
    if isinstance(connection, CapabilityResponse):
        return _session_list_failure(connection.state, mode="all")

    workspace_path = quote(connection.workspace_label, safe="")
    try:
        async with asyncio.timeout(SESSION_VIEW_BUDGET_SECONDS):
            async with httpx.AsyncClient(
                base_url=connection.base_url,
                headers=connection.headers,
                timeout=connection.timeout,
                follow_redirects=False,
            ) as client:
                page_fetch = await _fetch_session_page(client, workspace_path, page)
                if page_fetch.state is not None:
                    return _session_list_failure(page_fetch.state, mode="all")
                upstream_page = page_fetch.page
                if upstream_page is None:
                    raise ValueError("session response did not include a page")
    except (httpx.RequestError, httpx.InvalidURL, TimeoutError):
        return _session_list_failure("unreachable", mode="all")
    except (ValidationError, TypeError, ValueError):
        return _session_list_failure("unsupported-contract", mode="all")

    return SessionListResponse(
        state="ready",
        mode="all",
        items=tuple(
            SessionItem(
                session_key=item.id,
                is_active=item.is_active,
                created_at=item.created_at,
            )
            for item in upstream_page.items
        ),
        total=upstream_page.total,
        page=upstream_page.page,
        pages=upstream_page.pages,
        observed_at=datetime.now(timezone.utc),
    )


@router.get("/sessions-with-summaries", response_model=SessionListResponse)
async def sessions_with_summaries(
    page: Annotated[int, Query(ge=1, le=MAX_SESSION_PAGE)] = 1,
) -> SessionListResponse:
    """Return only summarized sessions from one bounded recent-session page."""

    connection = resolve_connection()
    if isinstance(connection, CapabilityResponse):
        return _session_list_failure(connection.state, mode="summarized")

    workspace_path = quote(connection.workspace_label, safe="")
    try:
        async with asyncio.timeout(SESSION_VIEW_BUDGET_SECONDS):
            async with httpx.AsyncClient(
                base_url=connection.base_url,
                headers=connection.headers,
                timeout=connection.timeout,
                follow_redirects=False,
            ) as client:
                page_fetch = await _fetch_session_page(client, workspace_path, page)
                if page_fetch.state is not None:
                    return _session_list_failure(page_fetch.state, mode="summarized")
                upstream_page = page_fetch.page
                if upstream_page is None:
                    raise ValueError("session response did not include a page")

                summary_fetches = await asyncio.gather(
                    *(
                        _fetch_session_summary(client, workspace_path, item.id)
                        for item in upstream_page.items
                    )
                )
                for fetch in summary_fetches:
                    if fetch.state is not None:
                        return _session_list_failure(fetch.state, mode="summarized")
    except (httpx.RequestError, httpx.InvalidURL, TimeoutError):
        return _session_list_failure("unreachable", mode="summarized")
    except (ValidationError, TypeError, ValueError):
        return _session_list_failure("unsupported-contract", mode="summarized")

    return SessionListResponse(
        state="ready",
        mode="summarized",
        items=tuple(
            SessionItem(
                session_key=item.id,
                is_active=item.is_active,
                created_at=item.created_at,
            )
            for item, summary_fetch in zip(upstream_page.items, summary_fetches)
            if summary_fetch.envelope is not None
            and (
                summary_fetch.envelope.short_summary is not None
                or summary_fetch.envelope.long_summary is not None
            )
        ),
        total=upstream_page.total,
        page=upstream_page.page,
        pages=upstream_page.pages,
        observed_at=datetime.now(timezone.utc),
    )


def _session_summary_response(
    state: CapabilityState,
    summary: SessionSummaryItem | None = None,
) -> SessionSummaryResponse:
    evidence_status: EvidenceStatus = "context" if summary is not None else "unavailable"
    warnings = ("unsupported-contract",) if state == "unsupported-contract" else ()
    return SessionSummaryResponse(
        state=state,
        summary=summary,
        evidence_status=evidence_status,
        observed_at=datetime.now(timezone.utc),
        warnings=warnings,
    )


def _public_summary(summary: _UpstreamSummary) -> SessionSummaryItem:
    content = summary.content[:MAX_PUBLIC_SUMMARY_CHARS]
    return SessionSummaryItem(
        content=content,
        summary_type=summary.summary_type,
        created_at=summary.created_at,
        token_count=summary.token_count,
        truncated=len(summary.content) > MAX_PUBLIC_SUMMARY_CHARS,
    )


@router.get("/session-summary", response_model=SessionSummaryResponse)
async def session_summary(
    session_id: str = Query(min_length=1, max_length=MAX_SESSION_ID_CHARS),
) -> SessionSummaryResponse:
    """Return one bounded derived summary for a validated session selector."""

    if any(ord(character) < 32 or ord(character) == 127 for character in session_id):
        return _session_summary_response("unsupported-contract")

    connection = resolve_connection()
    if isinstance(connection, CapabilityResponse):
        return _session_summary_response(connection.state)

    workspace_path = quote(connection.workspace_label, safe="")
    try:
        async with asyncio.timeout(SESSION_VIEW_BUDGET_SECONDS):
            async with httpx.AsyncClient(
                base_url=connection.base_url,
                headers=connection.headers,
                timeout=connection.timeout,
                follow_redirects=False,
            ) as client:
                summary_fetch = await _fetch_session_summary(client, workspace_path, session_id)
                if summary_fetch.state is not None:
                    return _session_summary_response(summary_fetch.state)
                envelope = summary_fetch.envelope
                if envelope is None:
                    return _session_summary_response("ready")
                summary = envelope.short_summary or envelope.long_summary
    except (httpx.RequestError, httpx.InvalidURL, TimeoutError):
        return _session_summary_response("unreachable")
    except (ValidationError, TypeError, ValueError):
        return _session_summary_response("unsupported-contract")

    return _session_summary_response(
        "ready",
        _public_summary(summary) if summary is not None else None,
    )
