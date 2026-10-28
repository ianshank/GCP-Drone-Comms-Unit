"""Tool-pin sync checker: pre-commit revs must equal the pyproject dev pins.

The repo pins ruff and mypy to exact versions in both packages' ``[dev]`` extras and
mirrors the same versions in ``.pre-commit-config.yaml`` revs, so CI, pre-commit, and
local runs reach identical lint/type verdicts. This checker fails when any of the four
sources disagree — the drift class that previously left pre-commit on ruff v0.7.4 while
CI floated to 0.16.x.

gitleaks is pinned in two places with the same failure mode: the pre-commit ``rev`` and
the CI secret-scan step's ``GITLEAKS_VERSION`` (``.github/workflows/ci.yml``). Those two
are checked against each other here as well (the CI ``GITLEAKS_SHA256`` has no
pre-commit counterpart and is hand-verified on every bump).

Version-agnostic parsing (regex over the TOML/YAML text rather than ``tomllib``) keeps
the script runnable on every interpreter the repo supports.

Usage::

    python tools/check_tool_pins.py [--repo-root PATH]

Exits 1 on any mismatch or missing pin, 0 when all sources agree.
"""

from __future__ import annotations

import argparse
import logging
import re
import sys
from pathlib import Path
from typing import Final

import yaml

_log = logging.getLogger("tools.check_tool_pins")

#: pyproject files whose [dev] extras must carry exact pins.
PYPROJECTS: Final[tuple[str, ...]] = (
    "packages/meshsa/pyproject.toml",
    "packages/jetson_yolo_gcs/pyproject.toml",
)

PRECOMMIT_CONFIG: Final[str] = ".pre-commit-config.yaml"

#: The workflow whose secret-scan step pins ``GITLEAKS_VERSION``.
CI_WORKFLOW: Final[str] = ".github/workflows/ci.yml"

#: pre-commit repos, mapped to the tool they pin. Matched as a URL suffix; the
#: two-segment ``gitleaks/gitleaks`` form is deliberate so a hypothetical
#: ``something-gitleaks`` mirror cannot satisfy it.
PRECOMMIT_REPOS: Final[dict[str, str]] = {
    "ruff-pre-commit": "ruff",
    "mirrors-mypy": "mypy",
    "gitleaks/gitleaks": "gitleaks",
}

#: Tools pinned in the pyprojects + pre-commit (three files must agree).
PYPROJECT_TOOLS: Final[tuple[str, ...]] = ("ruff", "mypy")

#: Tools pinned in pre-commit + the CI workflow (two files must agree).
CI_TOOLS: Final[tuple[str, ...]] = ("gitleaks",)

TOOLS: Final[tuple[str, ...]] = PYPROJECT_TOOLS + CI_TOOLS

_PIN_RE: Final[re.Pattern[str]] = re.compile(r'"(?P<tool>ruff|mypy)==(?P<version>[^"]+)"')

#: ``GITLEAKS_VERSION: 8.21.2`` (optionally quoted) in a workflow ``env:`` block.
_CI_VERSION_RE: Final[re.Pattern[str]] = re.compile(
    r"""^\s*(?P<tool>GITLEAKS)_VERSION:\s*["']?(?P<version>[^"'\s#]+)""",
    re.MULTILINE,
)

#: The release-URL fragment the secret-scan step must build from the env value. A pinned
#: ``GITLEAKS_VERSION`` that the download line does not reference would let the checker
#: pass while CI quietly ran a hardcoded other version.
_CI_DOWNLOAD_USES_VERSION: Final[str] = "v${GITLEAKS_VERSION}/gitleaks_${GITLEAKS_VERSION}_"


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
    """Tool versions pinned by the pre-commit repo revs (leading ``v`` stripped).

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
                    revs[tool] = f"CONFLICT({revs[tool]} vs {rev} in {PRECOMMIT_CONFIG})"
                else:
                    revs[tool] = rev
    return revs


def ci_workflow_pins(text: str) -> dict[str, str]:
    """Tool versions pinned as ``<TOOL>_VERSION:`` env values in the CI workflow.

    Regex over the text rather than a YAML parse: the value lives in a step's ``env:``
    block, and a textual match is both version-agnostic and immune to the workflow's
    ``${{ }}`` expressions, which PyYAML would otherwise have to tolerate. Two
    conflicting assignments are reported via the same sentinel as the other sources.
    """
    pins: dict[str, str] = {}
    for match in _CI_VERSION_RE.finditer(text):
        tool, version = match.group("tool").lower(), match.group("version").lstrip("v")
        if tool in pins and pins[tool] != version:
            pins[tool] = f"CONFLICT({pins[tool]} vs {version} in {CI_WORKFLOW})"
        else:
            pins[tool] = version
    if "gitleaks" in pins and _CI_DOWNLOAD_USES_VERSION not in text:
        pins["gitleaks"] = (
            f"UNUSED({pins['gitleaks']}: GITLEAKS_VERSION is set but the download URL in "
            f"{CI_WORKFLOW} does not reference it)"
        )
    return pins


def _sources_for(tool: str) -> tuple[str, ...]:
    """The files that must agree on ``tool``'s pin."""
    if tool in CI_TOOLS:
        return (PRECOMMIT_CONFIG, CI_WORKFLOW)
    return PYPROJECTS + (PRECOMMIT_CONFIG,)


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
    precommit_path = repo_root / PRECOMMIT_CONFIG
    if precommit_path.is_file():
        sources[PRECOMMIT_CONFIG] = precommit_revs(precommit_path.read_text(encoding="utf-8"))
    else:
        problems.append(f"missing {PRECOMMIT_CONFIG}")
    ci_path = repo_root / CI_WORKFLOW
    if ci_path.is_file():
        sources[CI_WORKFLOW] = ci_workflow_pins(ci_path.read_text(encoding="utf-8"))
    else:
        problems.append(f"missing {CI_WORKFLOW}")

    for tool in TOOLS:
        versions = {
            name: pins.get(tool) for name, pins in sources.items() if name in _sources_for(tool)
        }
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
    logging.basicConfig(stream=sys.stderr, level=logging.INFO, format="%(name)s: %(message)s")
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--repo-root", type=Path, default=None)
    args = parser.parse_args(argv)
    repo_root = (args.repo_root or Path(__file__).resolve().parents[1]).resolve()
    _log.debug("checking tool-pin sync under %s", repo_root)
    problems = check(repo_root)
    for problem in problems:
        print(f"tool pins: {problem}")
    if problems:
        _log.warning("tool-pin sync check found %d problem(s)", len(problems))
        return 1
    print(
        "tool pins: in sync (ruff, mypy across pyprojects + pre-commit; "
        "gitleaks across pre-commit + ci.yml)"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
