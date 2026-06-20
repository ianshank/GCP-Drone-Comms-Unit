"""``jetson-yolo-gcs`` console entry point.

The pure, testable pieces (``parse_args``, :func:`health_report`) live here and are
unit-tested; the live orchestration (``run``/``export-model`` — building real devices
and looping) is glue marked ``# pragma: no cover``.

Subcommands:
  * ``--health-check`` — validate config and report the resolved backend/encoder/
    pipelines with **no hardware**; exits 0.
  * ``export-model`` — export an Ultralytics model to TensorRT/ONNX.
  * (default) ``run`` — build the real pipeline and process frames.
"""

from __future__ import annotations

import argparse
import json
import signal
import sys
from typing import TYPE_CHECKING, Any

import structlog

from .core.config import Settings, get_settings
from .core.logging import configure_logging
from .detection.factory import backend_for_path
from .streaming.camera import build_capture_pipeline
from .streaming.gstreamer import build_stream_pipeline

if TYPE_CHECKING:
    from .pipeline import Pipeline

log = structlog.get_logger("jetson_yolo_gcs.cli")

#: Default Ultralytics export target for the ``export-model`` subcommand.
_DEFAULT_EXPORT_FORMAT = "engine"


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        prog="jetson-yolo-gcs",
        description="Jetson YOLO detection -> GCS video + MAVLink LANDING_TARGET",
    )
    p.add_argument(
        "--health-check",
        action="store_true",
        help="Validate config and print the resolved plan; requires no hardware.",
    )
    sub = p.add_subparsers(dest="command")
    export = sub.add_parser(
        "export-model", help="Export an Ultralytics model (e.g. .pt -> .engine)"
    )
    export.add_argument(
        "--format", default=_DEFAULT_EXPORT_FORMAT, help="Export format (engine, onnx, ...)"
    )
    return p.parse_args(argv)


def health_report(settings: Settings) -> dict[str, Any]:
    """Build a hardware-free summary of what the pipeline *would* do.

    Pure: resolves the detection backend by extension and renders the capture/stream
    pipeline strings without opening any device.
    """
    return {
        "detection": {
            "model_path": settings.yolo.model_path,
            "backend": backend_for_path(settings.yolo.model_path),
            "device": settings.yolo.device,
        },
        "camera": {
            "type": settings.camera.type.value,
            "pipeline": build_capture_pipeline(settings.camera),
        },
        "stream": {
            "enabled": settings.stream.enabled,
            "encoder": settings.stream.encoder.value,
            "pipeline": build_stream_pipeline(settings.stream),
        },
        "mavlink": {
            "endpoint": settings.mavlink.endpoint,
            "landing_target_enabled": settings.mavlink.enable_landing_target,
        },
        "pipeline": {
            "idle_poll_s": settings.pipeline.idle_poll_s,
            "max_consecutive_empty": settings.pipeline.max_consecutive_empty,
            "liveness_timeout_s": settings.pipeline.liveness_timeout_s,
        },
    }


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    settings = get_settings()
    configure_logging(settings.log_level, json_logs=settings.json_logs)

    if args.health_check:
        report = health_report(settings)
        print(json.dumps(report, indent=2))
        return 0

    if args.command == "export-model":  # pragma: no cover - real ultralytics export
        from ultralytics import YOLO

        model = YOLO(settings.yolo.model_path)
        model.export(format=args.format)
        return 0

    # Default: run the real pipeline.
    from .pipeline import build_pipeline  # pragma: no cover - real hardware wiring

    pipeline = build_pipeline(settings)  # pragma: no cover
    _install_signal_handlers(pipeline)  # pragma: no cover
    try:  # pragma: no cover
        pipeline.run(
            max_consecutive_empty=settings.pipeline.max_consecutive_empty,
            idle_poll_s=settings.pipeline.idle_poll_s,
        )
    finally:  # pragma: no cover
        pipeline.close()
    return 0


def _install_signal_handlers(pipeline: Pipeline) -> None:  # pragma: no cover - process glue
    """Wire SIGINT/SIGTERM to a clean loop stop so systemd shutdown drains the pipeline."""

    def _handler(_signum: int, _frame: object) -> None:
        log.info("shutdown signal received; stopping pipeline")
        pipeline.request_stop()

    for sig in (signal.SIGINT, signal.SIGTERM):
        signal.signal(sig, _handler)


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
