# Code Quality & Tech-Debt Plan — reflection pass

> **Status: WORKING PLAN (changeable).** A whole-team reflection taken *before* the next
> feature step: what the tree actually looks like today, measured, and the sequenced work to
> optimize it, reduce debt, harden it, shrink the remaining god files, keep CI/CD green, sweep
> hardcoded values, remove dead/redundant code, and organize the repository the way an
> enterprise reviewer expects — without lowering a single coverage floor.
>
> It does **not** amend [CHARTER.md](CHARTER.md) or [ROADMAP.md](ROADMAP.md), does not open
> M3+, and does not touch `c_gate_met`. Where it finds a scope or safety question it flags it
> for a maintainer decision (CHARTER §6) in §7. It re-prioritizes, and adds to, the open half
> of the `code-hygiene-modularity` bundle
> (`openspec/changes/code-hygiene-modularity/tasks.md`, **28 done / 43 open** at the time of
> writing) rather than replacing it: every item below that overlaps a `T-n.n` task cites it.
>
> Reading order stays CHARTER → ROADMAP → nearest `AGENTS.md` → NEXTSTEPS → IMPLEMENTATION_PLAN
> → this plan → the relevant spec.

Generated: 2026-10-25. Every number in §1 was re-derived from the tree at `ce9afc7` (main) on
that date; treat them as a snapshot and re-measure with the commands in Appendix A before
trusting them on a later read — [IMPLEMENTATION_PLAN.md](IMPLEMENTATION_PLAN.md) has drifted
between reconciliation passes twice, and this file will too.

---

## 0. The one-paragraph verdict

The repository is in **good** shape by the numbers — every gate is green on `main`, both
packages sit above 99 % line+branch coverage against 97/96 % floors, mypy runs `--strict`, and
the governance checkers are themselves tested. The debt is not "broken code"; it is
**(a)** a CI/CD process that produces permanently-red dependency PRs by design,
**(b)** a TypeScript workspace with a full local gate and **no CI job at all**,
**(c)** a handful of functions whose complexity (up to McCabe 31) and constructor arity (up to
23 parameters) are the real god-file residue after the T-4.1/T-4.2 split,
**(d)** a `defaults.py` single-source-of-truth that exists but is only partly adopted,
**(e)** a 37-file `docs/` tree where historical peer reviews sit beside the stable plan, and
**(f)** a stale version/changelog story (`0.3.0` in code since June, `0.1.0` the only cut
release). None of it is risky to fix; most of it is a few focused PRs each.

---

## 1. Measured baseline (2026-10-25)

### 1.1 Gates

| Gate | Result | Notes |
| ---- | ------ | ----- |
| `ruff check` (all five Python roots) | clean | |
| `ruff format --check` | clean, 308 files | |
| `mypy src` meshsa (`--strict`) | clean, 106 files | |
| `mypy flightctl/ tools/`, `mypy deliverables/`, jetson `mypy src` | **not runnable locally on Python 3.13** — see §1.5 trap | CI (3.10–3.12) is green |
| meshsa `pytest -m "not slow"` | 1117 passed, 6 skipped, 1 deselected | **99.30 %** line+branch, floor 97 |
| jetson `pytest` | 224 passed | **99.35 %**, floor 96 |
| tools/hooks `pytest --cov=tools` | 280 passed | 96 % measured, **not gated** |
| 7 governance checkers (`bind_guard` … `validate_agents_docs`) | all exit 0 | |
| TS `pnpm -r run typecheck` / `lint` / `test` | clean / clean / 27 passed | lint covers **only** `api-server`; `mockup-sandbox` has no `lint` or `test` script |
| CI on `main` (`ce9afc7`) | **green**, nightly green 10 days running | |

### 1.2 Open pull requests (all dependabot, 16)

