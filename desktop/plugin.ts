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
import { jsx, jsxs } from "react/jsx-runtime"

import {
  STATE_GUIDANCE,
  loadOverview,
  queueSummary,
  type OverviewData,
  type OverviewWarning
} from "./overview-model"

export const PLUGIN_ID = "honcho-inspector"
export const PLUGIN_VERSION = "0.1.0"
const OVERVIEW_PATH = "/honcho-inspector"
const OVERVIEW_TIMEOUT_MS = 65_000

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

function ReadyOverview({ data }: { data: OverviewData }) {
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
        ? jsx(ReadyOverview, { data: query.data })
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
