import { describe, expect, it } from "vitest"

import {
  STATE_GUIDANCE,
  loadOverview,
  normalizeOverview,
  queueSummary,
  type OverviewState
} from "../../desktop/overview-model"

const OBSERVED_AT = "2026-07-29T10:00:00.000Z"

const readyPayload = {
  state: "ready",
  workspace_label: "synthetic-workspace",
  peer_total: 12,
  session_total: 7,
  conclusion_total: 23,
  queue: {
    total: 8,
    completed: 5,
    in_progress: 1,
    pending: 2
  },
  observed_at: OBSERVED_AT,
  warnings: ["processing-pending", "processing-in-progress"]
}

describe("Overview renderer model", () => {
  it("loads and refreshes only through the fixed plugin-scoped route", async () => {
    const paths: string[] = []
    const rest = async (path: string): Promise<unknown> => {
      paths.push(path)
      return { ...readyPayload, raw_records: ["synthetic-private-record"] }
    }
    const request = () => rest("/overview")

    expect(await loadOverview(request)).toEqual(readyPayload)
    expect(await loadOverview(request)).toEqual(readyPayload)
    expect(paths).toEqual(["/overview", "/overview"])
  })

  it("projects only approved aggregate fields", () => {
    const result = normalizeOverview({
      ...readyPayload,
      raw_records: [{ content: "synthetic-private-record" }],
      api_key: "synthetic-secret"
    })

    expect(result).toEqual(readyPayload)
    expect(JSON.stringify(result)).not.toContain("synthetic-private-record")
    expect(JSON.stringify(result)).not.toContain("synthetic-secret")
  })

  it.each([
    { ...readyPayload, peer_total: "12" },
    { ...readyPayload, peer_total: Number.MAX_SAFE_INTEGER + 1 },
    { ...readyPayload, workspace_label: null },
    { ...readyPayload, queue: { ...readyPayload.queue, pending: -1 } },
    { ...readyPayload, queue: { ...readyPayload.queue, total: 7 } },
    { ...readyPayload, warnings: ["raw-upstream-warning"] },
    { ...readyPayload, observed_at: "2026-07-29T10:00:00" },
    { ...readyPayload, observed_at: "not-a-date" },
    "synthetic-private-response"
  ])("fails closed when the response is malformed", payload => {
    expect(normalizeOverview(payload, OBSERVED_AT)).toEqual({
      state: "unsupported-contract",
      workspace_label: null,
      peer_total: null,
      session_total: null,
      conclusion_total: null,
      queue: null,
      observed_at: OBSERVED_AT,
      warnings: ["unsupported-contract"]
    })
  })

  it("provides distinct safe guidance for every connection state", () => {
    const states: OverviewState[] = [
      "ready",
      "disabled",
      "missing-configuration",
      "unauthorized",
      "unreachable",
      "unsupported-contract"
    ]
    const titles = states.map(state => STATE_GUIDANCE[state].title)
    const descriptions = states.map(state => STATE_GUIDANCE[state].description)

    expect(new Set(titles).size).toBe(states.length)
    expect(new Set(descriptions).size).toBe(states.length)
    expect(descriptions.join(" ")).not.toMatch(/api[_ -]?key|bearer|https?:\/\//i)
  })

  it("describes queued work as normal processing activity", () => {
    expect(queueSummary(readyPayload.queue)).toEqual({
      title: "Processing normally",
      description: "1 in progress and 2 pending. Pending work is expected while Honcho updates memory."
    })
    expect(queueSummary({ total: 5, completed: 5, in_progress: 0, pending: 0 })).toEqual({
      title: "Queue is idle",
      description: "No work is waiting or currently processing."
    })
  })
})
