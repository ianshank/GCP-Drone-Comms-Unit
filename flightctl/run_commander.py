#!/usr/bin/env python3
"""Supervised commanding service (Initiative C) — the thin, live wiring.

This entry point assembles the tested ``meshsa.command`` pieces around a real
pymavlink link and an authenticated HTTP endpoint. All the logic (allow-list,
confirmation gate, ACK/retry/timeout, audit, pre-arm interlock) lives in
``meshsa.command`` and is fakes-tested; this file is the un-covered glue, mirroring
``run_gateway.py``.

Security posture (matches the §-gate in docs/specs/initiative-c-commanding-design.md):
  * Binds **loopback by default**; refuses a non-loopback bind without a token
    (``MESHSA_CMD_TOKEN``) — fail-closed, reusing the ``meshsa.llm`` auth pattern.
  * The command channel can be MAVLink2-signed (``MESHSA_CMD_SIGNING_KEY_FILE``).
  * Default allow-list is whitelist-first (``set_mode``, ``rtl``); arm/disarm and
    ``goto`` are opt-in; force-disarm needs its own flag **and** a force confirm.

Endpoints (all command routes require ``Authorization: Bearer <token>`` when set):
  * ``POST /command/stage``   {"name", "params"}            -> {confirmation_id, ...}
  * ``POST /command/confirm`` {"confirmation_id","force_ack"} -> {accepted, result, ...}
  * ``POST /command/cancel``  {"confirmation_id"}           -> {ok: true}
  * ``GET  /healthz``                                       -> {status: ok}

NOTE: arming additionally requires a fresh health report. The ``MavlinkCommandPump``
feeds autopilot heartbeats into the pre-arm interlock, so ``arm`` is permitted only
while the link is live and fails closed the moment heartbeats go stale.
"""

from __future__ import annotations

import argparse
import asyncio
import os
from pathlib import Path
from typing import Any

import structlog
from meshsa.command import (
    CommanderConfig,
    CommandError,
    CommandSender,
    CommandService,
    ConfirmationGate,
    ForceConfirmationRequired,
    HeartbeatHealth,
    JsonlAuditLog,
    MavlinkCommandLink,
    MavlinkCommandPump,
    UnknownCommandError,
    UnknownConfirmationError,
)
from meshsa.command.errors import (
    ArmBlockedError,
    CommandNotAllowedError,
    ForceDisarmDisabledError,
)
from meshsa.llm.server import authorize, is_loopback
from meshsa.protocols import MonotonicClock, SystemClock, UuidFactory
from pydantic import ValidationError

_log = structlog.get_logger("flightctl.commander")

ENV_TOKEN = "MESHSA_CMD_TOKEN"
ENV_SIGNING_KEY_FILE = "MESHSA_CMD_SIGNING_KEY_FILE"

# CommandError subclasses -> HTTP status. A 409 means "the request was understood
# but refused by policy/state"; 400 means "malformed/unknown".
_STATUS_FOR: dict[type[CommandError], int] = {
    UnknownCommandError: 400,
    CommandNotAllowedError: 403,
    ForceDisarmDisabledError: 403,
    UnknownConfirmationError: 404,
    ForceConfirmationRequired: 409,
    ArmBlockedError: 409,
}


def load_config(path: str) -> CommanderConfig:
    """Load + validate the commander config, failing closed with a clear message."""
    try:
        return CommanderConfig.from_file(path)
    except FileNotFoundError as exc:
        raise SystemExit(f"commander config not found: {path}") from exc
    except ValidationError as exc:
        # pydantic reports both malformed JSON/encoding and schema violations here.
        raise SystemExit(f"invalid commander config {path}:\n{exc}") from exc
    except OSError as exc:  # unreadable (permissions) / is-a-directory / I/O error
        raise SystemExit(f"cannot read commander config {path}: {exc}") from exc


