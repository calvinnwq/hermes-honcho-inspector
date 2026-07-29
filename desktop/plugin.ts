import {
  Button,
  ErrorState,
  Loader,
  PALETTE_AREA,
  ROUTES_AREA,
  SIDEBAR_NAV_AREA,
  StatusDot,
  host,
  useQuery,
  useValue,
  type HermesPlugin,
  type PluginContext
} from "@hermes/plugin-sdk"
import { useEffect, useRef, useState } from "react"
import { jsx, jsxs } from "react/jsx-runtime"

import {
  STATE_GUIDANCE,
  loadOverview,
  queueSummary,
  type OverviewData,
  type OverviewWarning
} from "./overview-model"
import {
  canRequestNextSessionPage,
  loadSessionSummary,
  loadSessions,
  sessionListPath,
  type EvidenceStatus,
  type SessionSummaryData,
  type SessionsData
} from "./session-model"

export const PLUGIN_ID = "honcho-inspector"
export const PLUGIN_VERSION = "0.1.0"
const OVERVIEW_PATH = "/honcho-inspector"
const OVERVIEW_BUDGET_MS = 55_000
const OVERVIEW_TIMEOUT_MS = OVERVIEW_BUDGET_MS + 10_000
const SESSION_VIEW_TIMEOUT_MS = 30_000

const WARNING_COPY: Record<OverviewWarning, string> = {
  "processing-pending": "Pending work is expected while Honcho updates memory.",
  "processing-in-progress": "Honcho is actively processing workspace memory.",
  "unsupported-contract": "The service response does not match the supported Overview contract."
}

function RefreshButton({ disabled, refresh }: { disabled: boolean; refresh: () => void }) {
  return jsx(Button, {
    type: "button",
    variant: "outline",
    size: "sm",
    disabled,
    onClick: refresh,
    children: disabled ? "Refreshing…" : "Refresh"
  })
}

function PageHeader({ data, refreshing, refresh }: { data: OverviewData; refreshing: boolean; refresh: () => void }) {
  const guidance = STATE_GUIDANCE[data.state]

  return jsxs("header", {
    className: "flex flex-wrap items-start justify-between gap-4",
    children: [
      jsxs("div", {
        className: "grid gap-1",
        children: [
          jsx("h1", { className: "text-xl font-semibold tracking-tight", children: "Honcho Inspector" }),
          jsxs("div", {
            className: "flex items-center gap-2 text-sm text-(--ui-text-secondary)",
            children: [
              jsx(StatusDot, { tone: guidance.tone }),
              jsx("span", { children: guidance.title }),
              data.workspace_label
                ? jsx("span", { className: "text-(--ui-text-tertiary)", children: `· ${data.workspace_label}` })
                : null
            ]
          })
        ]
      }),
      jsx(RefreshButton, { disabled: refreshing, refresh })
    ]
  })
}

function StatCard({ label, value }: { label: string; value: number }) {
  return jsxs("div", {
    className: "grid gap-1 rounded-md border border-(--ui-stroke-secondary) p-4",
    children: [
      jsx("div", { className: "text-xs font-medium uppercase tracking-wide text-(--ui-text-tertiary)", children: label }),
      jsx("div", { className: "text-2xl font-semibold tabular-nums", children: value.toLocaleString() })
    ]
  })
}

function WarningList({ warnings }: { warnings: OverviewWarning[] }) {
  if (warnings.length === 0) return null

  return jsx("ul", {
    className: "grid gap-2 rounded-md border border-(--ui-stroke-secondary) p-4 text-sm text-(--ui-text-secondary)",
    children: warnings.map(warning =>
      jsxs("li", {
        className: "flex gap-2",
        children: [
          jsx("span", { "aria-hidden": true, className: "text-(--ui-text-tertiary)", children: "•" }),
          jsx("span", { children: WARNING_COPY[warning] })
        ]
      }, warning)
    )
  })
}

const EVIDENCE_COPY: Record<EvidenceStatus, string> = {
  verified: "Verified source evidence",
  context: "Derived context, not exact source proof",
  unavailable: "Evidence unavailable"
}

function EvidenceLabel({ status }: { status: EvidenceStatus }) {
  return jsx("span", {
    className: "rounded-full border border-(--ui-stroke-secondary) px-2 py-1 text-xs text-(--ui-text-secondary)",
    children: `Evidence: ${EVIDENCE_COPY[status]}`
  })
}

