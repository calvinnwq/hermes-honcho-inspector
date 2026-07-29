import { execFileSync } from "node:child_process"
import { readFileSync } from "node:fs"
import { resolve } from "node:path"
import { beforeAll, describe, expect, it } from "vitest"

const root = resolve(import.meta.dirname, "../..")
const bundlePath = resolve(root, "dist/desktop-plugins/honcho-inspector/plugin.js")

beforeAll(() => {
  execFileSync("npm", ["run", "build", "--silent"], { cwd: root, stdio: "pipe" })
})

describe("Desktop release bundle", () => {
  it("contains the approved opt-in plugin identity and Overview contributions", () => {
    const bundle = readFileSync(bundlePath, "utf8")

    expect(bundle).toContain('var PLUGIN_ID = "honcho-inspector"')
    expect(bundle).toContain("id: PLUGIN_ID")
    expect(bundle).toContain("defaultEnabled: false")
    expect(bundle).toContain('var OVERVIEW_PATH = "/honcho-inspector"')
    expect(bundle).toContain('label: "Honcho Inspector"')
    expect(bundle).toContain('ctx.rest("/overview")')
    expect(bundle).toContain("ctx.registerMany")
    expect(bundle).toContain("useValue(host.state.profile)")
    expect(bundle).toContain('[PLUGIN_ID, "overview", profile]')
  })

  it("renders request failures before the empty loading fallback", () => {
    const bundle = readFileSync(bundlePath, "utf8")

    expect(bundle.indexOf("if (query.isError)"))
      .toBeLessThan(bundle.indexOf("if (query.isLoading"))
  })

  it("contains only supported runtime import specifiers", () => {
    const bundle = readFileSync(bundlePath, "utf8")
    const imports = [...bundle.matchAll(/(?:from\s*|import\s*\(\s*|import\s+)["']([^"']+)["']/g)].map(match => match[1])
    const allowed = new Set(["@hermes/plugin-sdk", "react", "react/jsx-runtime"])

    expect(imports.every(specifier => allowed.has(specifier))).toBe(true)
    expect(bundle).not.toMatch(/\brequire\s*\(/)
  })

  it("contains no generic host request or private build path", () => {
    const bundle = readFileSync(bundlePath, "utf8")

    expect(bundle).not.toContain("host.request")
    expect(bundle).not.toMatch(/\/Users\/|\/home\//)
    expect(bundle).not.toContain("sourceMappingURL")
  })
})
