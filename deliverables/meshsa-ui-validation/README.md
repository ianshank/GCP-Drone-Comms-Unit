# meshsa.ui Validation — Deliverables Package

Execution-ready artifacts produced by the peer review and rewrite of the
``meshsa.ui`` validation plan for
[GCP-Drone-Comms-Unit](https://github.com/ianshank/GCP-Drone-Comms-Unit).

Cross-referenced against the repo tree at **2026-07-28**.  All items trace
to NEXTSTEPS open items or AUDIT_M2_AUTH.md follow-up backlog.

---

## What is in this package

```
deliverables/meshsa-ui-validation/
├── README.md                       ← this file
│
├── tests/
│   ├── test_ui_validation_scenarios.py   ← Gate 1: S1–S6 named scenarios
│   ├── test_mavlink_bind_guard.py         ← Gate 0.3: mavlink bind-guard tests
│   └── test_cli_sdnotify.py               ← Gate 0.1: sd_notify heartbeat tests
│
├── patches/
│   ├── mavlink_source_bind_guard.py       ← Gate 0.3: patch for mavlink_source.py
│   └── cli_sdnotify_heartbeat.py          ← Gate 0.1: patch for ui/cli.py
│
├── systemd/
│   ├── meshsa-ui.service                  ← Gate 0.1: systemd unit (Type=notify)
│   └── meshsa-ui.env.example              ← Gate 0.1: env file template
│
└── docs/
    ├── RESIDUAL_RISK_ADDENDUM.md          ← Gate 2: risk acceptance text
    └── PORT_DECONFLICTION_G02.md          ← Gate 0.2: port 8099 deconfliction guide
```

---

## Gates and what each file implements

| Gate | Item | File(s) |
|------|------|---------|
| G0.1 | systemd unit with ``Type=notify`` + ``WatchdogSec=30`` | ``systemd/meshsa-ui.service`` |
| G0.1 | Environment file template | ``systemd/meshsa-ui.env.example`` |
| G0.1 | ``_send_notify`` + ``_watchdog_loop`` patch for ``ui/cli.py`` | ``patches/cli_sdnotify_heartbeat.py`` |
| G0.1 | Unit tests for heartbeat instrumentation | ``tests/test_cli_sdnotify.py`` |
| G0.2 | Port 8099 deconfliction guide | ``docs/PORT_DECONFLICTION_G02.md`` |
| G0.3 | ``validate_bind`` patch for ``mavlink_source.py`` | ``patches/mavlink_source_bind_guard.py`` |
| G0.3 | Tests for mavlink bind guard (xfail until patch lands) | ``tests/test_mavlink_bind_guard.py`` |
| Gate 1 | Named scenario tests S1–S6 (fakes-only) | ``tests/test_ui_validation_scenarios.py`` |
| Gate 2 | Residual risk acceptance text for ``operator-ui.md`` + AUDIT | ``docs/RESIDUAL_RISK_ADDENDUM.md`` |

---

## Integration checklist

Copy each file to the target location in the repo and apply in this order:

### Step 1 — Gate 0 preconditions

```bash
# G0.1: systemd unit + env template
cp systemd/meshsa-ui.service   flightctl/systemd/meshsa-ui.service
cp systemd/meshsa-ui.env.example flightctl/systemd/meshsa-ui.env.example

# G0.1: apply the _send_notify + _watchdog_loop patch to cli.py
# (follow the diff in patches/cli_sdnotify_heartbeat.py)
# Also add:
#   watchdog_heartbeat_s: float = Field(default=10.0, gt=0.0)
#   MESHSA_UI_WATCHDOG_HEARTBEAT_S binding
# to packages/meshsa/src/meshsa/ui/config.py

# G0.1: add sdnotify to the [ui] extra in pyproject.toml:
#   ui = ["aiohttp>=3.9", "sdnotify>=0.3"]

# G0.2: follow docs/PORT_DECONFLICTION_G02.md instructions
# Change ScoutConfig.port default from 8099 → 8101

# G0.3: apply the bind guard to mavlink_source.py
# (follow the diff in patches/mavlink_source_bind_guard.py)
```

### Step 2 — Gate 1: drop scenario tests into the test suite

```bash
cp tests/test_ui_validation_scenarios.py \
   packages/meshsa/tests/test_ui_validation_scenarios.py

cp tests/test_mavlink_bind_guard.py \
   packages/meshsa/tests/test_mavlink_bind_guard.py

cp tests/test_cli_sdnotify.py \
   packages/meshsa/tests/test_cli_sdnotify.py

# Run the full suite — all six S-scenarios must be green; xfail markers flip
# to xpass once the corresponding patches are applied.
cd packages/meshsa && pytest tests/ -v --cov=meshsa --cov-fail-under=97
```

### Step 3 — Gate 2: insert risk documentation

Follow ``docs/RESIDUAL_RISK_ADDENDUM.md`` for the exact text to add to:
- ``docs/specs/operator-ui.md`` (new §6.1)
- ``docs/AUDIT_M2_AUTH.md`` (surface #17 row)
- ``CHANGELOG.md``

### Step 4 — Gate 3: field validation

Run F1–F4 on the target edge hardware with the G0.1 systemd unit active.
Use the pass/fail criteria in the validation plan and the
``assert_logring_whitelist`` helper in ``test_ui_validation_scenarios.py``
for the log-ring soak scan (F3).

---

## Scenario index

| ID | Name | Location |
|----|------|----------|
| S1 | Radio-silence TTL eviction — well-formed empty GeoJSON | ``test_ui_validation_scenarios.py::test_s1_*`` |
| S2 | Multi-source composite-key concurrency — no collisions | ``test_ui_validation_scenarios.py::test_s2_*`` |
| S3 | Cap eviction ordering under backpressure | ``test_ui_validation_scenarios.py::test_s3_*`` |
| S4 | Kill-switch / freeze — stable last-known state | ``test_ui_validation_scenarios.py::test_s4_*`` |
| S5 | Cache-Control: no-store on all token-bearing responses | ``test_ui_validation_scenarios.py::test_s5_*`` |
| S6 | Stale-token rejection after rotation | ``test_ui_validation_scenarios.py::test_s6_*`` |

S4 includes one ``xfail`` for the currently-absent ``X-Snapshot-Age`` header.
S5 will expose gaps in routes that do not yet send ``Cache-Control: no-store``.
S6 is green against the current implementation (token is construction-time).

---

## Design decisions

**No hardcoded values.**  Every operational parameter — TTL, cap, port,
watchdog interval, token, log-ring size — flows through ``UIConfig`` with an
explicit default and a ``MESHSA_UI_*`` env binding.  Tests use only injected
``FakeClock`` and ``UIConfig`` constructor arguments.

**Fakes only in CI.**  No hardware, no live sockets, no real radios in any
of the Gate 1 tests.  The ``aiohttp.test_utils.TestClient`` / ``TestServer``
pair is the only in-process server.  Scenario S1c/S4c/S5/S6 use the
``TestClient`` against the real ``build_ui_app`` factory.

**xfail as gap tracker.**  ``xfail(strict=True)`` on S4d (``X-Snapshot-Age``)
and on the mavlink/sd_notify tests before their patches land means the CI run
fails loudly if the xfail flips to an unexpected pass (someone implemented the
feature without updating the test) or if the test is accidentally removed.

**Backward-compatible patches.**  The mavlink bind-guard patch adds ``token``
as a keyword-only arg extracted from ``**_options``; no existing config JSON or
test that does not pass ``token`` breaks.  The sd_notify patch adds
``watchdog_heartbeat_s`` to ``UIConfig`` with a safe default (10 s).

**Structlog throughout.**  ``_send_notify`` logs via ``structlog`` at
``debug`` (when sdnotify is absent) and ``warning`` (when a notify call fails),
consistent with the repo-wide no-``print`` / no-``console.log`` discipline.
