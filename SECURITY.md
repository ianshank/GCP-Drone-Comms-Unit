# Security Policy

## Reporting a vulnerability

Please report suspected security vulnerabilities **privately** rather than via public
issues:

1. Open a private security advisory on GitHub
   (`Security` -> `Advisories` -> `Report a vulnerability`), OR
2. Email the maintainers (replace with a real address before public release).

Include:
- A description of the vulnerability and its impact.
- Reproduction steps or a proof-of-concept.
- Affected versions / commit SHAs.
- Any suggested mitigations.

Maintainers will acknowledge within 5 business days and aim to release a fix or
mitigation within 30 days, depending on severity.

## Threat model notes

- The framework speaks to **untrusted radio peers and TAK servers**. All inbound
  frames pass through Pydantic validation and schema-version gates; malformed or
  incompatible frames are dropped and logged, never executed.
- The Meshtastic transport opens a serial device (or TCP/BLE); the host OS controls
  access (`dialout` group on Linux). Do not run the bridge as root.
- Configuration is loaded from JSON / env vars only; no remote config fetch is
  performed.
- The `meshsa-base.service` unit ships with `NoNewPrivileges`, `ProtectSystem=full`,
  `ProtectHome`, and `PrivateTmp`. Do not weaken these without review.

## Supported versions

The project is at `0.2.0` and is pre-1.0. Only the latest commit on `main` is
currently supported for security fixes.