def _read_signing_key(path: str | None) -> bytes | None:
    """Read the optional 32-byte MAVLink2 signing key file (fail closed on bad size)."""
    if not path:
        return None
    key = Path(path).read_bytes()
    if len(key) != 32:
        raise SystemExit(
            f"{ENV_SIGNING_KEY_FILE}: MAVLink2 signing key must be 32 bytes, got {len(key)}"
        )
    return key


def build_service(
    cfg: CommanderConfig, *, signing_key: bytes | None
) -> tuple[CommandService, JsonlAuditLog, MavlinkCommandPump]:
    """Wire the live link + pump + audit + gate + sender + service from the config.

    The :class:`MavlinkCommandPump` is the single owner of the autopilot socket: it
    serves COMMAND_ACKs to the sender *and* feeds autopilot heartbeats to the
    pre-arm interlock, so ``arm`` is gated on live link health rather than failing
    closed unconditionally. The pump is returned so the caller can shut it down.

    The only secret this needs (the signing key) is passed explicitly; the process
    environment is *not* handed in, so no token/key can leak through this seam.
    """
    from pymavlink import mavutil  # local import: needs the [mavlink] extra

    settings = cfg.to_settings()
    target_system = cfg.target_system
    target_component = cfg.target_component

    audit = JsonlAuditLog(cfg.audit_path, clock=SystemClock())
    audit.start()

    # One connection, one reader (pump), one writer (link): see mavlink_pump docs.
    connection = mavutil.mavlink_connection(cfg.mavlink_endpoint)
    link = MavlinkCommandLink(
        connection=connection,
        target_system=target_system,
        target_component=target_component,
        signing_key=signing_key,
    )

    clock = MonotonicClock()  # same timebase as HealthReport.t_mono (arm freshness)
    # HeartbeatHealth shares the service's freshness window so the provider and the
    # service's re-check (arm_report_max_age_s) agree on what "fresh" means.
    health = HeartbeatHealth(clock, max_age_s=settings.arm_report_max_age_s)
    pump = MavlinkCommandPump(
        link,
        connection=connection,
        target_system=target_system,
        target_component=target_component,
        on_heartbeat=health.beat,
    )
    pump.start()  # starts the send link (signing) + the single reader thread

    sender = CommandSender(pump, audit, settings=settings, clock=clock, expect_system=target_system)
    service = CommandService(
        gate=ConfirmationGate(UuidFactory()),
        sender=sender,
        settings=settings,
        audit=audit,
        clock=clock,
        health_provider=health,  # live pre-arm interlock, fed by the pump's heartbeats
    )
    return service, audit, pump


def validate_bind(host: str, token: str | None) -> None:
    """Fail closed: refuse a non-loopback bind without a token (command surface!)."""
    if not is_loopback(host) and token is None:
        raise SystemExit(
            f"refusing to bind the command service to {host!r} without {ENV_TOKEN} set. "
            "A command endpoint must never be exposed unauthenticated. Set "
            f"{ENV_TOKEN} to a strong secret, or bind to 127.0.0.1."
        )


