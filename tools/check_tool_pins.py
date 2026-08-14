"""Tool-pin sync checker: pre-commit revs must equal the pyproject dev pins.

The repo pins ruff and mypy to exact versions in both packages' ``[dev]`` extras and
mirrors the same versions in ``.pre-commit-config.yaml`` revs, so CI, pre-commit, and
local runs reach identical lint/type verdicts. This checker fails when any of the four
sources disagree — the drift class that previously left pre-commit on ruff v0.7.4 while
CI floated to 0.16.x.

Version-agnostic parsing (regex over the TOML text rather than ``tomllib``) keeps the
script runnable on every interpreter the repo supports.

Usage::

    python tools/check_tool_pins.py [--repo-root PATH]

Exits 1 on any mismatch or missing pin, 0 when all sources agree.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path
from typing import Final

import yaml

#: pyproject files whose [dev] extras must carry exact pins.
PYPROJECTS: Final[tuple[str, ...]] = (
    "packages/meshsa/pyproject.toml",
    "packages/jetson_yolo_gcs/pyproject.toml",
)

#: pre-commit mirror repos, mapped to the tool they pin.
PRECOMMIT_REPOS: Final[dict[str, str]] = {
    "ruff-pre-commit": "ruff",
    "mirrors-mypy": "mypy",
}

TOOLS: Final[tuple[str, ...]] = ("ruff", "mypy")

_PIN_RE: Final[re.Pattern[str]] = re.compile(r'"(?P<tool>ruff|mypy)==(?P<version>[^"]+)"')


def pyproject_pins(text: str, rel_path: str) -> dict[str, str]:
    """Exact ``tool==version`` pins found in one pyproject's text.

    Duplicate conflicting pins for the same tool in one file are a mismatch in
    themselves and reported via a sentinel value.
    """
    pins: dict[str, str] = {}
    for match in _PIN_RE.finditer(text):
        tool, version = match.group("tool"), match.group("version")
        if tool in pins and pins[tool] != version:
            pins[tool] = f"CONFLICT({pins[tool]} vs {version} in {rel_path})"
        else:
            pins[tool] = version
    return pins


def precommit_revs(text: str) -> dict[str, str]:
    """Tool versions pinned by the pre-commit mirror revs (leading ``v`` stripped).

    An empty or comment-only file parses to ``None``, not ``{}`` — calling ``.get`` on
    that raised an uncaught ``AttributeError``, turning a truncated config into a
    traceback instead of a reported problem. A repo entry whose ``rev`` is missing or
    empty is reported as a missing pin (see :func:`check`), not as a distinct version.
    """
    data = yaml.safe_load(text) or {}
    if not isinstance(data, dict):
        return {}
    revs: dict[str, str] = {}
    for repo in data.get("repos") or []:
        if not isinstance(repo, dict):
            continue
        url = str(repo.get("repo", ""))
        for suffix, tool in PRECOMMIT_REPOS.items():
            if url.rstrip("/").endswith(suffix):
                rev = str(repo.get("rev") or "").lstrip("v")
                if tool in revs and revs[tool] != rev:
                    revs[tool] = f"CONFLICT({revs[tool]} vs {rev} in .pre-commit-config.yaml)"
                else:
                    revs[tool] = rev
    return revs


def check(repo_root: Path) -> list[str]:
    """All pin-sync problems found; empty when every source agrees."""
    problems: list[str] = []
    sources: dict[str, dict[str, str]] = {}
    for rel in PYPROJECTS:
        path = repo_root / rel
        if not path.is_file():
            problems.append(f"missing pyproject: {rel}")
            continue
        sources[rel] = pyproject_pins(path.read_text(encoding="utf-8"), rel)
    precommit_path = repo_root / ".pre-commit-config.yaml"
    if precommit_path.is_file():
        sources[".pre-commit-config.yaml"] = precommit_revs(
            precommit_path.read_text(encoding="utf-8")
        )
    else:
        problems.append("missing .pre-commit-config.yaml")

    for tool in TOOLS:
        versions = {name: pins.get(tool) for name, pins in sources.items()}
        # Falsy, not just None: a mirror repo present with an empty/missing `rev` yields
        # "", which previously escaped the missing check, landed in `present` as a
        # distinct version, and was then filtered out of the detail string — producing a
        # "pins disagree" message that listed only the sources that agreed.
        missing = [name for name, version in versions.items() if not version]
        problems.extend(f"{name}: no exact {tool} pin found" for name in missing)
        present = {version for version in versions.values() if version}
        if len(present) > 1:
            detail = ", ".join(
                f"{name}={version or '<missing>'}" for name, version in sorted(versions.items())
            )
            problems.append(f"{tool} pins disagree: {detail}")
    return problems


def main(argv: list[str] | None = None) -> int:
    """CLI entry point; exits 1 on any mismatch, 0 when in sync."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--repo-root", type=Path, default=None)
    args = parser.parse_args(argv)
    repo_root = (args.repo_root or Path(__file__).resolve().parents[1]).resolve()
    problems = check(repo_root)
    for problem in problems:
        print(f"tool pins: {problem}")
    if problems:
        return 1
    print("tool pins: in sync (ruff, mypy across pyprojects + pre-commit)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
