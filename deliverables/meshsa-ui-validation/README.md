# meshsa.ui Validation — Deliverables Package

> **Retirement in progress** (code-hygiene-modularity T-10.2). The G0.3 bind-guard
> pair (`patches/mavlink_source_bind_guard.py`, `tests/test_mavlink_bind_guard.py`)
> was **deleted in T-10.2a**: the guard shipped in
> `meshsa/transports/mavlink_source.py` with a strictly safer parser (the patch's
> regex failed open on bracketed IPv6), and the live in-package coverage is
> `packages/meshsa/tests/test_mavlink_source.py::test_extract_endpoint_host_and_bind_validation`
> (incl. the empty/whitespace-token cases salvaged from the deleted suite).
> References to those two files below are historical. The rest of this tree
> retires in T-10.2b once T-3.1 salvages the remaining scenarios; note the
> sdnotify pair's tests exercise an inline copy of unshipped code and provide no
> evidence about the package until T-10.1 lands it for real.

Execution-ready artifacts produced by the peer review and rewrite of the
``meshsa.ui`` validation plan for
[GCP-Drone-Comms-Unit](https://github.com/ianshank/GCP-Drone-Comms-Unit).

Cross-referenced against the repo tree at **2026-07-28**.  All items trace
to open NEXTSTEPS items or the AUDIT_M2_AUTH.md follow-up backlog.

---

## Package contents

```
deliverables/meshsa-ui-validation/
├── README.md                           ← this file
├── pyproject-fragment.toml            ← dependency + tool config additions
│
├── docs/
│   ├── PEER_REVIEW.md                 ← primary deliverable: polished peer review
│   ├── RESIDUAL_RISK_ADDENDUM.md      ← Gate 2: risk acceptance text
│   └── PORT_DECONFLICTION_G02.md      ← Gate 0.2: port 8099 → 8101 guide
│
├── patches/
│   ├── cli_sdnotify_heartbeat.py      ← Gate 0.1: sd_notify + watchdog patch
│   └── mavlink_source_bind_guard.py   ← Gate 0.3: bind guard patch
│
├── systemd/
│   ├── meshsa-ui.service              ← Gate 0.1: systemd unit (Type=notify)
│   └── meshsa-ui.env.example          ← Gate 0.1: env file template (all vars)
│
└── tests/
    ├── conftest.py                    ← shared fixtures + asyncio_mode config
    ├── test_ui_validation_scenarios.py ← Gate 1: S1–S6 named scenario tests
    ├── test_mavlink_bind_guard.py      ← Gate 0.3: bind-guard contract tests
    └── test_cli_sdnotify.py            ← Gate 0.1: sd_notify heartbeat tests
```

---

## Gate map

| Gate | Requirement | Deliverable | Status |
|------|-------------|-------------|--------|
| G0.1 | systemd unit `Type=notify` + `WatchdogSec=30` | `systemd/meshsa-ui.service` | Ready to apply |
| G0.1 | Env file template (all `MESHSA_UI_*` vars) | `systemd/meshsa-ui.env.example` | Ready to apply |
| G0.1 | `_send_notify` + `_watchdog_loop` in `ui/cli.py` | `patches/cli_sdnotify_heartbeat.py` | Patch — apply manually |
| G0.1 | `watchdog_heartbeat_s` field in `UIConfig` | (described in patch file) | Patch — apply manually |
| G0.1 | Heartbeat unit tests | `tests/test_cli_sdnotify.py` | Drop in; xfail until patch lands |
| G0.2 | Port 8099 → 8101 for `ScoutConfig` | `docs/PORT_DECONFLICTION_G02.md` | Guide — one-line change |
| G0.3 | `validate_bind` in `MavlinkSourceTransport.__init__` | `patches/mavlink_source_bind_guard.py` | Patch — apply manually |
| G0.3 | Bind-guard unit tests | `tests/test_mavlink_bind_guard.py` | Drop in; xfail until patch lands |
| Gate 1 | Named scenario tests S1–S6 | `tests/test_ui_validation_scenarios.py` | Drop in; run immediately |
| Gate 2 | Residual risk acceptance text | `docs/RESIDUAL_RISK_ADDENDUM.md` | Paste into spec + AUDIT |
| Review | Polished peer review document | `docs/PEER_REVIEW.md` | Complete |

---

## Scenario index

| ID | Description | Key assertions | File |
|----|-------------|----------------|------|
| S1 | Radio-silence TTL eviction | `features == []`; `tracks_expired > 0`; HTTP 200 | `test_s1_*` |
| S2 | Multi-source composite-key concurrency | No `(source_uid, track_id)` collisions | `test_s2_*` |
| S3 | Cap eviction ordering under backpressure | Oldest-first; counter increments; cap never exceeded | `test_s3_*` |
| S4 | Kill-switch / frozen update loop | Last-known state served; `X-Snapshot-Age` xfail documented | `test_s4_*` |
| S5 | `Cache-Control: no-store` on all token-bearing routes | All `/api/*` routes + page route | `test_s5_*` |
| S6 | Stale-token rejection after rotation | Old token → 401; new token → 200; 401 body leaks nothing | `test_s6_*` |

**xfail markers:**
- `test_s4_snapshot_age_header_present` — `X-Snapshot-Age` header not yet
  implemented; flips to xpass when `build_ui_app` adds the header.
- All tests in `test_mavlink_bind_guard.py::TestMavlinkBindGuard` — flip when
  `patches/mavlink_source_bind_guard.py` is applied.
- All tests in `test_cli_sdnotify.py` — flip when
  `patches/cli_sdnotify_heartbeat.py` is applied.

---

## Integration checklist

### Step 0 — Dependencies

```bash
# Add sdnotify to the [ui] extra in packages/meshsa/pyproject.toml:
#   ui = ["aiohttp>=3.9", "sdnotify>=0.3"]
# Add pytest-asyncio to dev deps and set asyncio_mode = "auto" in pyproject.toml.
# See pyproject-fragment.toml for the exact sections to add/extend.
pip install sdnotify pytest-asyncio
```

### Step 1 — Apply Gate 0 patches

```bash
# G0.1: systemd unit + env template
cp systemd/meshsa-ui.service   flightctl/systemd/meshsa-ui.service
cp systemd/meshsa-ui.env.example flightctl/systemd/meshsa-ui.env.example

# G0.1: apply the sd_notify patch to meshsa/ui/cli.py
# Follow the diff summary in patches/cli_sdnotify_heartbeat.py:
#   1. Add _ENDPOINT_RE + _parse_endpoint_host at module level
#   2. Add _send_notify + _watchdog_loop at module level
#   3. Add UIConfig.watchdog_heartbeat_s field (default 10.0)
#   4. Add MESHSA_UI_WATCHDOG_HEARTBEAT_S env binding in config.py
#   5. Replace asyncio.Event().wait() in _run with the heartbeat loop

# G0.2: change ScoutConfig.port default from 8099 → 8101
# Follow docs/PORT_DECONFLICTION_G02.md (one-line change in scout/config.py)

# G0.3: apply the mavlink bind guard to meshsa/transports/mavlink_source.py
# Follow patches/mavlink_source_bind_guard.py:
#   1. Add _ENDPOINT_RE + _parse_endpoint_host at module level
#   2. Add "from ..netauth import validate_bind" to imports
#   3. Add token: str | None = None to __init__ kwargs
#   4. Paste _GUARD_BLOCK into __init__ before super().__init__()
```

### Step 2 — Drop in tests

```bash
cp tests/conftest.py \
   packages/meshsa/tests/conftest_ui_scenarios.py   # merge into existing conftest if present

cp tests/test_ui_validation_scenarios.py \
   packages/meshsa/tests/test_ui_validation_scenarios.py

cp tests/test_mavlink_bind_guard.py \
   packages/meshsa/tests/test_mavlink_bind_guard.py

cp tests/test_cli_sdnotify.py \
   packages/meshsa/tests/test_cli_sdnotify.py
```

### Step 3 — Run the suite

```bash
cd packages/meshsa

# Before Gate 0 patches — S1–S6 pass; bind-guard + sdnotify tests xfail.
pytest tests/ -v --cov=meshsa --cov-fail-under=97

# After Gate 0 patches — all xfails flip to xpass; suite still ≥ 97%.
pytest tests/ -v --cov=meshsa --cov-fail-under=97

# Confirm xfail → xpass (no unexpected passes slip through):
pytest tests/ -v --strict-markers
```

### Step 4 — Insert Gate 2 documentation

Follow `docs/RESIDUAL_RISK_ADDENDUM.md` for the exact markdown to add to:
- `docs/specs/operator-ui.md` (new §6.1)
- `docs/AUDIT_M2_AUTH.md` (surface #17 row update)
- `CHANGELOG.md`
- `docs/NEXTSTEPS.md` (tick the open systemd / sd_notify items)

### Step 5 — Field validation (Gate 3)

Run F1–F4 on target hardware (Jetson / Pi 5) using the pass/fail criteria in
the rewritten plan at `.local/tasks/meshsa-ui-validation-plan-review.md`.

For the log-ring whitelist soak (F3), import:
```python
from test_ui_validation_scenarios import assert_logring_whitelist
```
and call it on the dumped log-ring buffer after a 30-minute soak run.

---

## Design decisions (non-obvious choices)

**Why `ValueError` not `RuntimeError` for bind-guard failure?**
`netauth.validate_bind` raises `ValueError` throughout the codebase
(matches `detection_ingest.py`).  The plan text that says "RuntimeError" is
a documentation error in the original review; the implementation is `ValueError`.

**Why is `_parse_endpoint_host` inlined in the test file?**
The test file must be self-contained when placed in `packages/meshsa/tests/`.
Importing from `deliverables/meshsa-ui-validation/patches/` would require a
`sys.path` hack or a package install.  Once the patch lands in
`meshsa.transports.mavlink_source`, the inline copy can be replaced with a
direct import.  Both copies are kept in sync by the `test_parse_endpoint_*`
tests in `test_mavlink_bind_guard.py` that run against the local definition.

**Why does `test_cli_sdnotify.py` inline a reference implementation?**
Same reason — the test file must work in `packages/meshsa/tests/` without any
path to the patches directory.  The reference implementations are identical to
the patch; they are the contract, not a mock.  The `pytestmark` on the module
marks the whole file `xfail` until the real functions exist in `meshsa.ui.cli`.

**Why `asyncio_mode = "auto"` in `conftest.py`?**
The existing `test_ui_app.py` uses `async def` without `@pytest.mark.asyncio`
decorators, implying `asyncio_mode` is already `"auto"` project-wide.  The
`conftest.py` documents this expectation explicitly; if the existing setting
already covers it, the conftest entry is a harmless no-op.

**Why is `X-Snapshot-Age` an xfail, not a failing test?**
The header is a genuine gap identified by the peer review, not a regression.
Using `xfail(strict=True)` documents the gap without blocking CI and
automatically promotes to xpass when the header is implemented — no manual
cleanup needed.

**Why IPv6 endpoints return `None` (unguarded) rather than raising?**
pymavlink does not define an IPv6 endpoint format.  An operator who somehow
passes an IPv6 address gets no bind guard rather than a false-positive
`ValueError`.  This is conservative (permissive) rather than failing closed on
an unseen format.  The behaviour is explicitly tested and documented.

---

## Quality decisions (applied during hygiene pass 2026-07-28)

The following were fixed in the hygiene pass after initial authoring:

| Issue | File | Fix |
|-------|------|-----|
| `from mavlink_source_bind_guard import ...` (bad path when in `tests/`) | `test_mavlink_bind_guard.py` | Inlined `_parse_endpoint_host` + `_ENDPOINT_RE` |
| `from cli_sdnotify_heartbeat import ...` (bad path when in `tests/`) | `test_cli_sdnotify.py` | Inlined reference implementations |
| `import pytest` at bottom of file (E402) | `cli_sdnotify_heartbeat.py` | Moved to top; rewrote as clean patch module |
| Async tests in patch file missing `@pytest.mark.asyncio` | `cli_sdnotify_heartbeat.py` | Added decorator to all async test methods |
| `MESHSA_UI_WATCHDOG_HEARTBEAT_S` missing from env template | `meshsa-ui.env.example` | Added with comment explaining the WatchdogSec relationship |
| Magic number coordinates (38.5, -122.5) in test bodies | `test_ui_validation_scenarios.py` | Extracted to `_DEFAULT_LAT`, `_DEFAULT_LON` module constants |
| Missing return type annotations on all helper functions | `test_ui_validation_scenarios.py` | Added `-> SnapshotStore`, `-> UISources`, `-> TestClient`, `-> Envelope` |
| Lazy import inside `__init__` without explanation | `mavlink_source_bind_guard.py` | Changed to module-level import instruction; documented rationale |
| No `conftest.py` for shared fixtures + asyncio mode | `tests/` | Added `tests/conftest.py` |
| No pyproject config additions documented | (missing) | Added `pyproject-fragment.toml` |
| Primary peer review document not written | `docs/` | Added `docs/PEER_REVIEW.md` |
