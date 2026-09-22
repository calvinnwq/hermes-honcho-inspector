export function profilePath(path: string, profile: string): string {
  const normalizedProfile = profile.trim()
  if (normalizedProfile.length === 0) return path

  const separator = path.includes("?") ? "&" : "?"
  return `${path}${separator}profile=${encodeURIComponent(normalizedProfile)}`
}
