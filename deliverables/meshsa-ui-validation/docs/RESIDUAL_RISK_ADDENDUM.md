# Residual Risk Acceptance — meshsa.ui (Gate 2)

> **Status:** Draft — for insertion into ``docs/specs/operator-ui.md`` as §6.1
> and into the ``docs/AUDIT_M2_AUTH.md`` surface #17 row.
>
> These are risks that are **explicitly accepted by the operator**, not gaps
> that need fixing before the spec moves to ``Validated``.  Each entry states
> the risk, the mitigation already in place, and the record of acceptance.
>
> Insert the markdown below at the appropriate locations in the target files
> before signing off on ``Validated`` status.

---

## For insertion into ``docs/specs/operator-ui.md`` — new §6.1

```markdown
## 6.1  Residual risk acceptance

The following risks are acknowledged and explicitly accepted by the operator
for the v1 deployment envelope.  They do not block ``Validated`` status but
MUST be communicated to any operator who configures a non-loopback bind.

### R1 — Bearer token over plaintext HTTP (non-loopback binding only)

**Condition:** When ``MESHSA_UI_HOST`` is set to a non-loopback address (e.g.
the node's field LAN IP), the ``Authorization: Bearer`` header and the
``?token=`` query parameter transit an unencrypted HTTP channel between the
phone browser and the edge node.

**Why accepted:** TLS termination is an explicit v1 non-goal (§1); the
field LAN is the trust boundary.  Traffic never leaves the local network
in the intended deployment topology (isolated HaLow/WiFi mesh, no internet
bridge).

**Mitigations in place:**
- Fail-closed ``validate_bind``: a non-loopback bind without a token refuses
  to start (``ValueError`` at construction, ``SystemExit`` in ``main``).
- The systemd unit ships with ``MESHSA_UI_HOST=127.0.0.1`` (loopback-only
  by default); operators who widen it must explicitly set ``MESHSA_UI_TOKEN``
  in the env file.
- ``Cache-Control: no-store`` on all token-bearing responses (scenario S5)
  prevents disk persistence by a shared browser or caching proxy.
- ``STOPPING=1`` sd_notify on graceful shutdown prevents a brief window where
  the service is down but the watchdog has not yet expired.

**Residual exposure:** A passive attacker on the same field LAN segment
(e.g. a rogue device on the mesh network) can capture the token from a
single observed HTTP exchange.  No mitigation short of TLS termination
eliminates this risk.

**Acceptance:** Recorded here per CHARTER §4.7 and AUDIT_M2_AUTH.md §Surface
\#17.  TLS termination is tracked as a follow-up spec amendment (out of scope
for v1).

---

### R2 — TAK multicast on all interfaces (CoT multicast surface)

**Condition:** ``TakMulticastTransport`` binds ``("", 6969)`` on all
interfaces with no authentication or encryption.  Any device on any network
interface of the edge node can send or receive multicast CoT frames.

**Why accepted:** This is inherent to the CoT multicast protocol; restricting
the bind would break ATAK discovery on the field LAN.  The existing ATAK
ecosystem relies on this behavior; it is not a regression introduced by
``meshsa.ui``.

**Mitigations in place:**
- Already documented in AUDIT_M2_AUTH.md (surface #2, ``TakMulticastTransport``).
- The edge node is deployed on an isolated field network; internet-reachable
  interfaces are out of scope for the default deployment topology.

**Residual exposure:** Unauthenticated inbound CoT datagrams can be injected
by any device on any LAN segment reachable by the multicast group address
(``239.2.3.1``).

**Acceptance:** Unchanged from the original AUDIT_M2_AUTH.md assessment.
No new surface introduced by ``meshsa.ui``.

---

### R3 — sd_notify heartbeat requires ``sdnotify`` package (optional dep)

**Condition:** The ``WatchdogSec`` watchdog in the systemd unit is only
active when the ``sdnotify`` Python package is installed.  Without it,
``_send_notify`` is a documented no-op and the watchdog is silently
inactive.

**Why accepted:** The console still runs correctly without the package;
only the watchdog gate is affected.  Crash-based restart (``Restart=
on-failure``) still works; the watchdog adds protection against event-loop
stalls that do not crash the process.

**Mitigation:** ``sdnotify`` is listed in the ``[ui]`` extra
(``pyproject.toml``) so ``pip install 'meshsa[ui]'`` includes it.  The
``meshsa-ui.service`` unit file comments note the dependency.  The
``_send_notify`` helper logs a debug-level message when sdnotify is absent.

**Acceptance:** Recorded here.  The unit test ``test_send_notify_no_sdnotify_
package_is_noop`` asserts the graceful fallback behavior.
```

---

## For insertion into ``docs/AUDIT_M2_AUTH.md`` — surface #17 row update

Replace the existing (placeholder or partial) surface #17 row in the
``AUDIT_M2_AUTH.md`` surface inventory table with the row below.

```markdown
| 17 | `meshsa.ui` — `app.py:build_ui_app` | Inbound (HTTP server) | ``127.0.0.1:8100`` (``MESHSA_UI_HOST``/``MESHSA_UI_PORT``) | Bearer token on ``/api/*``; ``?token=`` on ``/``; ``/healthz`` open. Fail-closed via ``netauth.validate_bind`` at construction — non-loopback without a token raises ``ValueError``. ``Cache-Control: no-store`` on all token-bearing responses. | Plaintext HTTP by default; TLS termination is a v1 non-goal (operator-ui.md §1). Residual risk R1 accepted in operator-ui.md §6.1. | Fails closed — loopback or token required; construction-time ``validate_bind`` enforced |
```

---

## Changelog entry (for ``CHANGELOG.md``)

```markdown
### Gate 2 — Residual risk recorded (operator-ui v1)

- Added ``docs/specs/operator-ui.md §6.1`` documenting three accepted residual
  risks: bearer-over-plaintext-HTTP (R1), TAK multicast all-interfaces (R2),
  and sdnotify-optional watchdog (R3).
- Updated ``docs/AUDIT_M2_AUTH.md`` surface #17 row to reflect v1 shipping
  state: fail-closed bind, bearer auth, ``Cache-Control: no-store``,
  plaintext HTTP (TLS deferred).
```

---

## NEXTSTEPS tick (operator-ui field validation section)

Once Gate 2 documentation is merged, add the following tick to the
``NEXTSTEPS.md`` operator-ui section:

```markdown
- [x] Residual risk acceptance recorded in operator-ui.md §6.1 and
      AUDIT_M2_AUTH.md surface #17 (Gate 2 complete)
```
