# Slice 1 installation status

No release has been published.
Do not install Slice 1 into a live Hermes profile.

Slice 1 is a backend-only connection handshake.
It exposes fixed `GET /capabilities`, resolves Honcho configuration from the active Hermes profile, and performs only direct-HTTP `GET /health` against the resolved server-side target.
It returns normalized capability states without credentials, raw connection details, or upstream error bodies.
Its `supported_contract` value declares the project's static support target, while `contract_verified: false` states that the unversioned health response does not verify the Honcho API version.
It does not inspect memory records or provide product UI, and the Desktop entry remains inert.

The generated bundle exists for offline review of the intended paired layout:

```text
desktop-plugins/honcho-inspector/plugin.js
plugins/honcho-inspector/plugin.yaml
plugins/honcho-inspector/__init__.py
plugins/honcho-inspector/dashboard/manifest.json
plugins/honcho-inspector/dashboard/plugin_api.py
```

Hermes currently enables the Desktop and Python backend components separately.
Executable installation instructions will be added only after a later approved slice implements useful behavior and passes clean-profile testing.
