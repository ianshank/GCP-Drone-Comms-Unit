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
import sys
from typing import Any

import structlog

from .core.config import Settings, get_settings
from .core.logging import configure_logging
from .detection.factory import backend_for_path
from .streaming.camera import build_capture_pipeline
from .streaming.gstreamer import build_stream_pipeline

log = structlog.get_logger("jetson_yolo_gcs.cli")


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
    export.add_argument("--format", default="engine", help="Export format (engine, onnx, ...)")
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
    try:  # pragma: no cover
        pipeline.run()
    finally:  # pragma: no cover
        pipeline.close()
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
