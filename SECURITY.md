# Security Policy

## Supported versions

No public release is supported yet.
Security fixes apply to the current default branch until versioned releases begin.

## Reporting a vulnerability

Use GitHub private vulnerability reporting for this repository.
Do not open a public issue containing credentials, private Honcho data, source messages, workspace identifiers, or exploit details.

Include the affected commit or artifact hash, reproduction steps using synthetic data, impact, and any proposed mitigation.
Do not test against another person's Hermes or Honcho environment.

## Trust boundary

Hermes Desktop plugins are trusted unsandboxed local code.
Honcho Inspector must keep credentials server-side, expose only fixed local read routes, normalize responses, and ship deterministic source-reviewable artifacts.
The Slice 0 scaffold performs no Honcho network access and registers no backend routes.
