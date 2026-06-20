"""Logging configuration + CLI health-check (pure paths)."""

from __future__ import annotations

import json
import logging

import pytest

from jetson_yolo_gcs.cli import health_report, main, parse_args
from jetson_yolo_gcs.core.config import Settings
from jetson_yolo_gcs.core.logging import configure_logging, log_level_num


def test_log_level_num_known_and_unknown() -> None:
    assert log_level_num("debug") == logging.DEBUG
    assert log_level_num("not-a-level") == logging.INFO


def test_configure_logging_json_and_console() -> None:
    configure_logging("INFO", json_logs=True)
    configure_logging("DEBUG", json_logs=False)  # both branches run without error


def test_health_report_resolves_plan() -> None:
    report = health_report(Settings())
    assert report["detection"]["backend"] == "ultralytics"
    assert "v4l2src" in report["camera"]["pipeline"]
    assert "x264enc" in report["stream"]["pipeline"]
    assert report["mavlink"]["landing_target_enabled"] is False
    # Loop policy is surfaced for pre-flight validation.
    assert report["pipeline"]["idle_poll_s"] == 0.01
    assert report["pipeline"]["max_consecutive_empty"] is None
    assert report["pipeline"]["liveness_timeout_s"] == 2.0


def test_main_health_check_prints_json(capsys: pytest.CaptureFixture[str]) -> None:
    rc = main(["--health-check"])
    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["detection"]["backend"] == "ultralytics"


def test_parse_args_export_subcommand() -> None:
    args = parse_args(["export-model", "--format", "onnx"])
    assert args.command == "export-model"
    assert args.format == "onnx"