def build_app(service: CommandService, token: str | None) -> Any:
    """Build the aiohttp app. Blocking service calls run in the default executor."""
    from aiohttp import web

    async def _run(fn: Any, *args: Any) -> Any:
        return await asyncio.get_running_loop().run_in_executor(None, fn, *args)

    def _guard(request: Any) -> Any | None:
        if not authorize(token, request.headers.get("Authorization")):
            return web.json_response({"error": "unauthorized"}, status=401)
        return None

    async def stage(request: Any) -> Any:
        denied = _guard(request)
        if denied is not None:
            return denied
        try:
            payload = await request.json()
        except Exception:
            return web.json_response({"error": "expected a JSON object"}, status=400)
        name = payload.get("name")
        params = payload.get("params") or {}
        if not isinstance(name, str) or not isinstance(params, dict):
            return web.json_response({"error": "missing 'name' or bad 'params'"}, status=400)
        try:
            staged = await _run(service.stage, name, params)
        except CommandError as exc:
            return web.json_response({"error": str(exc)}, status=_STATUS_FOR.get(type(exc), 400))
        except (TypeError, ValueError) as exc:
            # build_command forwards **params to the builder; a bad kwarg name or a
            # non-numeric value raises TypeError/ValueError -> client error, not 500.
            return web.json_response({"error": f"bad params: {exc}"}, status=400)
        return web.json_response(
            {
                "confirmation_id": staged.confirmation_id,
                "name": staged.name,
                "command": staged.command,
                "requires_force_confirm": staged.requires_force_confirm,
            }
        )

    async def confirm(request: Any) -> Any:
        denied = _guard(request)
        if denied is not None:
            return denied
        try:
            payload = await request.json()
        except Exception:
            return web.json_response({"error": "expected a JSON object"}, status=400)
        token_id = payload.get("confirmation_id")
        force_ack = bool(payload.get("force_ack", False))
        if not isinstance(token_id, str):
            return web.json_response({"error": "missing 'confirmation_id'"}, status=400)

        def _do() -> Any:
            return service.confirm(token_id, force_ack=force_ack)

        try:
            outcome = await _run(_do)
        except CommandError as exc:
            return web.json_response({"error": str(exc)}, status=_STATUS_FOR.get(type(exc), 400))
        status = 200 if outcome.accepted else 502
        return web.json_response(
            {
                "accepted": outcome.accepted,
                "result": outcome.result,
                "attempts": outcome.attempts,
                "reason": outcome.reason,
                "name": outcome.spec.name,
                "command": outcome.spec.command,
            },
            status=status,
        )

    async def cancel(request: Any) -> Any:
        denied = _guard(request)
        if denied is not None:
            return denied
        try:
            payload = await request.json()
        except Exception:
            return web.json_response({"error": "expected a JSON object"}, status=400)
        token_id = payload.get("confirmation_id")
        if not isinstance(token_id, str):
            return web.json_response({"error": "missing 'confirmation_id'"}, status=400)
        await _run(service.cancel, token_id)
        return web.json_response({"ok": True})

    async def healthz(_request: Any) -> Any:
        return web.json_response({"status": "ok"})

    app = web.Application()
    app.router.add_post("/command/stage", stage)
    app.router.add_post("/command/confirm", confirm)
    app.router.add_post("/command/cancel", cancel)
    app.router.add_get("/healthz", healthz)
    return app


def main() -> None:  # pragma: no cover - process entry point
    parser = argparse.ArgumentParser(description="Supervised MAVLink commanding service")
    parser.add_argument("--config", required=True, help="path to the commander JSON config")
    args = parser.parse_args()

    try:
        import aiohttp  # noqa: F401  # presence check; web imported in build_app
        import pymavlink  # noqa: F401  # presence check; mavutil imported in build_service
    except ImportError as exc:
        raise SystemExit(
            "run_commander needs the [mavlink] and [llm] extras (pymavlink + aiohttp).\n"
            "Install:  pip install -e 'packages/meshsa[mavlink,llm]'\n"
            f"(missing dependency: {exc.name})"
        ) from exc

    from aiohttp import web

    cfg = load_config(args.config)
    token = (os.environ.get(ENV_TOKEN) or "").strip() or None
    validate_bind(cfg.host, token)  # fail closed before opening a socket

    # Read only the one secret we need from the environment — never hand the whole
    # process environment to build_service (no token/key can leak through it).
    signing_key = _read_signing_key(os.environ.get(ENV_SIGNING_KEY_FILE))
    service, audit, pump = build_service(cfg, signing_key=signing_key)
    try:
        web.run_app(build_app(service, token), host=cfg.host, port=cfg.port)
    finally:
        pump.close()
        audit.close()


if __name__ == "__main__":  # pragma: no cover
    main()
