# Gate 0.2 — Port 8099 Deconfliction Guide

> **Status:** Pending — apply before field validation (Gate 3).
>
> This document describes the change needed to resolve the deployment hazard
> identified in ``AUDIT_M2_AUTH.md``:
>
>   *"The shared default port 8099 between ``detection_ingest`` (UDP) and the
>    scout station (TCP) is confusing and worth deconflicting."*
>
> Source files to change are in ``packages/meshsa/src/meshsa/``.

---

## Problem

Two services share default port 8099:

| Service | Protocol | Default port | Source |
|---------|----------|-------------|--------|
| ``DetectionIngestTransport`` | UDP | 8099 | ``transports/detection_ingest.py:50`` |
| Scout station (``ScoutConfig``) | TCP (aiohttp) | 8099 | ``scout/config.py:163`` (approx.) |

These use different protocols so there is no OS-level conflict when both
run on the same node.  However, an operator who enables both and reads the
logs will see two services claiming the same port — one UDP, one TCP — which
is ambiguous, error-prone in firewall rules, and will eventually cause a real
collision if the protocol separation is ever removed.

---

## Change

Assign the scout station a new, distinct default port.  The detection ingest
transport keeps 8099 (it is already documented in ``AUDIT_M2_AUTH.md`` as
surface #10).

**Proposed new default for the scout station: ``8101``**

Selection rationale:
- 8100 is already reserved for ``meshsa.ui`` (``UIConfig.DEFAULT_UI_PORT``).
- 8101 is unassigned in the AUDIT inventory.
- Stays in the 81xx block used by the meshsa HTTP services, keeping the
  port map coherent.

### Files to change

**1. ``packages/meshsa/src/meshsa/scout/config.py``** — change the scout
station port default from 8099 to 8101:

```python
# Before:
port: int = Field(default=8099, gt=0, lt=65536)

# After:
port: int = Field(default=8101, gt=0, lt=65536)
```

**2. ``docs/AUDIT_M2_AUTH.md``** — update the scout station row's port column
from 8099 to 8101.

**3. ``docs/specs/operator-ui.md`` §5.1** — add a note to the ``MESHSA_UI_PORT``
entry confirming that 8100 is the UI port and 8101 is scout:

```
| `port` | `int` | `8100` | `MESHSA_UI_PORT` | … (distinct from scout station 8101) |
```

**4. ``CHANGELOG.md``** — add an entry:

```markdown
### Gate 0.2 — Port 8099 deconfliction

- Changed ``ScoutConfig`` default port from 8099 (shared with
  ``DetectionIngestTransport`` UDP) to 8101 to prevent ambiguity.
- Updated AUDIT_M2_AUTH.md scout station row.
- Operators who pinned ``MESHSA_SCOUT_PORT=8099`` via env are unaffected
  (env overrides the default); operators relying on the default should
  update their firewall rules and any hardcoded references.
```

---

## Backward-compatibility note

The change is the default value only.  Any deployment that sets
``MESHSA_SCOUT_PORT`` explicitly in its env file keeps that value and is
unaffected.  Only deployments that relied on the undocumented default of 8099
for the scout station need to update their firewall rules.  Since the default
was a known bug (shared with another service), no compatibility shim is
needed.

---

## Test change

The existing ``tests/test_scout_config.py`` likely asserts the default port
as 8099.  Update that assertion:

```python
# Before:
assert cfg.port == 8099

# After:
assert cfg.port == 8101
```

No new test is needed; the existing coverage is sufficient once the assert
is updated.

---

## NEXTSTEPS tick

Once this change is merged, add the following tick to the ``NEXTSTEPS.md``
operator-ui section:

```markdown
- [x] Port 8099 deconfliction: scout station default changed to 8101
      (AUDIT_M2_AUTH.md follow-up, Gate 0.2)
```
