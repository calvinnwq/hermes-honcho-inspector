# Contributing

## Scope

Keep changes within the read-only Honcho inspection boundary.
Do not add mutation, chat, semantic query, generic proxying, direct database access, telemetry, credential management, or package publication.
Open a design discussion before changing plugin identity, compatibility policy, evidence semantics, or the two-component release shape.

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

Use synthetic fixtures only.
Never commit credentials, live memories, source messages, workspace identifiers, private URLs, absolute machine paths, or generated `dist/` files.

## Pull requests

Use a focused feature branch and a conventional commit.
Describe the behavior proved, the read-only boundary, and exact verification output.
Do not add AI attribution or co-author trailers.
