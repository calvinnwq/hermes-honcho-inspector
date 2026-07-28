import { createHash } from "node:crypto"
import { chmod, copyFile, lstat, mkdir, readdir, readFile, rm, writeFile } from "node:fs/promises"
import { basename, dirname, join, parse, relative, resolve, sep } from "node:path"
import { build } from "esbuild"

const scriptRoot = resolve(import.meta.dirname, "..")
const sourceRoot = process.argv[3] ? resolve(process.argv[3]) : scriptRoot
const dist = process.argv[2] ? resolve(process.argv[2]) : join(scriptRoot, "dist")
if (basename(dist) !== "dist" || dist === sourceRoot || dist === scriptRoot) {
  throw new Error("output directory must be named dist and remain separate from the source root")
}

function containsPath(parent, candidate) {
  const remainder = relative(parent, candidate)
  return remainder === "" || (remainder !== ".." && !remainder.startsWith(`..${sep}`))
}

if (containsPath(dist, sourceRoot) || containsPath(dist, scriptRoot)) {
  throw new Error("output directory must not contain a source root or builder root")
}

async function rejectSymlinkComponents(target, label) {
  const filesystemRoot = parse(target).root
  const components = relative(filesystemRoot, target).split(sep).filter(Boolean)
  let current = filesystemRoot
  for (const component of components) {
    current = join(current, component)
    try {
      if ((await lstat(current)).isSymbolicLink()) {
        throw new Error(`${label} path components must not be symlinks: ${current}`)
      }
    } catch (error) {
      if (error?.code === "ENOENT") return
      throw error
    }
  }
}

await rejectSymlinkComponents(sourceRoot, "source")
await rejectSymlinkComponents(dist, "output")

const copies = new Map([
  ["plugin.yaml", "plugins/honcho-inspector/plugin.yaml"],
  ["__init__.py", "plugins/honcho-inspector/__init__.py"],
  ["dashboard/manifest.json", "plugins/honcho-inspector/dashboard/manifest.json"],
  ["dashboard/plugin_api.py", "plugins/honcho-inspector/dashboard/plugin_api.py"],
  ["INSTALL.md", "INSTALL.md"],
  ["LICENSE", "LICENSE"],
  ["compatibility.json", "compatibility.json"]
])

for (const source of [...copies.keys(), "desktop/plugin.ts"]) {
  const input = join(sourceRoot, source)
  await rejectSymlinkComponents(dirname(input), "source")
  const status = await lstat(input)
  if (!status.isFile()) throw new Error(`source input must be a regular file: ${source}`)
}

await rm(dist, { recursive: true, force: true })

for (const [source, target] of copies) {
  const destination = join(dist, target)
  await mkdir(dirname(destination), { recursive: true })
  await copyFile(join(sourceRoot, source), destination)
}

const desktopBundle = join(dist, "desktop-plugins/honcho-inspector/plugin.js")
await mkdir(dirname(desktopBundle), { recursive: true })
await build({
  absWorkingDir: sourceRoot,
  entryPoints: ["desktop/plugin.ts"],
  outfile: desktopBundle,
  bundle: true,
  format: "esm",
  platform: "browser",
  target: "es2022",
  charset: "utf8",
  legalComments: "none",
  sourcemap: false,
  treeShaking: true,
  logLevel: "silent"
})

async function normalizeModes(directory) {
  await chmod(directory, 0o755)
  for (const entry of await readdir(directory, { withFileTypes: true })) {
    const path = join(directory, entry.name)
    if (entry.isDirectory()) await normalizeModes(path)
    else if (entry.isFile()) await chmod(path, 0o644)
    else throw new Error(`generated release contains a special filesystem entry: ${path}`)
  }
}

await normalizeModes(dist)

async function filesUnder(directory) {
  const entries = await readdir(directory, { withFileTypes: true })
  const files = []
  for (const entry of entries) {
    const path = join(directory, entry.name)
    if (entry.isDirectory()) files.push(...await filesUnder(path))
    if (entry.isFile() && entry.name !== "SHA256SUMS") files.push(path)
  }
  return files
}

const releaseFiles = (await filesUnder(dist))
  .map(path => ({ path, relative: relative(dist, path).replaceAll("\\", "/") }))
  .sort((a, b) => a.relative < b.relative ? -1 : a.relative > b.relative ? 1 : 0)

const checksums = []
for (const file of releaseFiles) {
  const digest = createHash("sha256").update(await readFile(file.path)).digest("hex")
  checksums.push(`${digest}  ${file.relative}`)
}
const checksumManifest = join(dist, "SHA256SUMS")
await writeFile(checksumManifest, `${checksums.join("\n")}\n`, "utf8")
await chmod(checksumManifest, 0o644)
