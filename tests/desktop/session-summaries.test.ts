import { describe, expect, it } from "vitest"

import {
  loadSessionSummary,
  loadSessions,
  normalizeSessionSummary,
  normalizeSessions,
  sessionListPath
} from "../../desktop/session-model"

const OBSERVED_AT = "2026-07-29T10:00:00.000Z"

const sessionsPayload = {
  state: "ready",
  mode: "all",
  items: [
    {
      session_key: "synthetic-session-2",
      is_active: true,
      created_at: "2026-07-29T09:00:00Z"
    },
    {
      session_key: "synthetic-session-1",
      is_active: false,
      created_at: "2026-07-28T09:00:00Z"
    }
  ],
  total: 2,
  page: 1,
  pages: 1,
  observed_at: OBSERVED_AT,
  warnings: []
}

const summaryPayload = {
  state: "ready",
  summary: {
    content: "Honcho derived context for a synthetic session.",
    summary_type: "short",
    created_at: "2026-07-29T09:05:00Z",
    token_count: 12,
    evidence_status: "context",
    truncated: false,
    message_id: "synthetic-source-message",
    raw_record: "synthetic-private-record"
  },
  evidence_status: "context",
  observed_at: OBSERVED_AT,
  warnings: [],
  api_key: "synthetic-secret"
}

describe("Session Summaries renderer model", () => {
  it("loads a bounded recent-session list through the fixed route", async () => {
    const paths: string[] = []
    const result = await loadSessions(() => {
      paths.push("/sessions")
      return Promise.resolve(sessionsPayload)
    })

    expect(result).toEqual(sessionsPayload)
    expect(paths).toEqual(["/sessions"])
  })

  it("loads the summary-only page through its separate fixed route", async () => {
    const paths: string[] = []
    const result = await loadSessions(() => {
      paths.push(sessionListPath(2, true))
      return Promise.resolve({ ...sessionsPayload, mode: "summarized" })
    })

    expect(result.mode).toBe("summarized")
    expect(paths).toEqual(["/sessions-with-summaries?page=2"])
  })

  it("builds a bounded fixed route for each requested session page", () => {
    expect(sessionListPath(3)).toBe("/sessions?page=3")
    expect(sessionListPath(3, true)).toBe("/sessions-with-summaries?page=3")
    expect(() => sessionListPath(0)).toThrow()
    expect(() => sessionListPath(1_001)).toThrow()
  })

  it("loads one summary through the fixed route with an encoded selector", async () => {
    const paths: string[] = []
    const result = await loadSessionSummary(() => {
      paths.push("/session-summary?session_id=synthetic-session%2F2")
      return Promise.resolve(summaryPayload)
    })

    expect(result.summary?.evidence_status).toBe("context")
    expect(paths).toEqual(["/session-summary?session_id=synthetic-session%2F2"])
    expect(JSON.stringify(result)).not.toContain("synthetic-source-message")
    expect(JSON.stringify(result)).not.toContain("synthetic-private-record")
    expect(JSON.stringify(result)).not.toContain("synthetic-secret")
  })

  it("marks a ready session with no generated summary as unavailable", () => {
    expect(normalizeSessionSummary({
      state: "ready",
      summary: null,
      evidence_status: "unavailable",
      observed_at: OBSERVED_AT,
      warnings: []
    })).toEqual({
      state: "ready",
      summary: null,
      evidence_status: "unavailable",
      observed_at: OBSERVED_AT,
      warnings: []
    })
  })

  it("requires a dedicated summary dialog contract in the Desktop surface", async () => {
    const source = await import("node:fs/promises").then(fs =>
      fs.readFile(new URL("../../desktop/plugin.ts", import.meta.url), "utf8")
    )

    expect(source).toContain("function SessionSummaryModal")
    expect(source).toContain('role: "dialog"')
    expect(source).toContain('"aria-modal": true')
    expect(source).toContain("bg-(--ui-chat-bubble-background)")
    expect(source).toContain("border-(--stroke-nous)")
    expect(source).toContain("shadow-nous")
  })

  it.each([
    { ...sessionsPayload, total: Number.MAX_SAFE_INTEGER + 1 },
    { ...sessionsPayload, items: [{ ...sessionsPayload.items[0], session_key: "\nprivate" }] },
    { ...sessionsPayload, warnings: ["raw-upstream-warning"] },
    { ...sessionsPayload, observed_at: "not-a-date" },
    { ...summaryPayload, evidence_status: "verified" },
    { ...summaryPayload, summary: { ...summaryPayload.summary, token_count: -1 } },
    "synthetic-private-response"
  ])("fails closed when a session response is malformed", payload => {
    const result = typeof payload === "string"
      ? normalizeSessions(payload, OBSERVED_AT)
      : "summary" in payload
        ? normalizeSessionSummary(payload, OBSERVED_AT)
        : normalizeSessions(payload, OBSERVED_AT)

    expect(result.state).toBe("unsupported-contract")
    expect(JSON.stringify(result)).not.toContain("synthetic-private-response")
  })
})
