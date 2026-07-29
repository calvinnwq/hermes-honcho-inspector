# Slice 3A installation status

No release has been published.
Do not install Slice 3A into a live Hermes profile.

Slice 3A provides a Desktop Overview and a bounded Session Summaries view backed by fixed `GET /capabilities`, `GET /overview`, `GET /sessions`, `GET /sessions-with-summaries`, and `GET /session-summary` plugin routes.
The backend resolves Honcho configuration from the active Hermes profile and performs only reviewed, server-controlled operations against that resolved target.
Those operations are direct-HTTP `GET /health`, queue status, and size-one read-only list requests for peer, session, and conclusion totals.
The [README](README.md) owns the fixed session pagination and page-scoped summary-filter behavior.
Summary inspection performs one fixed read-only request for the selected session and projects only approved derived-summary fields.
The Desktop Overview calls only the plugin-scoped Overview route and cannot choose a host, workspace, HTTP method, upstream path, request body, or filter.
The Session Summaries view cannot choose a host, workspace, HTTP method, upstream path, request body, or arbitrary filter either.
Overview responses contain normalized connection state, workspace label, aggregate totals, queue counts, safe warnings, and an observation timestamp.
Session responses add bounded selectors and approved derived-summary fields.
No response contains credentials, raw connection details, upstream error bodies, raw messages, or summary source identifiers.
The `supported_contract` value declares the project's static support target, while `contract_verified: false` states that the unversioned health response does not verify the Honcho API version.

The generated bundle exists for offline review of the intended paired layout:

```text
desktop-plugins/honcho-inspector/plugin.js
plugins/honcho-inspector/plugin.yaml
plugins/honcho-inspector/__init__.py
plugins/honcho-inspector/dashboard/manifest.json
plugins/honcho-inspector/dashboard/plugin_api.py
```

Hermes currently enables the Desktop and Python backend components separately.
Executable installation instructions require separate approval and clean-profile testing of the paired components.
