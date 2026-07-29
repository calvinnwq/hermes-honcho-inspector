# Slice 2 installation status

No release has been published.
Do not install Slice 2 into a live Hermes profile.

Slice 2 provides a Desktop Overview backed by fixed `GET /capabilities` and `GET /overview` plugin routes.
The backend resolves Honcho configuration from the active Hermes profile and performs only reviewed, server-controlled operations against that resolved target.
Those operations are direct-HTTP `GET /health`, queue status, and size-one read-only list requests for peer, session, and conclusion totals.
The Desktop Overview calls only the plugin-scoped Overview route and cannot choose a host, workspace, HTTP method, upstream path, request body, or filter.
Responses contain normalized connection state, workspace label, aggregate totals, queue counts, safe warnings, and an observation timestamp without credentials, raw connection details, upstream error bodies, or raw memory records.
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
