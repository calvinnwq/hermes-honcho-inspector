import { STATE_GUIDANCE, type OverviewState } from "./overview-model"

export type SessionState = OverviewState
export type EvidenceStatus = "verified" | "context" | "unavailable"
export type SessionListMode = "all" | "summarized"

export interface SessionItem {
  session_key: string
  is_active: boolean
  created_at: string
}

export interface SessionsData {
  state: SessionState
  mode: SessionListMode
  items: SessionItem[]
  total: number | null
  page: number | null
  pages: number | null
  observed_at: string
  warnings: string[]
}

export interface SessionSummary {
  content: string
  summary_type: "short" | "long"
  created_at: string
  token_count: number
  evidence_status: "context"
  truncated: boolean
}

export interface SessionSummaryData {
  state: SessionState
  summary: SessionSummary | null
  evidence_status: EvidenceStatus
  observed_at: string
  warnings: string[]
}

const MAX_SESSION_ITEMS = 20
const MAX_SESSION_PAGE = 1_000
const MAX_SESSION_KEY_CHARS = 200
const MAX_SUMMARY_CHARS = 8_000
const STATES = new Set<SessionState>(Object.keys(STATE_GUIDANCE) as SessionState[])
const WARNING = "unsupported-contract"

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value)
}

function isCount(value: unknown): value is number {
  return typeof value === "number" && Number.isSafeInteger(value) && value >= 0
}

function isTimestamp(value: unknown): value is string {
  return typeof value === "string"
    && /(?:Z|[+-]\d{2}:\d{2})$/.test(value)
    && Number.isFinite(Date.parse(value))
}

function isSessionKey(value: unknown): value is string {
  return typeof value === "string"
    && value.length > 0
    && value.length <= MAX_SESSION_KEY_CHARS
    && ![...value].some(character => {
      const code = character.charCodeAt(0)
      return code < 32 || code === 127
    })
}

function normalizeWarnings(value: unknown): string[] | null {
  if (!Array.isArray(value) || !value.every(item => item === WARNING)) return null
  return [...value] as string[]
}

function unsupportedSessions(observedAt: string, mode: SessionListMode = "all"): SessionsData {
  return {
    state: "unsupported-contract",
    mode,
    items: [],
    total: null,
    page: null,
    pages: null,
    observed_at: observedAt,
    warnings: [WARNING]
  }
}

function unsupportedSummary(observedAt: string): SessionSummaryData {
  return {
    state: "unsupported-contract",
    summary: null,
    evidence_status: "unavailable",
    observed_at: observedAt,
    warnings: [WARNING]
  }
}

function normalizeSessionItem(value: unknown): SessionItem | null {
  if (!isRecord(value)) return null
  if (!isSessionKey(value.session_key) || typeof value.is_active !== "boolean" || !isTimestamp(value.created_at)) {
    return null
  }

  return {
    session_key: value.session_key,
    is_active: value.is_active,
    created_at: value.created_at
  }
}

export function normalizeSessions(value: unknown, fallbackObservedAt = new Date().toISOString()): SessionsData {
  if (!isRecord(value) || typeof value.state !== "string" || !STATES.has(value.state as SessionState)) {
    return unsupportedSessions(fallbackObservedAt)
  }

  const state = value.state as SessionState
  if (value.mode !== "all" && value.mode !== "summarized") {
    return unsupportedSessions(fallbackObservedAt)
  }
  const mode = value.mode as SessionListMode
  const warnings = normalizeWarnings(value.warnings)
  if (warnings === null || !isTimestamp(value.observed_at) || !Array.isArray(value.items) || value.items.length > MAX_SESSION_ITEMS) {
    return unsupportedSessions(fallbackObservedAt, mode)
  }

  const items = value.items.map(normalizeSessionItem)
  if (items.some(item => item === null)) return unsupportedSessions(fallbackObservedAt, mode)

  const normalizedItems = items as SessionItem[]
  if (state !== "ready") {
    if (
      normalizedItems.length !== 0
      || value.total !== null
      || value.page !== null
      || value.pages !== null
    ) return unsupportedSessions(fallbackObservedAt, mode)
    return {
      state,
      mode,
      items: [],
      total: null,
      page: null,
      pages: null,
      observed_at: value.observed_at,
      warnings
    }
  }

  if (
    !isCount(value.total)
    || !isCount(value.page)
    || value.page < 1
    || value.page > MAX_SESSION_PAGE
    || !isCount(value.pages)
    || value.pages > MAX_SESSION_PAGE
    || value.page > Math.max(value.pages, 1)
    || normalizedItems.length > value.total
    || (value.total === 0 && normalizedItems.length !== 0)
  ) {
    return unsupportedSessions(fallbackObservedAt, mode)
  }

  return {
    state,
    mode,
    items: normalizedItems,
    total: value.total,
    page: value.page,
    pages: value.pages,
    observed_at: value.observed_at,
    warnings
  }
}

export function sessionListPath(page: number, summarizedOnly = false): string {
  if (!Number.isSafeInteger(page) || page < 1 || page > MAX_SESSION_PAGE) {
    throw new RangeError("session page is outside the supported bound")
  }
  return summarizedOnly ? `/sessions-with-summaries?page=${page}` : `/sessions?page=${page}`
}

function normalizeSessionSummaryItem(value: unknown): SessionSummary | null {
  if (!isRecord(value)) return null
  if (
    typeof value.content !== "string"
    || value.content.length === 0
    || value.content.length > MAX_SUMMARY_CHARS
    || (value.summary_type !== "short" && value.summary_type !== "long")
    || !isTimestamp(value.created_at)
    || !isCount(value.token_count)
    || value.evidence_status !== "context"
    || typeof value.truncated !== "boolean"
  ) {
    return null
  }

  return {
    content: value.content,
    summary_type: value.summary_type,
    created_at: value.created_at,
    token_count: value.token_count,
    evidence_status: "context",
    truncated: value.truncated
  }
}

export function normalizeSessionSummary(
  value: unknown,
  fallbackObservedAt = new Date().toISOString()
): SessionSummaryData {
  if (!isRecord(value) || typeof value.state !== "string" || !STATES.has(value.state as SessionState)) {
    return unsupportedSummary(fallbackObservedAt)
  }

  const state = value.state as SessionState
  const warnings = normalizeWarnings(value.warnings)
  if (warnings === null || !isTimestamp(value.observed_at)) return unsupportedSummary(fallbackObservedAt)

  if (state !== "ready") {
    if (value.summary !== null || value.evidence_status !== "unavailable") return unsupportedSummary(fallbackObservedAt)
    return {
      state,
      summary: null,
      evidence_status: "unavailable",
      observed_at: value.observed_at,
      warnings
    }
  }

  if (value.summary === null) {
    if (value.evidence_status !== "unavailable") return unsupportedSummary(fallbackObservedAt)
    return {
      state,
      summary: null,
      evidence_status: "unavailable",
      observed_at: value.observed_at,
      warnings
    }
  }

  const summary = normalizeSessionSummaryItem(value.summary)
  if (summary === null || value.evidence_status !== "context") return unsupportedSummary(fallbackObservedAt)
  return {
    state,
    summary,
    evidence_status: "context",
    observed_at: value.observed_at,
    warnings
  }
}

export async function loadSessions(request: () => Promise<unknown>): Promise<SessionsData> {
  return normalizeSessions(await request())
}

export async function loadSessionSummary(request: () => Promise<unknown>): Promise<SessionSummaryData> {
  return normalizeSessionSummary(await request())
}
