# Slice 0 installation status

No release has been published.
Do not install Slice 0 into a live Hermes profile.
It is an inert repository and release-contract scaffold with no Honcho connection, backend routes, or product UI.

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