function SessionStatePanel({ state }: { state: SessionsData["state"] }) {
  const guidance = STATE_GUIDANCE[state]
  return jsxs("div", {
    className: "grid gap-2 rounded-md border border-(--ui-stroke-secondary) p-4",
    children: [
      jsx("h3", { className: "font-medium", children: guidance.title }),
      jsx("p", { className: "text-sm text-(--ui-text-secondary)", children: guidance.description })
    ]
  })
}

function SessionSummaryPanel({
  selectedSessionKey,
  query,
  refresh
}: {
  selectedSessionKey: string | null
  query: { data: SessionSummaryData | undefined; isError: boolean; isFetching: boolean }
  refresh: () => void
}) {
  if (selectedSessionKey === null) {
    return jsx("p", {
      className: "text-sm text-(--ui-text-tertiary)",
      children: "Select a recent session to inspect its generated summary."
    })
  }

  if (query.isError) {
    return jsxs("div", {
      className: "grid gap-2 rounded-md border border-(--ui-stroke-secondary) p-4",
      children: [
        jsx("h3", { className: "font-medium", children: "Summary unavailable" }),
        jsx("p", { className: "text-sm text-(--ui-text-secondary)", children: "Honcho Inspector could not load this session summary. Try again." }),
        jsx(RefreshButton, { disabled: query.isFetching, refresh })
      ]
    })
  }

  if (query.data === undefined || query.isFetching) {
    return jsx(Loader, { label: "Loading session summary" })
  }

  if (query.data.state !== "ready") return jsx(SessionStatePanel, { state: query.data.state })
  if (query.data.summary === null) {
    return jsxs("div", {
      className: "grid gap-2 rounded-md border border-(--ui-stroke-secondary) p-4",
      children: [
        jsx("h3", { className: "font-medium", children: "No summary yet" }),
        jsx("p", { className: "text-sm text-(--ui-text-secondary)", children: "Honcho has not produced a summary for this session yet." }),
        jsx(EvidenceLabel, { status: "unavailable" })
      ]
    })
  }

  const summary = query.data.summary
  return jsxs("article", {
    className: "grid gap-3 rounded-md border border-(--ui-stroke-secondary) p-4",
    children: [
      jsxs("div", {
        className: "flex flex-wrap items-center justify-between gap-2",
        children: [
          jsx("h3", { className: "font-medium", children: "Derived summary" }),
          jsx(EvidenceLabel, { status: summary.evidence_status })
        ]
      }),
      jsx("p", {
        className: "text-sm leading-6 whitespace-pre-wrap text-(--ui-text-secondary)",
        children: summary.content
      }),
      jsx("p", {
        className: "text-xs text-(--ui-text-tertiary)",
        children: "This is Honcho-generated context, not a transcript. The API does not prove exact claim-to-message attribution."
      }),
      jsx("p", {
        className: "text-xs text-(--ui-text-tertiary)",
        children: `Generated ${new Date(summary.created_at).toLocaleString()} · ${summary.summary_type} summary${summary.truncated ? " · shortened for display" : ""}`
      })
    ]
  })
}

function SessionSummaryModal({
  selectedSessionKey,
  selectedSessionCreatedAt,
  query,
  refresh,
  close,
  restoreFocus
}: {
  selectedSessionKey: string | null
  selectedSessionCreatedAt: string | undefined
  query: { data: SessionSummaryData | undefined; isError: boolean; isFetching: boolean }
  refresh: () => void
  close: () => void
  restoreFocus: () => void
}) {
  const dialogRef = useRef<HTMLDialogElement | null>(null)

  useEffect(() => {
    const dialog = dialogRef.current
    if (selectedSessionKey !== null && dialog !== null && !dialog.open) {
      dialog.showModal()
    }
  }, [selectedSessionKey])

  if (selectedSessionKey === null) return null

  const closeModal = () => {
    if (dialogRef.current?.open) dialogRef.current.close()
    close()
    restoreFocus()
  }

  return jsxs("dialog", {
    ref: dialogRef,
    role: "dialog",
    "aria-modal": true,
    "aria-labelledby": "honcho-session-summary-title",
    "data-slot": "dialog-content",
    onCancel: (event: { preventDefault(): void }) => {
      event.preventDefault()
      closeModal()
    },
    className: "fixed left-1/2 top-1/2 z-(--z-modal) m-0 grid max-h-[85vh] w-full max-w-2xl -translate-x-1/2 -translate-y-1/2 gap-3 overflow-y-auto rounded-xl border border-(--stroke-nous) bg-(--ui-chat-bubble-background) p-4 text-[length:var(--conversation-text-font-size)] text-foreground shadow-nous duration-200 backdrop:bg-black/22 backdrop:backdrop-blur-[0.125rem]",
    children: [
      jsxs("header", {
        className: "flex items-start justify-between gap-4",
        children: [
          jsxs("div", {
            className: "grid gap-1",
            children: [
              jsx("h2", { id: "honcho-session-summary-title", className: "font-medium", children: "Session summary" }),
              selectedSessionCreatedAt
                ? jsx("p", { className: "text-sm text-(--ui-text-tertiary)", children: new Date(selectedSessionCreatedAt).toLocaleString() })
                : null
            ]
          }),
          jsx(Button, {
            type: "button",
            variant: "outline",
            size: "sm",
            autoFocus: true,
            onClick: closeModal,
            children: "Close"
          })
        ]
      }),
      jsx(SessionSummaryPanel, {
        selectedSessionKey,
        query,
        refresh
      })
    ]
  })
}

