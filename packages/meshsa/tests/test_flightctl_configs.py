"""Regression tests for the SHIPPED flightctl config files.

These pin the operational contracts that broke during live bring-up — the Betaflight AETR
channel order (throttle at index 2) and the MSP gateway building a real ``msp_source`` node —
so a future edit to the JSON can't silently reintroduce a throttle/yaw swap or drop the FC leg.
No hardware: the board/poll are injected.
"""

from pathlib import Path

import pytest
from test_msp_source import FakeBoard, _fix_poll

from meshsa import (
    JoystickChannelSource,
    JsEvent,
    MspSourceTransport,
    NodeConfig,
    build_node,
    load_mapping,
)
from meshsa.rc import RC_MAX

_REPO = Path(__file__).resolve().parents[3]
_CONFIGS = _REPO / "flightctl" / "configs"


def test_msp_gateway_config_builds_fc_node():
    cfg = NodeConfig.from_file(str(_CONFIGS / "jetson_gateway.msp.json"))
    node = build_node(
        cfg,
        transport_kwargs={"fc": {"board": FakeBoard(), "poll": _fix_poll()}},
    )
    fc = next(t for t in node.router.transports if t.name == "fc")
    assert isinstance(fc, MspSourceTransport)  # not silently skipped as "unknown type"
    assert fc._coord_scale == pytest.approx(1e7)
    assert fc._callsign == "FC1"
    # the CoT leg must carry the air pli_type from codec_options, not the ground default
    tak = next(t for t in cfg.transports if t.name == "tak")
    assert tak.codec_options["pli_type"] == "a-f-A-M-F-Q"


def test_rc_config_honors_betaflight_aetr_order():
    m = load_mapping(str(_CONFIGS / "jetson_rc.json"))
    # AETR contract: throttle is channel index 2 (NOT 3), ARM is index 4, 8 channels total.
    assert m.throttle_channel == 2
    assert m.arm.channel == 4
    assert len(m.channels) == 8

    # Behavioural regression for the live throttle/yaw swap: drive the real source and assert
    # a high throttle stick lands at index 2 and ARM at index 4 — not the RPYT default layout.
    class _Reader:
        def __init__(self, evs):
            self._evs = list(evs)

        def read(self):
            return self._evs.pop(0) if self._evs else []

    reader = _Reader(
        [
            [JsEvent("axis", 7, -32767)],  # arm switch low → ready
            [JsEvent("axis", 7, 32767), JsEvent("axis", 2, 32767)],  # arm high + throttle high
        ]
    )
    src = JoystickChannelSource(reader, m)
    src.channels(now=1.0)
    chans = src.channels(now=1.1)
    assert chans[2] == RC_MAX  # throttle axis drives channel index 2 (AETR)
    assert chans[4] == RC_MAX  # ARM on index 4
