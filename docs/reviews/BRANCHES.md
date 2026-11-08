# Branch Disposition

Verified 2026-07-07 against `origin/main` @ `efca0ec3e6fbe39b4d0075ec9507d4a42ab9839d`
(via `git fetch origin`; all commands below are read-only — no branch, ref, or PR
state was mutated to produce this document).

---

## `feat/tls-cot-and-fts-pacing` — SUPERSEDED (safe to close)

**Verification commands run:**

```
$ git log --oneline origin/main..origin/feat/tls-cot-and-fts-pacing
e6c7beb chore(release): 0.3.0 — docs, version bump, SleepFn de-dup
6a84165 feat(meshsa): inline FTS rate-limit pacing for the TAK TCP transport
53ef2df feat(meshsa): TLS CoT for the TAK TCP transport (:8089)
```

```
$ git diff --stat origin/main...origin/feat/tls-cot-and-fts-pacing
 CHANGELOG.md                                       |  27 ++++
 README.md                                          |   2 +-
 docs/NEXTSTEPS.md                                  |  12 +-
 flightctl/README.md                                |  39 ++++-
 flightctl/configs/jetson_gateway.tls.json          |  38 +++++
 flightctl/scripts/gen_certs.sh                     |  87 +++++++++++
 flightctl/systemd/fts.env.example                  |   3 +
 packages/meshsa/README.md                          |  10 +-
 packages/meshsa/pyproject.toml                     |   2 +-
 packages/meshsa/src/meshsa/pacing.py               |  36 +++++
 packages/meshsa/src/meshsa/protocols.py            |   5 +-
 .../src/meshsa/transports/meshtastic_radio.py      |   4 +-
 packages/meshsa/src/meshsa/transports/tak.py       |  95 +++++++++++-
 packages/meshsa/src/meshsa/version.py              |   2 +-
 packages/meshsa/tests/test_pacing.py               |  73 ++++++++++
 packages/meshsa/tests/test_tak.py                  | 159 ++++++++++++++++++++-
 16 files changed, 579 insertions(+), 15 deletions(-)
```

**Cross-check that the two feature commits already landed on main** (equivalent
content reached main via different SHAs — `a54e3ac` / `49f9bf2` — rather than a
fast-forward of this branch):

```
$ git log -1 --oneline a54e3ac
a54e3ac feat(tak): add opt-in TLS CoT (:8089) to TakTcpTransport

$ git log -1 --oneline 49f9bf2
49f9bf2 feat(tak): add opt-in FTS pacing (token-bucket rate limit)

$ git merge-base --is-ancestor a54e3ac origin/main && echo "a54e3ac IS ancestor of origin/main"
a54e3ac IS ancestor of origin/main

$ git merge-base --is-ancestor 49f9bf2 origin/main && echo "49f9bf2 IS ancestor of origin/main"
49f9bf2 IS ancestor of origin/main
```

**No PR is attached to this branch** (checked via `gh pr list --head
feat/tls-cot-and-fts-pacing`, which returned `[]`).

**Conclusion — reality matches the brief's expectation exactly.** All three
non-main commits are accounted for:

- `53ef2df` (TLS CoT) and `6a84165` (FTS pacing) are feature-equivalent to
  `a54e3ac` / `49f9bf2`, both confirmed ancestors of `origin/main`. No unique
  product code remains outside main.
- `e6c7beb` is a `0.3.0` release/version-bump commit (CHANGELOG, README,
  `version.py`, docs) whose underlying features are already present in main.
  It carries no product code that isn't already shipped.

This branch is **fully superseded** and safe to delete. No unique product code
was found absent from `origin/main`.

**Human action required (NOT run by this task — read-only constraint):**

```bash
git push origin --delete feat/tls-cot-and-fts-pacing
```

No GitHub PR is attached to this branch (verified above), so no `gh pr close`
is needed for this one.

---

## PR #11 `feat/fc-msp-telemetry-rc-pilot` — DECISION REQUIRED (do not close)

**PR metadata** (read-only `gh pr view`):

