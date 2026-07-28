# Honcho Inspector for Hermes

Honcho Inspector is a read-only Hermes plugin project for inspecting Honcho health, remembered content, attribution, session context, and evidence gaps.

The repository currently implements **Slice 1**: the reviewed Slice 0 repository and release foundation plus a narrow backend connection handshake.
`GET /capabilities` resolves the active Hermes profile's Honcho configuration server-side, performs only a fixed direct-HTTP `GET /health` probe, and returns a normalized secret-free capability state.
Slice 1 reports `supported_contract` as static project support metadata and `contract_verified: false`; the unversioned health response proves reachability only and does not verify the Honcho API version.
The Desktop entry remains inert.
Slice 1 does not inspect memory records, expose product UI, or provide any renderer-controlled transport behavior.

## Product boundary

The V0.1 promise is inspectable memory with honest evidence status.
Honcho v3.0.11 does not expose exact conclusion-to-message or peer-card-line provenance, so the future UI will label linked messages as context rather than verified sources.

The project is deliberately read-only.
It will not expose mutation, chat, cleanup, workspace administration, credential management, semantic query, direct database access, or a generic Honcho proxy.

## Architecture

The product uses two components with runtime ID `honcho-inspector`:

```text
Hermes Desktop plugin
  -> plugin-scoped ctx.rest calls
  -> Hermes Python backend plugin
  -> fixed read-only Honcho API adapter
```

The Desktop and backend components live in one repository, version, and release because they form one product and one security boundary.
Hermes Desktop plugins are trusted unsandboxed local code, so releases must remain deterministic and source-reviewable.

## Slice 1 verification

Requirements:

- Node.js 22.12 or newer
- Python 3.11 or newer

Setup and verify:

Set `PYTHON` to any Python 3.11+ executable when `python3` is older.

```bash
npm ci
PYTHON="${PYTHON:-python3}"
"$PYTHON" -c 'import sys; sys.exit("Python 3.11+ required") if sys.version_info < (3, 11) else None'
"$PYTHON" -m venv .venv
.venv/bin/python -m pip install -e '.[test]'

npm run build
.venv/bin/python -m pytest tests/backend -q
npm test -- --run
npm run typecheck
.venv/bin/python scripts/verify-release.py dist
.venv/bin/python scripts/verify-readonly.py
npm audit
```

The generated `dist/` directory is ignored by Git.
It contains only the two install trees, installation guide, license, compatibility record, and checksums.

## Compatibility

Development contracts are pinned in [`compatibility.json`](compatibility.json).
The first supported tagged Hermes release is intentionally unset until clean-profile testing proves it.
Honcho support is limited to OpenAPI contract 3.0.11, and hosted credentialed smoke testing has not run.

## Installation

See [`INSTALL.md`](INSTALL.md) for the paired-component layout and current limitations.
No public release or package-registry publication exists yet.

## Contributing and security

See [`CONTRIBUTING.md`](CONTRIBUTING.md) before changing the product boundary and [`SECURITY.md`](SECURITY.md) for private vulnerability reporting.

Licensed under the [MIT License](LICENSE).