function SessionPagination({
  data,
  disabled,
  setPage
}: {
  data: SessionsData
  disabled: boolean
  setPage: (page: number) => void
}) {
  if (data.page === null || data.pages === null || data.pages <= 1) return null

  return jsxs("nav", {
    "aria-label": "Session pages",
    className: "flex flex-wrap items-center justify-between gap-2 pt-2",
    children: [
      jsx(Button, {
        type: "button",
        variant: "outline",
        size: "sm",
        disabled: disabled || data.page <= 1,
        onClick: () => setPage(data.page! - 1),
        children: "Previous page"
      }),
      jsx("span", {
        className: "text-xs text-(--ui-text-tertiary)",
        children: data.mode === "summarized"
          ? `Page ${data.page} of ${data.pages} · ${data.items.length} with summaries on this page`
          : `Page ${data.page} of ${data.pages} · ${data.total?.toLocaleString() ?? ""} sessions`
      }),
      jsx(Button, {
        type: "button",
        variant: "outline",
        size: "sm",
        disabled: disabled || !canRequestNextSessionPage(data),
        onClick: () => setPage(data.page! + 1),
        children: "Next page"
      })
    ]
  })
}

function SessionSummaries({ ctx, profile }: { ctx: PluginContext; profile: string }) {
  const [selectedSessionKey, setSelectedSessionKey] = useState<string | null>(null)
  const [page, setPage] = useState(1)
  const [summarizedOnly, setSummarizedOnly] = useState(true)
  const returnFocusRef = useRef<HTMLButtonElement | null>(null)
  useEffect(() => {
    setPage(1)
    setSelectedSessionKey(null)
  }, [profile])
  useEffect(() => {
    setPage(1)
    setSelectedSessionKey(null)
  }, [summarizedOnly])
  useEffect(() => {
    setSelectedSessionKey(null)
  }, [page])

  const sessionsQuery = useQuery<SessionsData>({
    queryKey: [PLUGIN_ID, "sessions", profile, page, summarizedOnly ? "summarized" : "all"],
    queryFn: () => loadSessions(() =>
      ctx.rest<unknown>(sessionListPath(page, summarizedOnly), { timeoutMs: SESSION_VIEW_TIMEOUT_MS })
    ),
    retry: false
  })
  const summaryQuery = useQuery<SessionSummaryData>({
    queryKey: [PLUGIN_ID, "session-summary", profile, selectedSessionKey],
    queryFn: () => selectedSessionKey === null
      ? Promise.resolve({
          state: "ready",
          summary: null,
          evidence_status: "unavailable",
          observed_at: new Date().toISOString(),
          warnings: []
        } satisfies SessionSummaryData)
      : loadSessionSummary(() =>
          ctx.rest<unknown>(
            `/session-summary?session_id=${encodeURIComponent(selectedSessionKey)}`,
            { timeoutMs: SESSION_VIEW_TIMEOUT_MS }
          )
        ),
    retry: false
  })
  const selectedSessionCreatedAt = sessionsQuery.data?.state === "ready"
    ? sessionsQuery.data.items.find(session => session.session_key === selectedSessionKey)?.created_at
    : undefined

  return jsxs("section", {
    "aria-label": "Recent session summaries",
    className: "grid gap-4 rounded-md border border-(--ui-stroke-secondary) p-4",
    children: [
      jsxs("div", {
        className: "flex flex-wrap items-start justify-between gap-2",
        children: [
          jsxs("div", {
            className: "grid gap-1",
            children: [
              jsx("h2", { className: "text-[0.9375rem] font-semibold tracking-tight text-foreground", children: summarizedOnly ? "Sessions with summaries" : "Recent sessions" }),
              jsx("p", {
                className: "text-sm text-(--ui-text-secondary)",
                children: summarizedOnly
                  ? "Only sessions with a generated summary on the selected page are shown. Empty pages can occur because Honcho exposes summaries per session."
                  : "Inspect one generated summary without exposing raw messages."
              })
              ]
            }),
          jsxs("div", {
            className: "flex flex-wrap items-center gap-2",
            role: "group",
            "aria-label": "Session list mode",
            children: [
                jsx(Button, {
                  type: "button",
                  variant: summarizedOnly ? "secondary" : "outline",
                  size: "sm",
                  onClick: () => setSummarizedOnly(true),
                  children: "Summarised only"
                }),
                jsx(Button, {
                  type: "button",
                  variant: summarizedOnly ? "outline" : "secondary",
                  size: "sm",
                  onClick: () => setSummarizedOnly(false),
                  children: "All sessions"
                }),
                jsx(RefreshButton, { disabled: sessionsQuery.isFetching, refresh: () => void sessionsQuery.refetch() })
              ]
            }),
        ]
      }),
      sessionsQuery.isError
        ? jsxs("div", {
            className: "grid gap-2 text-sm text-(--ui-text-secondary)",
            children: [
              jsx("p", { children: "Honcho Inspector could not load recent sessions. Try again." }),
              jsx(RefreshButton, { disabled: sessionsQuery.isFetching, refresh: () => void sessionsQuery.refetch() })
            ]
          })
        : sessionsQuery.isLoading || sessionsQuery.data === undefined
          ? jsx(Loader, { label: "Loading recent sessions" })
          : sessionsQuery.data.state !== "ready"
            ? jsx(SessionStatePanel, { state: sessionsQuery.data.state })
            : sessionsQuery.data.items.length === 0
              ? jsxs("div", {
                  className: "grid gap-3",
                  children: [
                    jsx("p", {
                      className: "text-sm text-(--ui-text-tertiary)",
                      children: summarizedOnly
                        ? "No sessions with generated summaries were found on this page. Try another page or show all sessions."
                        : "No recent sessions are available."
                    }),
                    jsx(SessionPagination, {
                      data: sessionsQuery.data,
                      disabled: sessionsQuery.isFetching,
                      setPage
                    })
                  ]
                })
              : jsxs("div", {
                  className: "grid gap-2",
                  children: [
                    jsx("div", {
                      className: "grid gap-2",
                      children: sessionsQuery.data.items.map(session =>
                        jsx("button", {
                          type: "button",
                          className: `flex items-center justify-between gap-3 rounded-md border p-3 text-left text-sm transition-colors ${selectedSessionKey === session.session_key ? "border-(--ui-focus) bg-(--ui-bg-secondary)" : "border-(--ui-stroke-secondary)"}`,
                          onClick: (event: { currentTarget: HTMLButtonElement }) => {
                            returnFocusRef.current = event.currentTarget
                            setSelectedSessionKey(session.session_key)
                          },
                          children: [
                            jsxs("span", {
                              className: "grid gap-1",
                              children: [
                                jsx("span", { className: "font-medium", children: new Date(session.created_at).toLocaleString() }),
                                jsx("span", { className: "text-xs text-(--ui-text-tertiary)", children: session.is_active ? "Active session" : "Completed session" })
                              ]
                            }),
                            jsx("span", { className: "text-(--ui-text-tertiary)", "aria-hidden": true, children: "›" })
                          ]
                        }, session.session_key)
                      )
                    }),
                    jsx(SessionPagination, {
                      data: sessionsQuery.data,
                      disabled: sessionsQuery.isFetching,
                      setPage
                    })
                  ]
                }),
      jsx(SessionSummaryModal, {
        selectedSessionKey,
        selectedSessionCreatedAt,
        query: summaryQuery,
        refresh: () => void summaryQuery.refetch(),
        close: () => setSelectedSessionKey(null),
        restoreFocus: () => returnFocusRef.current?.focus()
      })
    ]
  })
}

