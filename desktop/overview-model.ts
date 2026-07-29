export type OverviewState =
  | "ready"
  | "disabled"
  | "missing-configuration"
  | "unauthorized"
  | "unreachable"
  | "unsupported-contract"

export type OverviewWarning =
  | "processing-pending"
  | "processing-in-progress"
  | "unsupported-contract"

export interface OverviewQueue {
  total: number
  completed: number
  in_progress: number
  pending: number
}

export interface OverviewData {
  state: OverviewState
  workspace_label: string | null
  peer_total: number | null
  session_total: number | null
  conclusion_total: number | null
  queue: OverviewQueue | null
  observed_at: string
  warnings: OverviewWarning[]
}

export interface StateGuidance {
  title: string
  description: string
  tone: "good" | "muted" | "warn" | "bad"
}

export const STATE_GUIDANCE: Record<OverviewState, StateGuidance> = {
  ready: {
    title: "Connected",
    description: "Honcho is reachable and the workspace overview is current.",
    tone: "good"
  },
  disabled: {
    title: "Honcho is disabled",
    description: "Enable Honcho in the active Hermes profile to inspect its workspace.",
    tone: "muted"
  },
  "missing-configuration": {
    title: "Configuration required",
    description: "Configure Honcho for the active Hermes profile, then refresh this page.",
    tone: "warn"
  },
  unauthorized: {
    title: "Authentication required",
    description: "The configured Honcho connection rejected authentication. Review the profile configuration.",
    tone: "bad"
  },
  unreachable: {
    title: "Honcho unavailable",
    description: "The configured Honcho service could not be reached. Check the service and try again.",
    tone: "bad"
  },
  "unsupported-contract": {
    title: "Unsupported Honcho contract",
    description: "The configured service did not return the supported Overview contract. Update or verify Honcho, then retry.",
    tone: "warn"
  }
}

const STATES = new Set<OverviewState>(Object.keys(STATE_GUIDANCE) as OverviewState[])
const WARNINGS = new Set<OverviewWarning>([
  "processing-pending",
  "processing-in-progress",
  "unsupported-contract"
])

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

function normalizeWarnings(value: unknown): OverviewWarning[] | null {
  if (!Array.isArray(value) || !value.every(item => typeof item === "string" && WARNINGS.has(item as OverviewWarning))) {
    return null
  }

  return [...value] as OverviewWarning[]
}

function normalizeQueue(value: unknown): OverviewQueue | null {
  if (!isRecord(value)) return null
  const { total, completed, in_progress: inProgress, pending } = value
  if (![total, completed, inProgress, pending].every(isCount)) return null
  const safeTotal = total as number
  const safeCompleted = completed as number
  const safeInProgress = inProgress as number
  const safePending = pending as number
  if (safeTotal !== safeCompleted + safeInProgress + safePending) return null

  return {
    total: safeTotal,
    completed: safeCompleted,
    in_progress: safeInProgress,
    pending: safePending
  }
}

function unsupportedOverview(observedAt: string): OverviewData {
  return {
    state: "unsupported-contract",
    workspace_label: null,
    peer_total: null,
    session_total: null,
    conclusion_total: null,
    queue: null,
    observed_at: observedAt,
    warnings: ["unsupported-contract"]
  }
}

export function normalizeOverview(value: unknown, fallbackObservedAt = new Date().toISOString()): OverviewData {
  if (!isRecord(value) || typeof value.state !== "string" || !STATES.has(value.state as OverviewState)) {
    return unsupportedOverview(fallbackObservedAt)
  }

  const state = value.state as OverviewState
  const warnings = normalizeWarnings(value.warnings)
  if (
    warnings === null
    || !isTimestamp(value.observed_at)
    || !(value.workspace_label === null || typeof value.workspace_label === "string")
  ) {
    return unsupportedOverview(fallbackObservedAt)
  }

  if (state !== "ready") {
    if (
      value.peer_total !== null
      || value.session_total !== null
      || value.conclusion_total !== null
      || value.queue !== null
    ) {
      return unsupportedOverview(fallbackObservedAt)
    }

    return {
      state,
      workspace_label: value.workspace_label,
      peer_total: null,
      session_total: null,
      conclusion_total: null,
      queue: null,
      observed_at: value.observed_at,
      warnings
    }
  }

  const queue = normalizeQueue(value.queue)
  if (
    typeof value.workspace_label !== "string"
    || value.workspace_label.length === 0
    || !isCount(value.peer_total)
    || !isCount(value.session_total)
    || !isCount(value.conclusion_total)
    || queue === null
  ) {
    return unsupportedOverview(fallbackObservedAt)
  }

  return {
    state,
    workspace_label: value.workspace_label,
    peer_total: value.peer_total,
    session_total: value.session_total,
    conclusion_total: value.conclusion_total,
    queue,
    observed_at: value.observed_at,
    warnings
  }
}

export async function loadOverview(request: () => Promise<unknown>): Promise<OverviewData> {
  return normalizeOverview(await request())
}

function unit(value: number, singular: string, plural: string): string {
  return `${value} ${value === 1 ? singular : plural}`
}

export function queueSummary(queue: OverviewQueue): { title: string; description: string } {
  if (queue.in_progress === 0 && queue.pending === 0) {
    return {
      title: "Queue is idle",
      description: "No work is waiting or currently processing."
    }
  }

  return {
    title: "Processing normally",
    description: `${unit(queue.in_progress, "in progress", "in progress")} and ${unit(queue.pending, "pending", "pending")}. Pending work is expected while Honcho updates memory.`
  }
}
