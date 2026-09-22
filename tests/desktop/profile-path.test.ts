import { describe, expect, it } from "vitest"

import { profilePath } from "../../desktop/profile-path"

describe("profilePath", () => {
  it("adds the active profile without dropping an existing query", () => {
    expect(profilePath("/overview", "kody")).toBe("/overview?profile=kody")
    expect(profilePath("/sessions?page=2", "kody")).toBe("/sessions?page=2&profile=kody")
  })

  it("encodes profile names and leaves an empty profile unscoped", () => {
    expect(profilePath("/overview", "synthetic/profile")).toBe("/overview?profile=synthetic%2Fprofile")
    expect(profilePath("/overview", "")).toBe("/overview")
  })
})