function ReadyOverview({ data, ctx, profile }: { data: OverviewData; ctx: PluginContext; profile: string }) {
  if (data.queue === null || data.peer_total === null || data.session_total === null || data.conclusion_total === null) {
    return null
  }

  const queue = queueSummary(data.queue)

  return jsxs("div", {
    className: "grid gap-5",
    children: [
      jsx("section", {
        "aria-label": "Workspace totals",
        className: "grid gap-3 sm:grid-cols-3",
        children: [
          jsx(StatCard, { label: "Peers", value: data.peer_total }),
          jsx(StatCard, { label: "Sessions", value: data.session_total }),
          jsx(StatCard, { label: "Conclusions", value: data.conclusion_total })
        ]
      }),
      jsxs("section", {
        "aria-label": "Processing queue",
        className: "grid gap-3 rounded-md border border-(--ui-stroke-secondary) p-4",
        children: [
          jsxs("div", {
            className: "flex flex-wrap items-center justify-between gap-2",
            children: [
              jsx("h2", { className: "font-medium", children: queue.title }),
              jsx("span", {
                className: "text-xs tabular-nums text-(--ui-text-tertiary)",
                children: `${data.queue.completed.toLocaleString()} recently completed`
              })
            ]
          }),
          jsx("p", { className: "text-sm text-(--ui-text-secondary)", children: queue.description })
        ]
      }),
      jsx(WarningList, { warnings: data.warnings }),
      jsx(SessionSummaries, { ctx, profile }, profile),
      jsx("p", {
        className: "text-xs text-(--ui-text-tertiary)",
        children: `Observed ${new Date(data.observed_at).toLocaleString()}`
      })
    ]
  })
}

