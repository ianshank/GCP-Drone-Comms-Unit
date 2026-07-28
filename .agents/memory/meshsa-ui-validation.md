---
name: meshsa-ui-validation
description: Decisions, gaps, and conventions from the meshsa.ui validation plan peer review and deliverables package.
---

# meshsa.ui Validation Plan — Durable Decisions

## Deliverables location
All artifacts live in `deliverables/meshsa-ui-validation/`. The README there is the authoritative integration checklist.

## Exception type for validate_bind failures
`netauth.validate_bind` raises `ValueError` (not `RuntimeError`). The original plan text that says "RuntimeError" is a documentation error. Tests must use `pytest.raises(ValueError)`.

**Why:** Confirmed by reading `meshsa/netauth.py` — the implementation raises `ValueError` throughout, matching `detection_ingest.py` which is the reference pattern.

## Test file self-containment rule
Test files dropped into `packages/meshsa/tests/` must not import from `deliverables/*/patches/`. Any helper needed by a test file must be inlined in that file or imported from the `meshsa.*` package.

**Why:** The patches directory is not on `sys.path` and is not installed. Cross-directory imports cause collection failures.

## IPv6 endpoints are unguarded (by design)
`_parse_endpoint_host` returns `None` for IPv6 bracketed notation (e.g. `udpin:[::1]:14550`). This is intentional — pymavlink does not define an IPv6 endpoint format. Unguarded is conservative (permissive) rather than false-positive-closed. Tested explicitly.

**Why:** Bracketed IPv6 requires a separate regex branch and a different test matrix. No known pymavlink deployment uses IPv6 endpoints.

## asyncio_mode = "auto" assumed project-wide
The existing `test_ui_app.py` uses `async def` test functions without `@pytest.mark.asyncio`, implying this setting is already active. New test files add the decorator for explicitness but the conftest documents the project-wide setting as the authoritative source.

## WatchdogSec / heartbeat_s relationship
`WatchdogSec=30` in the systemd unit. Default `watchdog_heartbeat_s=10.0` in `UIConfig`. The heartbeat must arrive within `WatchdogSec` (not `WatchdogSec/2` — sd_notify requires arrival within the full interval, but sending at `WatchdogSec/3` is the safe practice). `MESHSA_UI_WATCHDOG_HEARTBEAT_S` must be added to `UIConfig` and the env file when the G0.1 patch is applied.

## Three false positives in the uploaded review
1. OpenSpec artifact IS verifiable — `openspec/changes/meshsa-operator-ui/proposal.md` exists.
2. Phone viewport criteria ARE pass/fail gates (prose style, not observation-only).
3. 97% coverage is NOT a regression — it was always the floor, never 98%.

## Three missed gaps (not in the uploaded review)
1. Port 8099 shared between `DetectionIngestTransport` (UDP) and `ScoutConfig` (TCP).
2. `MavlinkSourceTransport` has no `validate_bind` guard (unlike `detection_ingest`).
3. No `X-Snapshot-Age` header — operators cannot distinguish frozen snapshot from empty.

## xfail strategy
Use `xfail(strict=True)` on individual test methods for unimplemented features. This:
- Documents the gap without blocking CI.
- Fails loudly if the xfail unexpectedly passes (feature added without updating tests).
- Flips cleanly to xpass when the feature is implemented — no manual cleanup.