```
$ gh pr view 11 --json number,title,state,headRefName,url
{
  "number": 11,
  "title": "feat(flightctl): Betaflight FC telemetry + pilot-from-Jetson (MSP RC), TLS CoT, FTS pacing",
  "state": "OPEN",
  "headRefName": "feat/fc-msp-telemetry-rc-pilot",
  "url": "https://github.com/ianshank/GCP-Drone-Comms-Unit/pull/11"
}
```

**Verification commands run:**

```
$ git log --oneline origin/main..origin/feat/fc-msp-telemetry-rc-pilot
da7d86c fix: address PR #11 review comments + shell-lint failure
4ce24d6 merge: integrate main into fc-msp-telemetry-rc-pilot
7e139d6 feat(flightctl): Betaflight FC telemetry track + pilot-from-Jetson (MSP RC)
e6c7beb chore(release): 0.3.0 — docs, version bump, SleepFn de-dup
6a84165 feat(meshsa): inline FTS rate-limit pacing for the TAK TCP transport
53ef2df feat(meshsa): TLS CoT for the TAK TCP transport (:8089)
```

```
$ git diff --stat origin/main...origin/feat/fc-msp-telemetry-rc-pilot
 .gitignore                                         |   3 +
 CHANGELOG.md                                       |  22 +
 docs/NEXTSTEPS.md                                  |  43 +-
 docs/PR_BODY_fc_pilot.md                           |  52 ++
 flightctl/README.md                                | 128 ++++-
 flightctl/configs/jetson_gateway.msp.json          |  53 ++
 flightctl/configs/jetson_gateway.tls.json          |  38 ++
 flightctl/configs/jetson_rc.json                   |  16 +
 flightctl/rc_bridge.py                             | 202 ++++++++
 flightctl/scripts/gen_certs.sh                     |  88 ++++
 flightctl/scripts/start_all.sh                     | 118 +++--
 flightctl/systemd/fts.env.example                  |   3 +
 packages/meshsa/README.md                          |  10 +-
 packages/meshsa/pyproject.toml                     |   1 +
 packages/meshsa/src/meshsa/__init__.py             |  38 ++
 packages/meshsa/src/meshsa/cot.py                  |   9 +-
 packages/meshsa/src/meshsa/pacing.py               |  36 ++
 packages/meshsa/src/meshsa/protocols.py            |   5 +-
 packages/meshsa/src/meshsa/rc.py                   | 546 +++++++++++++++++++++
 packages/meshsa/src/meshsa/telemetry.py            |  16 +-
 .../meshsa/src/meshsa/transports/msp_source.py     | 232 ++++++++-
 packages/meshsa/src/meshsa/transports/tak.py       |  99 +++-
 packages/meshsa/tests/test_cot.py                  |  16 +
 packages/meshsa/tests/test_flightctl_configs.py    |  69 +++
 packages/meshsa/tests/test_msp_bridge_e2e.py       |  89 ++++
 packages/meshsa/tests/test_msp_source.py           | 114 +++++
 packages/meshsa/tests/test_pacing.py               |  73 +++
 packages/meshsa/tests/test_rc.py                   | 527 ++++++++++++++++++++
 packages/meshsa/tests/test_tak.py                  | 168 ++++++-
 packages/meshsa/tests/test_telemetry_codec.py      |  18 +
 30 files changed, 2759 insertions(+), 73 deletions(-)
```

```
$ git show origin/main:packages/meshsa/src/meshsa/rc.py
fatal: path 'packages/meshsa/src/meshsa/rc.py' does not exist in 'origin/main'

$ git show origin/main:flightctl/rc_bridge.py
fatal: path 'flightctl/rc_bridge.py' does not exist in 'origin/main'
```

Both confirmed absent from main, as expected.

**Unique files not in main** (actual list from the diffstat above; sizes are
the diffstat line-change counts, not raw file line counts):