| Kind | Count | CI | Why |
| ---- | ----- | -- | --- |
| ruff / mypy pin bumps — `pip` (#67, #68, #71, #72) and `pre-commit` (#50, #51) | 6 | **red** | `tools/check_tool_pins.py` requires the pin to agree across **three** files (`packages/meshsa/pyproject.toml`, `packages/jetson_yolo_gcs/pyproject.toml`, `.pre-commit-config.yaml`); dependabot moves one. The `dependabot.yml` comment says the pair "lands green once merged as a pair" — it is a **triple**, and no single PR can ever be green. Dependabot names the pre-commit side by full repository URL (`https://github.com/astral-sh/ruff-pre-commit`, `https://github.com/pre-commit/mirrors-mypy`), which matters for P0-1's `patterns:`. |
| `github-actions` majors (#37, #38, #40, #39, #48) | 5 | green | Unmerged since August; every CI log now carries the "Node.js 20 is deprecated … forced to run on Node.js 24" warning these fix. |
| other `pre-commit` revs (#41, #43, #45) | 3 | green | #43 (gitleaks 8.21.2 → 8.30.1) is green only because nothing checks the pre-commit rev against the CI `GITLEAKS_VERSION`/`GITLEAKS_SHA256` — a known trap, now with a live example. |
| structlog range widening (#42, #44) | 2 | — | stale since 2026-08-15 |

### 1.3 Size and shape

| Measure | meshsa | jetson_yolo_gcs | tools | TS (non-vendored) |
| ------- | ------ | --------------- | ----- | ----------------- |
| source files / LOC | 106 / 13 435 | 32 / 2 585 | 15 / 2 794 | 1 629 LOC total |
| test LOC | 14 890 (101 flat files) | 3 079 (`unit/` + `integration/`) | 2 464 | 357 |
| largest source file | `cot.py` 396 | `pipeline.py` 415 | `validate_agents_docs.py` **901** | `custom-fetch.ts` 371 |
| `# pragma: no cover` | 72 | 28 | 1 | — |
| `# noqa` / `type: ignore` | 4 / 2 | 10 / 0 | 8 / 1 | — |
| `except Exception` (src) | 49 across both packages + flightctl | | | |

### 1.4 Complexity hotspots (ruff `C901`/`PLR09xx` at default-ish thresholds: complexity 10, branches 12, statements 50, args 6)

| Function | Metric | Value |
| -------- | ------ | ----- |
| `ui/app.py::build_ui_app` | complexity / statements | **31** / 70 |
| `config.py::NodeConfig.from_env` | complexity / branches | 22 / 20 (135-line function) |
| `flightctl/run_commander.py::build_app` | complexity | 21 (frozen path — `scope_freeze`) |
| `scout/station/app.py::build_app` | complexity | 19 |
| `cot.py::CotCodec.decode` | complexity / branches | 17 / 17 |
| `tools/claude_hooks/literal_guard.py::_iter_magic_bindings` | complexity / branches | 15 / 14 |
| `cot.py::_decode_richer_detail`, `llm/tools.py::format_drone_state` | complexity | 11 |
| `transports/tak.py::TakTcpTransport.__init__` | arguments | **23** |
| `transports/meshtastic_radio.py::__init__` | arguments | 19 |
| `jetson pipeline.py::Pipeline.__init__`, `cot.py::CotCodec.__init__`, `msp_source.py` | arguments | 13 |
| 19 functions total over 6 args; 8 over complexity 10; 33 findings in all | | |

Four of the five aiohttp app factories (`ui/app.py`, `scout/station/app.py`, `llm/server.py`,
`health.py`, plus `flightctl/run_commander.py`) each re-implement bearer-auth, token
normalization, error responses and route wiring — the duplication T-3.1's `_web.py` (design
D-5) was specified to remove, and the reason three of the top-four complexity scores are
`build_*app` functions. The per-service `validate_bind` adapters are **not** part of that
duplication: `bind_guard` recognizes exactly that shape (design D-4), so they stay.

### 1.5 Environment trap found this pass

The cloud dev image ships **Python 3.13.17**, while `requires-python`, the classifiers, the CI
matrix and `mypy.ini`'s `python_version = 3.10` all stop at 3.12. Under 3.13, `python -m mypy
flightctl/ tools/` aborts on numpy's stubs (`Type statement is only supported in Python 3.12
and greater`) before checking a single repo file; the `mypy` on `PATH` is a *different*
interpreter with no `structlog`/`pydantic` and reports 137 bogus errors. Both are environment
artifacts, not repo defects, but they cost a turn and will cost the next agent one too —
item **P0-6** adds 3.13 to the matrix and records the trap.

---

## 2. Findings by theme

### A. CI/CD — green on `main`, structurally red on dependencies

- **A1. The pin triple.** `check_tool_pins.py` is correct to demand agreement; the defect is
  that nothing can *produce* agreement in one PR. Three fixes, pick one (§3 P0-1):
  (i) `dependabot.yml` `multi-ecosystem-groups` — one group spanning the two `pip`
  directories and `pre-commit`, so ruff/mypy bumps arrive as one PR
  (documented in dependabot-core's own `.github/dependabot.yml`: a top-level
  `multi-ecosystem-groups:` key with a `schedule`, and each `updates:` entry naming it via
  `multi-ecosystem-group:` + `patterns:`); (ii) replace the `ruff-pre-commit` / `mirrors-mypy`
  mirrors with `repo: local` hooks that run the venv's ruff/mypy, collapsing the triple to a
  pair; (iii) a single `requirements/tooling.txt` constraints file both pyprojects reference.
  (i) is the smallest diff and keeps `check_tool_pins.py` as the backstop.
- **A2. No TypeScript CI job.** `scripts/validate-pre-pr.sh` steps 1–4 run typecheck, ESLint,
  vitest and the api-server build locally; CI never does. T-2.3b deferred this "pending a
  Node/pnpm toolchain in the working environment" — that toolchain exists now (this pass ran
  all four green with `pnpm 10.28 / node 22`), so the deferral reason is gone.
- **A3. Stale green dependabot PRs.** Five actions majors and three pre-commit revs are green
  and unmerged for two months. Merging the actions set also clears the Node 20 deprecation
  warning on every job.
- **A4. gitleaks version is pinned in two places with no sync check** (`.pre-commit-config.yaml`
  `rev` vs `ci.yml` `GITLEAKS_VERSION` + `GITLEAKS_SHA256`). PR #43 is the live proof.
- **A5. `tools/` coverage is measured, not gated** (96 % today; `scope_freeze.py` at **28 %**
  because it is only subprocess-tested). The CI comment says "measure first, then gate"; it has
  been measured since August.
- **A6. Python 3.13 absent from the matrix** (§1.5).
- **A7. Release hygiene.** `version.py` has said `0.3.0` since 2026-06-13; `CHANGELOG.md` has
  one cut release (`0.1.0`, 2026-07-28) and a 410-line `[Unreleased]`. `release.yml` only fires
  on `v*` tags, so nothing has exercised it. Either cut `0.3.0` or stop claiming it.
- **A8. Docker pins.** Root `Dockerfile` runs `corepack prepare pnpm@latest` (unpinned) while
  `package.json` has no `packageManager` field — the TS CI job (A2) should read the version
  from `packageManager` via `pnpm/action-setup` rather than hard-code it, which requires adding
  that field.

### B. God files, complexity, arity

The T-4.1/T-4.2 split did its job: no source file in either package exceeds 420 lines. What is
left is **function-level**, and it clusters in three shapes:

- **B1. `build_*app` factories** (`ui/app.py` 31, `scout/station/app.py` 19,
  `run_commander.py` 21). Each inlines auth middleware, bind validation, route tables and
  error policy. T-3.1's `_web.py` removes the shared part; what remains per app should be a
  route table, which is data, not branches.
- **B2. `NodeConfig.from_env`** (22, 135 lines). Twenty `MESHSA_*` prefix blocks parsed by
  hand. T-3.2's `_envconfig.py` (a declarative prefix→model mapper) is the fix; the same helper
  retires the nine other `os.environ` parsing sites listed in Appendix B.
- **B3. `CotCodec.decode` + `_decode_richer_detail`** (17 + 11) — T-4.4 (`_CotNaming` + module-level
  encode/decode) is already specified.
- **B4. Constructor arity** — 19 functions over six parameters; the transports lead
  (`TakTcpTransport` 23, `MeshtasticTransport` 19). These are not accidental: each parameter
  is a config field with an explicit default (CHARTER §4 Invariant 5). The enterprise shape is
  a frozen `*Options` dataclass/Pydantic model per transport accepted alongside the keyword
  form (additive, back-compatible), so the registry factory passes one object and tests build
  one fixture. `tak.py`'s `TlsSettings` (T-4.2b) is the first instance of exactly this.
- **B5. `tools/validate_agents_docs.py`** — 901 lines, 30 top-level functions, zero classes,
  plus a 665-line test file. It is the largest file in the repo and growing (nine checks and
  three exception tables). Split into a `tools/agents_docs/` package by check family
  (`manifest`, `paths`, `unicode`, `rules`) behind the same CLI; the test file splits with it.
- **B6. jetson `Pipeline.__init__` (13 args) and `LandingTargetBridge` (14 methods, 291 lines)**
  — T-4.5 already names the `_SuppressionCounter` + frame-encoder strategy split.

### C. Hardcoded values

`meshsa/defaults.py` is the right pattern (leaf module, port table, separate loopback/target
constants with the rationale recorded) and `literal_guard` enforces ports, hosts, queue/backoff
names and MAVLink endpoints with four declared waivers. Adoption of the queue/backoff/endpoint/
port/host constants **shipped in T-3.5a** (13 sites; every transport constructor now defaults
from `defaults.py`) — the module's own docstring still says they are "only swept into their
~15 call sites in T-3.5", which is stale and is itself a P3-1 fix. The residual gap is the
classes of literal the sweep did not cover. The config-guardian sweep run for this plan found:

**C1. Credential defaults in shell (tightening only, highest priority) — landed 2026-10-27 as P0-8; the text below describes the tree as found.**
- `ops/pi5-node/setup_pi5_node.sh:27` — `AP_PSK="change-me-please"` is written verbatim into
  `/etc/hostapd/hostapd.conf` (`wpa_passphrase=${AP_PSK}`, line 102) and, unlike the sibling
  `mesh-up.sh`, is **not** env-overridable: an unedited run brings the field ATAK-client AP up
  on a published passphrase. Fix: `AP_PSK="${AP_PSK:?set AP_PSK}"`.
- `flightctl/scripts/start_all.sh:61` — `FTH_FTS_API_Auth="${FTH_FTS_API_Auth:-token}"` falls
  back to FreeTAKServer's upstream default SystemUser API token. Fix: no fallback; source from
  the untracked `fts.env` and skip the WebMap step when unset. Line 177 prints the upstream
  default UI credentials (`admin/password`) — cosmetic, but it normalizes leaving them.
- Neither was in [AUDIT_M2_AUTH.md](AUDIT_M2_AUTH.md); they are now rows #21 and #22.

**C2. Unrecorded all-interfaces surfaces (record, do not change) — recorded 2026-10-27 as audit rows #23–#25.**
`flightctl/systemd/fts.env.example:14-16` (`FTS_USER/API/DP_ADDRESS=0.0.0.0`, the shipped FTS
deployment example), `flightctl/systemd/mavp2p.env.example:4` (the systemd twin of audit
row #19, which cites only `start_all.sh`), and `artifacts/mockup-sandbox/vite.config.ts:60,68`
(`host: "0.0.0.0"` + `allowedHosts: true`, Replit-era dev tooling). All three are outside
`bind_guard`'s Python-only scope; the audit's inventory is the control, so they get rows with
the same "accepted, not remediated" treatment as #18.

**C3. Reachable-from-env gaps in package code (new Pydantic fields, defaults unchanged).**
- `llm/sources.py:256,297` — `timeout_s: float = 3.0` on `Mavlink2RestSource` and
  `FtsTrackSource` is not surfaced through `llm/server.py::ServerConfig`, so the only HTTP
  timeout on the assistant's upstream calls cannot be set from the environment. Home:
  `ServerConfig.source_timeout_s` + `MESHSA_LLM_SOURCE_TIMEOUT_S`.
- `scout/station/_html.py:120` — `setInterval(refresh, 3000)`: the station's browser poll
  cadence is hardcoded where the operator console injects `UIConfig.poll_interval_s`
  (`ui/_html.py:212`). Home: `ScoutConfig.station_poll_interval_s`, injected via `render_page`.
- `scout/station/_html.py:63` — the OpenStreetMap tile URL is hardcoded (third-party egress
  from the operator's browser; offline field use needs a code edit) where the console has
  `UIConfig.map_style_url`. Home: `ScoutConfig.station_tile_url`.

**C4. Port-table rows missing from `defaults.py`** (the table's own docstring claims it
records every adjacent port, including external tools): `5000` (FTS UI; `start_all.sh:52`,
`setup_pi5_node.sh:168`), `1880` (Node-RED WebMap), `14551`/`14552` (mavp2p → gateway /
mavlink2rest; `14551` also in two `flightctl/configs/*.json`), `30005` (dump1090 Beast),
`5762` (SITL TCP, `jetson_command.json`). `setup_pi5_node.sh:146,174` re-types
`tcp://${FTS_IP}:8087` twice instead of the `${FTS_COT_PORT:-8087}` form `start_all.sh` uses.
The Meshtastic `PRIVATE_APP` portnum `256` appears in `meshtastic_radio.py:105`, `cli.py:60`
and `base.env.example:6`; `literal_guard`'s `ports` rule cannot see it because it is not a
`PORT_*` name — `defaults.DEFAULT_MESHTASTIC_PORTNUM` closes that.

**C5. Timing defaults not single-sourced (outside T-3.5a's scope; P3-1).** The source-transport trio
`join_timeout_s / log_every_n / log_interval_s` (`polling_source.py:60-63`,
`msp_source.py:78-82`), `poll_interval_s=1.0` (`crsf_source.py:74`), `recv_timeout_s=1.0`
(`mavlink_source.py:83`), and `tak.py:196-198` (`pacing_rate_hz=10.0`, `pacing_burst=1`,
`read_size=4096`) all flow correctly through `TransportConfig.options` but repeat their
defaults inline. `tools/check_task_sync.py:57,94` hardcodes `timeout=60` twice while
`validate_agents_docs.py:261` defines `GIT_TIMEOUT_S = 60` "matching check_task_sync" —
name it in the file that claims the match.

**C6. Frozen zone — report only.** `command/health.py:23` `max_age_s=3.0` vs
`command/config.py:66` `arm_report_max_age_s=2.0` are two defaults for one freshness window
(`run_commander.py:138` passes the config value, so `3.0` is a dead default that disagrees
only when a caller omits it); `command/mavlink_pump.py:165` `+ 2.0` join grace is unnamed.
Already on NEXTSTEPS as a §6 decision; T-8.8 migrates both after the gate flips.

**C7. Paths and magic numbers (low).** Serial/video device defaults (`/dev/ttyUSB0`,
`/dev/ttyACM0`, `/dev/ttyAMA0`, `/dev/video0`) are all overridable but unnamed;
`base.env.example` uses the udev alias `/dev/meshsa-radio` while the CLI default is
`/dev/ttyUSB0`. `/mnt/ssd` appears ~15 times; `setup_fts.sh:22` ignores `$SSD` where
`start_all.sh` honors it. `setup_pi5_node.sh:89,100` hardcodes the DHCP range and AP channel
without deriving from `NODE_IP`/`MESH_CIDR`. `tak_multicast.py:63` `65535` → `_MAX_DATAGRAM_BYTES`.
`_EARTH_R_M = 6_371_000.0` is defined in **both** `cv/geo.py:27` and `scout/survey.py:24`
inside the same package — no dependency excuse; it belongs in `defaults.py`.

**Leave as is, justified:** systemd `RestartSec`/`WatchdogSec`, Dockerfile `HEALTHCHECK`
intervals, `start_all.sh` `wait_port` budgets, the SRI-pinned MapLibre CDN tag in
`_webpage.py`, `mavlink_fake.py` bench defaults, `inference/config.py` and `ui/config.py` URLs
(already fields), and root `Dockerfile` `ENV PORT=8080` (platform convention; consolidate to
one `ARG`).

### D. Dead, redundant and duplicated code

Method: `vulture` at confidence 60 and 80 over both `src` trees, `flightctl/` and `tools/`,
every candidate triaged against registries, `[project.scripts]`, pydantic validators,
`__all__`, pypubsub callback signatures and tests; then an AST pass over all 337 public
top-level definitions counting references in non-test source vs tests. Vulture's ~130
confidence-60 hits are false positives (registry-decorated `_make_*` factories, `model_config`,
dataclass fields, Protocol methods, the pypubsub `interface` parameter). What survived:

**D1. Confirmed dead (safe to delete, P3-2).**

| Site | Evidence |
| ---- | -------- |
| `jetson_yolo_gcs/core/errors.py:27` `ConfigError` | zero references in src, tests, docs |
| `meshsa/command/lifecycle.py:40` `MAV_RESULT_IN_PROGRESS` | zero references; siblings are used (frozen zone — delete under T-8) |
| `meshsa/transports/detection_ingest.py:66` `self._token = token` | assigned, never read; `validate_bind` consumed it two lines earlier |
| `meshsa/fpv/telemetry_store.py:28` `self._history_len` | assigned, never read; the in-file comment already says "retained for constructor compatibility" pending T-5.4 |
| `lib/db/src/index.ts:13` `export const pool` | consumed only by the next line in the same file |
| `lib/api-client-react/src/custom-fetch.ts` exports `BodyType`, `ApiError`, `ResponseParseError`, `CustomFetchOptions` | zero references including the orval-generated trees (`ErrorType` *is* used) — the unused **exports** are the finding, not the file |
| `meshsa[tak] = []`, `jetson_yolo_gcs[hailo] = []` | empty extras — install no-ops that imply a dependency set that does not exist |
| `twine` in both `[dev]` extras | `release.yml` installs its own copy; nothing local invokes it |
| `scripts/` pnpm workspace | `@workspace/scripts` with `"files": []` and **zero** `.ts` files, still typechecked by `package.json`'s `typecheck` script (documented scaffolding — fold into P3-4) |

**D2. Public `src` code referenced only by tests (maintainer decision, §7 item 5).**
Deliberate API with no in-tree consumer: `version.warn_deprecated` (the convention
CONTRIBUTING cites; never yet called), `netauth.NetAuthPolicy`/`DEFAULT_POLICY` (no surface
takes a policy; all 16 call sites use the function), `NemotronConfig.with_model`,
`command/lifecycle.is_accepted`, `Node.publish_chat` (the only `MessageKind.CHAT` producer),
`llm/sources` `Static*Source.set_*` (documented as for tests/demos). **Shipped but
unreachable from any console script:** `scout/pose.py::PoseFuser`, `scout/replay.py`
`ReplayPoseSource`/`ReplayDetectionSource`, `scout/store.by_block`, `survey.coverage_fraction`
(the `ScoutPipeline` docstring says it "wires a PoseSource"; nothing does), jetson
`mavlink/pose.py::MavlinkPoseSource` (the only concrete `PoseSource`; `cli.py` never
constructs it — this is T-10.3), jetson `utils/jetson.py` `read_tegrastats`/`set_power_mode`/
`enable_jetson_clocks` and `TimeSync.exchange` (device-only, `pragma: no cover`). The FPV
carve-out set (`ArmGuard.update_health`/`latched`, `crsf/rc.py` `ticks_to_us`/`unpack_channels`,
`FlightLogger.set_note`/`record_frame`) is **not** dead code; it is T-5.1b.

**D3. Duplication hotspots.**

| Pair | What | Fix |
| ---- | ---- | --- |
| `llm/server.py:103`, `ui/app.py:51`, `scout/station/app.py:35` | three near-identical 2-arg `validate_bind(host, token)` wrappers differing only in `service`/`remedy` strings | **Keep.** This is the shape `bind_guard` recognizes (design D-4): a `def validate_bind` outside `netauth` must delegate to the canonical symbol, and a listener file must call an imported `validate_bind` alias. A factory-produced callable would fail the checker. Only the `service`/`remedy` strings are candidates for `_web.py`'s `ServiceAuth` (D-5) |
| `cv/geo.py:27` ↔ `scout/survey.py:24` | `_EARTH_R_M` twice **inside meshsa** | `defaults.py` (C7) |
| `.github/workflows/ci.yml:81-91` ↔ `:149-159` (+ an awk variant at `:207`) | coverage-summary heredoc duplicated per job | `tools/coverage_summary.py <name> <gate>`; the `tools/` floor (P0-5) then uses it too |
| `tools/check_task_sync.py:50-99` ↔ `tools/validate_agents_docs.py:284-328` | same `subprocess.run(["git", …])` boilerplate ×5 with repeated `# noqa: S603` | `tools/_git.py::git_lines(root, *args)`; lands with P2-6 |
| `FakeClock` ×8 | `packages/meshsa/tests/conftest.py` provides the auto-increment variant; `test_ui_logring.py`, `test_ui_snapshot.py`, `test_command_lifecycle.py`, `test_command_service.py` each re-declare the *settable* variant; jetson and deliverables have their own | add a settable `FakeClock` fixture to the meshsa conftest and delete the four in-file copies (deliverables' copy is inline-by-design) |
| `meshsa/registry.py` ↔ `jetson_yolo_gcs/core/registry.py`; `meshsa/protocols.py` `Clock`/`SystemClock`/`MonotonicClock` ↔ `jetson_yolo_gcs/core/clock.py`; the two `errors.py` bases; `cv/geo.py` ↔ `geometry/ned.py` off-axis/depression math | line-for-line mirrors across the two distributions | **deliberate** under the no-`meshsa`-dependency rule; this is exactly the `meshsa_core` case (P4-1). Until then, cross-cite each from the other so a fix lands in both |
| seven checker `main(argv)` + repo-root scaffolds under `tools/` | near-identical argparse/root-resolution boilerplate | low value; mention only |

**D4. Stale references.** `docs/IMPLEMENTATION_PLAN.md` cites four spec files that do not
exist (`m2-fts-e2e.md`, `m3-richer-tracks.md`, `m4-store-and-forward.md`, `m5-packaging.md`
— "author this" to-dos phrased as paths) and `docs/NEXT_STEPS.md` (real file: `NEXTSTEPS.md`);
`docs/specs/operator-ui.md` cites a peer-review doc and an openspec bundle that do not exist;
README's tree block cites two missing paths (H3). 24 stale backticked paths repo-wide, most in
historical review docs. No commented-out code blocks; no tracked `__pycache__`/`.egg-info`;
zero `TODO`/`FIXME` in source (one in docs).

**D5. `__init__.py` re-export surfaces nobody imports through.** `meshsa/fpv` (38 names),
`meshsa/scout` (24), `meshsa/llm` (22), `jetson_yolo_gcs` (30) — **zero** in-tree importers
via the package root; `meshsa/__init__.py` exports 64 names of which 2 are imported from
source. Public API by design, so not a deletion; but every re-export is a second place a
rename must touch, and the registry side-effect imports in `meshsa/__init__.py` are
load-bearing. Record the supported import path per subpackage in `packages/meshsa/AGENTS.md`
and stop growing the root surfaces.

### E. Hardening

- **E1.** The fail-open inventory in [AUDIT_M2_AUTH.md](AUDIT_M2_AUTH.md) is current (6 rows,
  4 genuine; `0.0.0.0` mavp2p ingest in `start_all.sh` and the api-server listener are recorded
  as accepted). Nothing in this plan changes that posture; the **T-8** command-zone items stay
  gated behind `c_gate_met`.
- **E2.** `netauth.validate_bind` accepts a whitespace-only token (documented gap,
  `test_whitespace_token_currently_accepted_documented_gap`). One normalization in `netauth`
  covers all four surfaces — but NEXTSTEPS lists it as a maintainer decision, so it stays in §7.
- **E3.** 49 `except Exception` sites across `src/` + `flightctl/`. T-1 narrowed two in
  `llm/sources.py`; the rest need a one-line triage each (log-and-continue with `exc_info` is
  legitimate in a pump loop; bare swallow is not). Add ruff `BLE001` as a *per-file opt-in*
  after triage, not repo-wide.
- **E4.** `bind_guard`'s `SCAN_GLOBS` is Python-only; the one TS listener is recorded, not
  scanned. If the TS CI job (A2) lands, a 20-line ESLint `no-restricted-syntax` rule on
  `app.listen(` without a host argument is the TS-side equivalent.
- **E5.** Supply chain: actions are SHA-pinned (good); `pnpm-workspace.yaml` enforces a 1-day
  `minimumReleaseAge` (good); Python has no lockfile at all — CI installs `>=` ranges every run.
  A `constraints.txt` generated with `pip-compile`/`uv pip compile`, refreshed by dependabot,
  turns "CI went red because an upstream shipped" into a reviewed PR.

### F. Backward compatibility and reuse

- **F1.** The wire contract (`schema_version`, `MIN_COMPATIBLE_SCHEMA`, `warn_deprecated`) is
  sound and tested; nothing here bumps it. Every refactor in §3 is **behind an unchanged
  public facade** — the T-4 rule — and the `*Options` objects in B4 are additive.
- **F2.** `meshsa_core` (T-7, spec `meshsa-core.md`, status Definition) is the reuse story:
  jetson may not import meshsa, so `netauth`/`registry`/`clock`/heartbeat logic exists twice.
  It is the largest item and goes **last** because it is a new distribution with its own
  release process (A7 first).
- **F3.** `deliverables/` deliberately inlines reference implementations and pins behavior with
  `xfail(strict=True)`; T-10.2b retires `meshsa-ui-validation` once its scenarios are promoted
  into `packages/meshsa/tests`. Until then its 5 `type: ignore`s are the only ones in the tree
  that mypy marks unused.

### G. Coverage quality (not just quantity)

- **G1.** 99.3 % with 72 `pragma: no cover` in meshsa and 28 in jetson. Most are documented
  hardware/I-O glue (correct); an inventory by reason (`hardware`, `cli-glue`, `optional-dep`)
  as a comment convention lets `grep` audit them instead of a human.
- **G2.** The nightly runs the full extras install and is the only place optional-dependency
  typing drift is caught; it is **not** a superset of PR CI (no jetson, no governance). A
  weekly `full` job that *is* a superset would close the "green on PR, red on Saturday" window.
- **G3.** Hypothesis is on for codecs (`test_property_codecs.py`); `SnapshotStore` cap/TTL and
  the link-loss soak are property-tested. `NodeConfig.from_env` and `CotCodec.decode` — the two
  highest-complexity pure functions — are not. Add round-trip properties as part of B2/B3, so the
  refactor ships with a stronger oracle than the one it inherits.
- **G4.** `tools/` floor: gate at 90 now (measured 95–96 for three months), raise to 95 after
  `scope_freeze.py` gains in-process tests (its 28 % is the whole gap).

### H. Enterprise organization

- **H1. `docs/` is 37 files with three kinds of content mixed:** stable plan (CHARTER, ROADMAP,
  C4, ARCHITECTURE), working plans (NEXTSTEPS 40 KB, IMPLEMENTATION_PLAN, this file), and
  **historical records** (seven `*_PEER_REVIEW*.md`, two `GAP_ANALYSIS*`, `AUDIT_REPORT.md`
  dated 2026-06-02, `BRANCHES.md` verified 2026-07-07 against branches that no longer exist,
  `PR_BODY.md`, `AGENTS_MD_EVIDENCE.md`). Move the records to `docs/reviews/` (or
  `docs/history/`) with a one-line index; keep the stable/working split at the top level.
  `ROADMAP_RECONCILIATION.md` and `CHARTER_ALIGNMENT_AUDIT_*` stay — they are cited by
  NEXTSTEPS as process.
- **H2. Two `C4.md`s** (repo-level 12.5 KB and `docs/architecture/C4.md` 8.5 KB) — a known
  trap. Merge or rename; one should be the C4 and the other a workspace appendix.
- **H3. README's tree block is stale** — it cites `docs/PEER_REVIEW.md` and a root
  `validate-pre-pr.sh`, neither of which exists. `validate_agents_docs.py` checks cited paths
  in the five `AGENTS.md` guides; extending its `CONTEXT_SCAN_GLOBS` path check to `README.md`
  and `docs/*.md` (advisory first) is a 10-line change that makes H1 safe to execute.
- **H4. Replit scaffolding** survives in `pnpm-workspace.yaml` (a non-existent
  `lib/integrations/*` entry, `@replit/*` catalog pins and a `stripe-replit-sync` allowlist
  line) and root `package.json` (`@replit/connectors-sdk`, a Windows-only rollup binary). None is
  imported by `api-server`. T-2.3b's archive of `mockup-sandbox` + `api-client-react` is the
  moment to drop these.
- **H5. Test layout asymmetry.** meshsa has 101 flat `test_*.py` files; jetson uses
  `unit/`/`integration/`. Do **not** reorganize meshsa's tests for symmetry (wide diff, no
  behavior) — instead adopt pytest markers (`unit`, `integration`, `e2e` already exists) so the
  taxonomy in [LOCAL_TESTING_PLAN.md](LOCAL_TESTING_PLAN.md) is selectable without moving files.
- **H6. `Makefile` sprawl.** Root `Makefile` (TS, 200 lines, Replit-era), `tools/Makefile`
  (Python), `scripts/validate-pre-pr.sh` (both), `package.json` scripts, pre-commit — five
  entry points to the same gates. Keep `validate-pre-pr.sh` as the one truth; make the two
  Makefiles thin aliases to it per side, and delete targets nothing calls (`db-push`,
  `py-check`, `outdated`).

---

## 3. The plan — phased, each item independently shippable

Sizing: **S** = one PR under ~200 lines, **M** = one PR, a day, **L** = several PRs, a spec
delta. Every code item carries the standing rules: security-reviewer on anything under
`packages/`, test-engineer first, unchanged public facade, coverage floors untouched.

### Phase 0 — Make CI/CD honest (≈1 week, all S/M; no behavior change except P0-8)

| ID | Item | Theme | Size | Acceptance |
| -- | ---- | ----- | ---- | ---------- |
| **P0-1** | `dependabot.yml`: `multi-ecosystem-groups` `python-tooling` spanning `/packages/meshsa`, `/packages/jetson_yolo_gcs` (pip, `patterns: [ruff, mypy]`) and `/` (pre-commit, `patterns: ["https://github.com/astral-sh/ruff-pre-commit", "https://github.com/pre-commit/mirrors-mypy"]` — dependabot names pre-commit hooks by full repository URL, so a bare `ruff-pre-commit` pattern matches nothing); close #67/#68/#71/#72/#50/#51 **only after** the grouped PR has appeared | A1 | S | next ruff bump arrives as **one** green PR touching all three files; `check_tool_pins.py` unchanged |
| **P0-2** | Merge the five green actions PRs (#37, #38, #39, #40, #48) and the three green pre-commit PRs (#41, #43, #45); bump CI `GITLEAKS_VERSION`/`SHA256` to match #43 | A3, A4 | S | zero "Node.js 20 deprecated" warnings in a CI log |
| **P0-3** | `check_tool_pins.py::TOOLS` gains `gitleaks` (pre-commit `rev` ↔ `ci.yml` env) and `pydantic`/`pyyaml`/`pytest` (CI governance install ↔ pre-commit `additional_dependencies`) | A4 | S | the test `test_real_repo_is_in_sync` covers five tools; a mutation on `GITLEAKS_VERSION` fails it |
| **P0-4** | **`ts` CI job**: `pnpm/action-setup` (version from a new `packageManager` field) + `actions/setup-node` with `cache: pnpm`, `pnpm install --frozen-lockfile`, lib build, typecheck, lint, test, api-server build; `concurrency` and `timeout-minutes` like the others; add to CONTRIBUTING's required-checks list | A2, A8 | M | job green on this branch; `validate-pre-pr.sh` header says CI runs steps 1–4 |
| **P0-5** | `tools/` coverage floor `--cov-fail-under=90` in the governance job (measured 95–96) | A5, G4 | S | floor in CI; `ci.yml` comment updated |
| **P0-6** | Python 3.13 in both matrices + classifiers; `mypy.ini` keeps `python_version = 3.10`; AGENTS.md trap entry for the 3.13/numpy-stub behavior | A6 | S | 3.13 green or a documented skip with the failing module named |
| **P0-7** | Cut **`v0.3.0`**: move `[Unreleased]` into a dated section, tag, let `release.yml` build (PyPI step is already token-gated and will no-op) | A7 | S | tag exists; CHANGELOG `[Unreleased]` is empty |
| **P0-8** | **Operator-visible credential hardening** (C1): `AP_PSK` becomes required, `FTH_FTS_API_Auth` loses its fallback — an existing provisioning run that relied on either published default now fails fast (`setup_pi5_node.sh`) or skips the WebMap step (`start_all.sh`) until the operator sets the variable; audit rows for C1 and the three unrecorded all-interfaces surfaces (C2) — **bind-auditor** on the diff | C1, C2, E1 | S | an unedited `setup_pi5_node.sh` run fails before touching hostapd; `AUDIT_M2_AUTH.md` inventory gains five rows; CHANGELOG `### Changed` entry under operator-visible changes; the two variables documented in `ops/pi5-node/README_pi5_node.md` and `flightctl/README.md` |

**Status (2026-10-27):** P0-1, P0-3, P0-4, P0-5, P0-6 and P0-8 landed on this branch
(PR #73). P0-3 also moved gitleaks to 8.30.1 in both places, which supersedes PR #43.
P0-2 (merging the remaining green dependabot PRs #37/#38/#39/#40/#48/#41/#45 and closing
#43 as superseded) and P0-7 (tagging `v0.3.0`) are maintainer actions on `main`.
**P0-1, amended in the Phase 1 PR:** both grouped entries now use `patterns: ["*"]`,
because an entry that joins a multi-ecosystem group updates only the dependencies its
patterns match — the ruff/mypy-only patterns would have silently stopped every other
pip and pre-commit update. One weekly PR now carries all Python-side bumps. The
post-merge check still applies: the `multi-ecosystem-groups` semantics (that pip
dependencies outside the `patterns:` still get their own PRs, and that `directories:` is
accepted beside `multi-ecosystem-group:`) could not be confirmed against docs.github.com
from this environment. A dependabot config error never fails a build — it shows only under
Insights → Dependency graph → Dependabot. Open that tab after merge; if it reports a parse
error or no non-ruff/mypy pip PR ever appears again, restore the two per-directory `pip`
entries (same ecosystem + directory cannot be listed twice, so the group would then have to
go).

### Phase 1 — Guardrails before refactoring (≈1 week)

| ID | Item | Theme | Size | Acceptance |
| -- | ---- | ----- | ---- | ---------- |
| **P1-1** | Enable ruff `C90` + `PLR0911/0912/0913/0915` in both pyprojects and `ruff.toml` with **ratchet** thresholds set to today's maximum (`max-complexity = 31`, `max-args = 23`, `max-branches = 20`, `max-statements = 70`), each with a comment naming the function that sets it; lower a threshold in the same PR that fixes its function | B | S | `ruff check` clean at the ratchet; §1.4 table checked into the PR description as the starting line |
| **P1-2** | `vulture` (min-confidence 80) and a `deptry`-style unused-extras check as **advisory** steps in the governance job (warning annotations, exit 0), whitelist file committed | D | S | the step summary lists candidates; false positives whitelisted with a reason |
| **P1-3** | `validate_agents_docs.py` path-existence check extended to `README.md` and `docs/**/*.md` (advisory `::warning` first; gate after H1) | H3 | S | the two stale README paths are reported |
| **P1-4** | `pragma: no cover` reason convention (`# pragma: no cover - hardware`) + a grep-based advisory count by reason in the coverage summary | G1 | S | every pragma in `src/` carries a reason |
| **P1-5** | Pytest markers `unit`/`integration` registered (`--strict-markers` already on) and applied by directory for jetson and by filename convention for meshsa; LOCAL_TESTING_PLAN cites the selector | H5 | S | `pytest -m integration` selects the e2e/bridge/soak files |
| **P1-6** | Python lockfile: `requirements/ci-constraints.txt` compiled from both `[dev]` extras; CI installs with `-c`; dependabot `pip` entry for `/requirements` | E5 | M | a CI run installs identical versions twice in a row |

**Status (2026-10-28):** P1-1 … P1-6 landed (Phase 1 PR). Measured ratchet anchors are in
the three ruff configs; `vulture` at 80 had one false positive (whitelisted); the bare
pragma count is 1, the `__main__` guard in the frozen `run_commander.py`, which stays
until T-8 so the freeze is honored; the docs
citation sweep reports 45 dead paths on this tree (38 in `docs/*.md`, 6 in `docs/specs/`,
1 in `docs/architecture/`, 1 in README — the first measurement here said three, a misread
of a truncated output that the security review caught), which is the P3-3 worklist; the `deptry`-style unused-extras check was **not** added (the
two empty extras, `meshsa[tak]` and `jetson_yolo_gcs[hailo]`, are already on P3-2's list
and nothing else in the extras is unused). The lock was verified with `pip --dry-run`
against both packages on 3.13 and with uv on a 3.10 interpreter.

### Phase 2 — Shared foundations, then the god functions (≈3 weeks; this is T-3 + the residue of T-4)

Order matters: the foundations remove the duplication that *is* the complexity.

| ID | Item | Theme | Bundle | Size | Acceptance |
| -- | ---- | ----- | ------ | ---- | ---------- |
| **P2-1** | `meshsa/_web.py` per design D-5 — HTTP/auth/response helpers only (`ServiceAuth`, `normalize_token`, `unauthorized`, `bearer_auth_middleware`, `no_store_headers`, route-table helper); the per-service `validate_bind` adapters stay as the direct-delegating shape `bind_guard` recognizes (D-4); characterization tests first (route/status/header pins for all four apps), then migrate `health.py`, `llm/server.py`, `scout/station/app.py`, `ui/app.py` | B1, A | T-3.1 | L | `build_ui_app` complexity ≤ 12; auth matrix tests unchanged and green; `bind_guard` clean with its exceptions list unchanged |
| **P2-2** | `meshsa/_envconfig.py`: declarative `EnvPrefix` → model mapper with typed coercion + `warn_deprecated` hook; migrate `NodeConfig.from_env`, `fpv/config.py`, `ui/config.py`, `llm/server.py`, `scout/cli.py`; Hypothesis property: `from_env(to_env(cfg)) == cfg` | B2, G3 | T-3.2 | L | `from_env` ≤ 30 lines; the **seven eligible** `os.environ` sites (Appendix B) → one helper, with `command/config.py` and `run_commander.py` explicitly deferred to T-8.8 while `c_gate_met` is false; every `MESHSA_*` var still parsed (golden env-var inventory test) |
| **P2-3** | `cot.py`: `_CotNaming` + module-level `encode_*`/`decode_*` behind the `CotCodec` facade; property round-trip extended to richer detail | B3, G3 | T-4.4 | M | `decode` ≤ 10 complexity; golden snapshot files unchanged |
| **P2-4** | Transport `*Options` models (`TakTcpOptions`, `MeshtasticOptions`, `MspOptions`, `MavlinkSourceOptions`) accepted alongside keywords (additive); registry factories pass the model | B4, F1 | new (T-4.2b pattern) | M | `__init__` arity ≤ 6 on the four transports; existing keyword call sites untouched and tested |
| **P2-5** | `_queues.py` `BoundedDropQueue` adopted in `flight_logger.py`, `inference/service.py` offline queue, `ui/snapshot.py` (T-3.5a's constant sweep is already done; the C5 timing literals are P3-1's, not this item's) | D | T-3.5b | M | three drop-and-count queues share one implementation; drop counters byte-identical in existing tests; zero new `literal_guard` waivers |
| **P2-6** | `tools/agents_docs/` package split of `validate_agents_docs.py` (+ its tests) by check family; same CLI entry point | B5 | new | M | no file in `tools/` over 400 lines; checker output byte-identical on the current tree |
| **P2-7** | jetson `LandingTargetBridge` → `_SuppressionCounter` + frame-encoder strategies; `Pipeline` takes a `PipelineDeps` object | B6 | T-4.5 | M | body-FRD wire output byte-identical (existing pin); arity ≤ 6 |

### Phase 3 — Config sweep, dead code, docs organization (≈1–2 weeks)

| ID | Item | Theme | Size | Acceptance |
| -- | ---- | ----- | ---- | ---------- |
| **P3-1** | Hardcoded-value sweep per §2.C, highest-severity first; each literal becomes a config field with env binding or a `defaults.py` constant; `literal_guard` rules extended where a class of literal repeats | C | M | §2.C list empty or every remaining item carries a "leave as is" rationale in `governance.yaml` |
| **P3-2** | Dead-code removals per §2.D (confirmed set only); probable set goes to §7 | D | S–M | `vulture` advisory step reports zero at confidence 80 |
| **P3-3** | `docs/reviews/` move for the historical records (H1), `C4.md` dedupe (H2), README tree fix (H3); P1-3 flips from advisory to gating | H | S | `validate_agents_docs.py` passes with the docs path check gating |
| **P3-4** | T-2.3b: archive `mockup-sandbox` + `api-client-react`, drop Replit leftovers from `pnpm-workspace.yaml`/`package.json`, prune root `Makefile` to aliases of `validate-pre-pr.sh` | H4, H6 | M | `pnpm install` lockfile shrinks; `ts` job still green; `make validate` = steps 1–4 only, documented |
| **P3-5** | `except Exception` triage (E3) with per-file `BLE001` opt-in where the file is now clean | E3 | M | count halves; every remaining site logs `exc_info=True` or narrows |

### Phase 4 — Reuse at distribution scale (after a release exists)

| ID | Item | Theme | Bundle | Size |
| -- | ---- | ----- | ------ | ---- |
| **P4-1** | `packages/meshsa_core` extraction; `meshsa.netauth` becomes a re-export shim; jetson adopts the shim; `bind_guard` learns `mavlink_connection` | F2 | T-7.1–T-7.4 | L |
| **P4-2** | Weekly `full` workflow that is a true superset of PR CI (both packages, full extras, slow, governance, ts) | G2 | new | S |
| **P4-3** | `deliverables/meshsa-ui-validation` retirement once scenarios are promoted | F3 | T-10.2b | M |

### Explicitly not in this plan

- Anything under `command_emission_globs` beyond what T-8 already specifies (frozen while
  `c_gate_met` is false).
- Renumbering any spec `§` heading (docstrings cite them).
- Reorganizing `packages/meshsa/tests` into subdirectories (H5 uses markers instead).
- Raising the 97/96 floors — they are already exceeded by two points; the lever is *what* is
  covered (G1, G3), not the number.

---

## 4. Targets — what "done" looks like, measurably

| Metric | Today | Target (end of Phase 3) |
| ------ | ----- | ----------------------- |
| Open dependabot PRs red by design | 6 | 0 (grouped) |
| CI jobs covering the TS workspace | 0 | 1 required check |
| Functions over McCabe 10 | 8 | ≤ 2 (the frozen `run_commander.build_app` + one named exception) |
| Functions over 6 args | 19 | ≤ 6 |
| Largest file (any language) | 901 lines | ≤ 450 |
| `os.environ` parsing sites | 9 | 1 helper + `_envconfig` declarations on the 7 eligible sites; the 2 frozen sites wait for T-8.8 |
| aiohttp app factories re-implementing auth/bind | 4 | 0 (one `_web.py`) |
| `tools/` coverage floor | none | 90 → 95 |
| Python versions in CI | 3 | 4 (3.10–3.13) |
| Stale paths cited in README/docs | 2 known | 0, gated |
| Historical docs at `docs/` top level | ~11 | 0 (in `docs/reviews/`) |
| Cut releases | 1 (`0.1.0`) | `0.3.0` tagged; CHANGELOG `[Unreleased]` empty |

---

## 5. Roles (the "full team" view)

| Role | Owns in this plan |
| ---- | ----------------- |
| **Product / maintainer** | §7 decisions; P0-7 release call; the A1 option choice; accepts the ratchet thresholds in P1-1 |
| **Platform / CI engineer** | Phase 0 and Phase 1 end to end; P4-2 |
| **Framework engineer (meshsa)** | P2-1…P2-5, P3-1, P3-5 — with **security-reviewer** on every diff (binding) and **test-engineer** writing the characterization tests first |
| **Perception engineer (jetson)** | P2-7, jetson half of P1-5 and P3-1 |
| **Tooling engineer** | P2-6, P1-2, P1-3, P1-4 |
| **Docs owner** | P3-3, H1/H2/H3, CONTRIBUTING required-checks update |
| **Subagents** | `config-guardian` re-run after P3-1; `bind-auditor` on P2-1; `charter-gate-keeper` on anything near `command/` |

---

## 6. Sequencing and risk

```
Phase 0 (CI honest)  ──►  Phase 1 (guardrails)  ──►  Phase 2 (foundations → god functions)
                                                           │
                                                           ▼
                                      Phase 3 (sweep, dead code, docs)  ──►  Phase 4 (meshsa_core)
```

- Phases 0 and 1 are **zero-behavior-change with one exception** — P0-8 is operator-visible
  credential hardening (a provisioning run that relied on a published default now fails fast
  or skips a step until the variable is set) and ships with its own CHANGELOG and runbook
  lines. Within a phase, items can land in any order; the phases go first because P1-1's
  ratchet is what proves Phase 2 actually reduced complexity rather than moved it.
- Phase 2 is ordered P2-1 → P2-2 → P2-3 because `_web.py` and `_envconfig.py` are what the
  `build_*app` and `from_env` functions decompose *into*; doing the splits first would produce
  four private copies of each.
- The single highest-risk change is **P2-2** (every `MESHSA_*` env var flows through it). The
  mitigation is the golden env-var inventory test: enumerate every variable name the current
  `from_env` reads (grep + a fixture), assert the new mapper reads exactly that set, and run the
  Hypothesis round-trip. If that test is not written first, do not start P2-2.
- Nothing in Phases 0–3 changes the wire schema, a default port, a bind host, or a public
  constructor signature (new `*Options` are additive); the one operator-visible change is
  P0-8's removal of two credential defaults. Backward compatibility is otherwise by
  construction, and `CHANGELOG.md` gets one `### Changed` line per phase (plus P0-8's own),
  not per PR.

---

## 7. Decisions needed from the maintainer (CHARTER §6)

1. **A1 option** — (i) dependabot multi-ecosystem group, (ii) `repo: local` pre-commit hooks,
   or (iii) a constraints file. Recommendation: **(i)**, smallest diff, keeps the checker.
2. **Cut `v0.3.0` now (P0-7)**, or re-set `version.py` to `0.2.x` until the `[Unreleased]`
   section is reviewed? Recommendation: cut it; the changelog is already written.
3. **P1-1 ratchet thresholds** — accept "today's maximum, lowered with each fix", or set a
   hard target now and accept 33 temporary `# noqa`s? Recommendation: ratchet; `noqa`s hide
   the signal P1-1 exists to show.
4. **Whitespace-only bearer tokens (E2)** — normalize in `netauth` (one place, four surfaces)
   or document as-is. Recommendation: normalize; it is strictly a denial-side change.
5. **Dead-code "probable" set (§2.D)** — each removal is reversible, but the pre-flight
   arm-gating carve-out (`ArmGuard`, `crsf/rc.py`, `RCLink`, `record_rc`) is ratified charter
   scope with no production entry point (T-5.1b). This plan does **not** touch it; the decision
   to wire or retire it is yours and predates this pass.
6. **`docs/reviews/` move (H1)** — low risk, but it is "reorganizing folders", which the
   engineering rules reserve for deliberate decisions. Yes/no.

---

## Appendix A — How the baseline was measured

```bash
# Python gates (run from the package dir so pyproject tool config applies)
ruff check packages/meshsa flightctl tools deliverables packages/jetson_yolo_gcs --exclude archive
ruff format --check packages/meshsa flightctl tools deliverables packages/jetson_yolo_gcs --exclude archive
(cd packages/meshsa && python -m mypy src && python -m pytest -m "not slow")
(cd packages/jetson_yolo_gcs && python -m mypy src && python -m pytest)
python -m pytest tools/claude_hooks/tests tools/tests --cov=tools --cov-report=term
for c in tools/claude_hooks/bind_guard.py tools/claude_hooks/literal_guard.py tools/check_tool_pins.py \
         tools/check_task_sync.py tools/validate_workforce.py tools/validate_skills.py \
         tools/validate_agents_docs.py; do python "$c"; done

# Complexity table (§1.4) — thresholds are the ones P1-1 ratchets from
ruff check packages/meshsa/src packages/jetson_yolo_gcs/src flightctl tools deliverables \
  --exclude archive --select C901,PLR0911,PLR0912,PLR0913,PLR0915 \
  --config 'lint.mccabe.max-complexity=10' --config 'lint.pylint.max-args=6' \
  --config 'lint.pylint.max-branches=12' --config 'lint.pylint.max-statements=50' --statistics

# TypeScript gates
pnpm install --frozen-lockfile && pnpm --filter './lib/*' run build \
  && pnpm -r run typecheck && pnpm -r run lint && pnpm -r run test
```

Ruff's `C901`/`PLR09xx` thresholds (`lint.mccabe.max-complexity`, `lint.pylint.max-args`,
`max-branches`, `max-statements`; defaults 10/5/12/50) and the dependabot
`multi-ecosystem-groups` syntax were confirmed against current upstream documentation at the
time of writing; re-check them when P1-1 and P0-1 land.

## Appendix B — Environment-parsing sites that P2-2 consolidates

`packages/meshsa/src/meshsa/{cli.py, ui/cli.py, config.py, llm/agent.py, llm/server.py,
command/config.py, fpv/config.py}`, `flightctl/run_commander.py`, `flightctl/run_gateway.py`.
`command/config.py` and `run_commander.py` are frozen (`scope_freeze`) and migrate under
T-8.8 after the gate flips; the other seven migrate in P2-2.
