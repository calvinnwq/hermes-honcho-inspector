# Agent Instructions

## Outcome

Build a public read-only Honcho Inspector for Hermes with honest evidence labels and no mutation authority.

## Boundaries

- Keep runtime identity `honcho-inspector` and repository/package identity `hermes-honcho-inspector`.
- Keep Desktop and backend components on one version.
- Keep credentials and raw connection details out of renderer code, responses, logs, fixtures, and artifacts.
- Use only fixed backend routes and fixed reviewed Honcho operations.
- Do not use a generic proxy, high-level Honcho SDK client, direct database access, mutation, chat, semantic query, telemetry, or package publication.
- Treat Desktop plugins as trusted unsandboxed local code.
- Use synthetic fixtures only.
- Do not infer exact source provenance when the public API does not supply it.

## Setup

Set `PYTHON` to any Python 3.11+ executable when `python3` is older.

```bash
npm ci
PYTHON="${PYTHON:-python3}"
"$PYTHON" -c 'import sys; sys.exit("Python 3.11+ required") if sys.version_info < (3, 11) else None'
"$PYTHON" -m venv .venv
.venv/bin/python -m pip install -e '.[test]'
```

## Verification

```bash
npm run build
.venv/bin/python -m pytest tests/backend -q
npm test -- --run
npm run typecheck
.venv/bin/python scripts/verify-release.py dist
.venv/bin/python scripts/verify-readonly.py
npm audit
git diff --check
```

## Git and release

Use feature branches and conventional commits after the initial repository scaffold.
Do not commit `dist/`, publish packages or releases, change compatibility claims, or add external side effects without approval.
