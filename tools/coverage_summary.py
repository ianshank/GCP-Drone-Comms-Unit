#!/usr/bin/env python3
"""Print one Markdown line summarising a ``coverage.xml`` for the CI job summary.

Three CI jobs used to carry the same heredoc (plan P3-2, §2.D D3): parse the Cobertura
XML pytest-cov writes, print the line/branch rates against the job's gate, and say so
plainly when the file is missing (pytest failed before writing it, or the ``xml``
report was dropped from the command). This is that heredoc, once.

Usage::

    python tools/coverage_summary.py NAME GATE [--xml PATH] >> "$GITHUB_STEP_SUMMARY"

Always exits 0: the summary is reporting, never the gate — the gate is pytest's own
``--cov-fail-under``, and a summary step that failed would hide the number precisely
in the run where it caused the failure.
"""

from __future__ import annotations

import argparse
import sys
import xml.etree.ElementTree as ET
from pathlib import Path


def summarize(name: str, gate: int, xml_path: Path) -> str:
    """The Markdown line for *xml_path*, or the missing-file explanation."""
    if not xml_path.is_file():
        return (
            f"**{name} coverage**: {xml_path.name} not produced (pytest failed before "
            "writing it, or --cov-report=xml was dropped)"
        )
    root = ET.parse(xml_path).getroot()  # our own pytest-cov artifact, not untrusted input
    line_rate = float(root.get("line-rate", "0")) * 100
    # Without ``--cov-branch`` coverage.py still writes branch-rate="0" and
    # branches-valid="0"; printing "0.00% branches" would read as a real measurement.
    if int(root.get("branches-valid", "0")) > 0:
        branch_rate = float(root.get("branch-rate", "0")) * 100
        branches = f", {branch_rate:.2f}% branches"
    else:
        branches = ""
    return f"**{name} coverage**: {line_rate:.2f}% lines{branches} (gate: {gate}%)"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("name", help="label for the line, e.g. meshsa")
    parser.add_argument("gate", type=int, help="the job's --cov-fail-under value, for display")
    parser.add_argument(
        "--xml",
        default="coverage.xml",
        type=Path,
        help="Cobertura XML path (default: ./coverage.xml)",
    )
    args = parser.parse_args(argv)
    print(summarize(args.name, args.gate, args.xml))
    return 0


if __name__ == "__main__":
    sys.exit(main())