function ConnectionGuidance({ data }: { data: OverviewData }) {
  const guidance = STATE_GUIDANCE[data.state]

  return jsxs("section", {
    className: "grid gap-3 rounded-md border border-(--ui-stroke-secondary) p-5",
    children: [
      jsxs("div", {
        className: "flex items-center gap-2",
        children: [
          jsx(StatusDot, { tone: guidance.tone }),
          jsx("h2", { className: "font-medium", children: guidance.title })
        ]
      }),
      jsx("p", { className: "max-w-2xl text-sm text-(--ui-text-secondary)", children: guidance.description })
    ]
  })
}

function OverviewPage({ ctx }: { ctx: PluginContext }) {
  const profile = useValue(host.state.profile)
  const query = useQuery<OverviewData>({
    queryKey: [PLUGIN_ID, "overview", profile],
    queryFn: () => loadOverview(() =>
      ctx.rest<unknown>("/overview", { timeoutMs: OVERVIEW_TIMEOUT_MS })
    ),
    retry: false
  })
  const refresh = () => void query.refetch()

  if (query.isError) {
    return jsx("main", {
      className: "grid h-full place-items-center p-6",
      children: jsx(ErrorState, {
        title: "Overview unavailable",
        description: "Honcho Inspector could not load its fixed backend route. Check the plugin backend and try again.",
        children: jsx(RefreshButton, { disabled: query.isFetching, refresh })
      })
    })
  }

  if (query.isLoading || query.data === undefined) {
    return jsx("main", {
      className: "grid h-full place-items-center p-6",
      children: jsx(Loader, { label: "Loading Honcho overview" })
    })
  }

  return jsxs("main", {
    className: "mx-auto grid w-full max-w-4xl gap-6 overflow-auto p-6",
    children: [
      jsx(PageHeader, { data: query.data, refreshing: query.isFetching, refresh }),
      query.data.state === "ready"
        ? jsx(ReadyOverview, { data: query.data, ctx, profile })
        : jsx(ConnectionGuidance, { data: query.data })
    ]
  })
}

const plugin: HermesPlugin = {
  id: PLUGIN_ID,
  name: "Honcho Inspector",
  defaultEnabled: false,
  register(ctx) {
    ctx.registerMany([
      {
        id: "overview-page",
        area: ROUTES_AREA,
        data: { path: OVERVIEW_PATH },
        render: () => jsx(OverviewPage, { ctx })
      },
      {
        id: "overview-nav",
        area: SIDEBAR_NAV_AREA,
        data: { path: OVERVIEW_PATH, label: "Honcho Inspector", codicon: "database" }
      },
      {
        id: "overview-command",
        area: PALETTE_AREA,
        data: {
          id: "honcho-inspector.open",
          label: "Open Honcho Inspector",
          keywords: ["honcho", "memory", "overview"],
          run: () => host.navigate(OVERVIEW_PATH)
        }
      }
    ])
  }
}

export default plugin