- `packages/meshsa/src/meshsa/rc.py` — new, 546 lines added (RC/pilot-from-Jetson)
- `flightctl/rc_bridge.py` — new, 202 lines added
- `flightctl/configs/jetson_rc.json` — new, 16 lines
- `flightctl/configs/jetson_gateway.msp.json` — new, 53 lines
- `packages/meshsa/tests/test_rc.py` — new, 527 lines added
- `packages/meshsa/tests/test_msp_bridge_e2e.py` — new, 89 lines added
- `packages/meshsa/tests/test_msp_source.py` — new, 114 lines added
- `packages/meshsa/tests/test_flightctl_configs.py` — new, 69 lines added
- `packages/meshsa/src/meshsa/transports/msp_source.py` — modified, +232/-? (MSP telemetry source, richer tracks)
- `packages/meshsa/src/meshsa/telemetry.py` — modified, 16 lines changed
- `packages/meshsa/src/meshsa/cot.py` — modified, 9 lines changed
- `packages/meshsa/src/meshsa/__init__.py` — modified, 38 lines added
- `docs/PR_BODY_fc_pilot.md` — new, 52 lines
- `flightctl/scripts/start_all.sh` — modified, 118 lines changed
- Plus the TLS-CoT / FTS-pacing commits (`53ef2df`, `6a84165`) and the `0.3.0`
  release commit (`e6c7beb`) inherited from `feat/tls-cot-and-fts-pacing`,
  which are **already superseded by main** (see section above) — these are
  not unique/at-risk work.

**Overlap risk — confirmed real, not hypothetical.** The current
`chore/harden-0.3.x` / `feat/m3-richer-tracks` branches carry M3.2 commits
(`ddfdaa7`, `4ba3ce8`, `fb92b47`) that were verified to be:

```
$ git branch -a --contains ddfdaa7
  chore/harden-0.3.x
+ feat/m3-richer-tracks
(repeats identically for 4ba3ce8 and fb92b47)
```

- present on local/`origin/chore/harden-0.3.x` and
  local/`origin/feat/m3-richer-tracks`, and
- **absent** from `origin/main` and from `origin/feat/fc-msp-telemetry-rc-pilot`
  itself (`git merge-base --is-ancestor <sha> origin/feat/fc-msp-telemetry-rc-pilot`
  returned "NOT ancestor" for all three).

This means M3.2-flavored work (POI/FOV, stable multi-UAS UIDs, richer MAVLink
tracks) is being developed in parallel on two different lineages —
`chore/harden-0.3.x`/`feat/m3-richer-tracks` on one side, and PR #11's MSP/RC
groundwork on the other — with no common ancestor carrying both. A naive merge
of PR #11 after `chore/harden-0.3.x` lands on main risks duplicate/conflicting
telemetry-track and CoT-detail logic in `msp_source.py`, `telemetry.py`, and
`cot.py`.

**Blocking factor:** the RC/pilot-from-Jetson path in `rc.py` /
`rc_bridge.py` is a **command surface** (it can move flight-control inputs,
not just report telemetry). Per CHARTER §3, command surfaces must clear the
M2 TLS+auth gate before merge. This PR must be sequenced **after** Tier-1/M2
work lands, regardless of which merge strategy is chosen below.

**Decision required (maintainer) — do not close PR #11.** Three options:

1. **Rebase PR #11 on current main and merge the RC/MSP slice.** Highest
   integration cost (must reconcile with whatever `chore/harden-0.3.x` /
   `feat/m3-richer-tracks` M3.2 work has landed by then), but preserves full
   commit history and the already-passing test suite (`test_rc.py`,
   `test_msp_bridge_e2e.py`, etc.) as-is.
2. **Port only `rc.py` + `rc_bridge.py` in a fresh PR off main.** Lower
   integration risk — cherry-picks just the RC/pilot command-surface code
   without dragging in the (now-superseded) TLS-CoT/pacing history or the
   MSP-telemetry pieces that may already be reaching main via
   `chore/harden-0.3.x` / `feat/m3-richer-tracks`. Requires re-verifying test
   coverage lands cleanly against whatever `msp_source.py`/`telemetry.py`
   shape exists on main at that time.
3. **Abandon PR #11 and re-derive the RC/pilot feature from scratch** once
   Tier-1/M2 (TLS+auth gate) and the M3.2 richer-tracks work are both settled
   on main. Highest cost in re-implementation effort, lowest risk of merge
   conflicts or duplicated logic.

In all three cases: sequence after Tier-1/M2 (TLS+auth gate, CHARTER §3)
lands on main, and re-diff against main immediately before executing to catch
any further overlap from `chore/harden-0.3.x` / `feat/m3-richer-tracks`.

**No branch or PR mutation was performed to produce this document.** `PR #11`
remains `OPEN` at the time of writing.
