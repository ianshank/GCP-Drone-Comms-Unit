"""Static literal-guard linter: service literals live in the defaults module, once.

Scans the repo (``packages/**/src/**/*.py`` and ``flightctl/**/*.py``) with :mod:`ast`
and enforces the single-home rule from ``.claude/governance.yaml`` (``literal_guard``
section): operational service literals must be sourced from the canonical defaults
module (``meshsa/defaults.py``) instead of re-typed at call sites. Four rules:

* ``ports`` — an int constant equal to any ``PORT_*`` value. The port set is derived
  by AST-parsing the defaults module, never hardcoded here: a new port table row
  automatically widens the rule.
* ``hosts`` — a string constant exactly equal to ``127.0.0.1`` or ``0.0.0.0``.
  Exact equality only: operator-remedy messages and docstrings that merely contain
  an address never match, so the checker cannot pressure prose (including in
  governance-frozen files) into the exception list.
* ``magics`` — a numeric default bound to a parameter, field, or call keyword named
  ``queue_maxsize`` / ``backoff_initial_s`` / ``backoff_max_s`` / ``backoff_factor``.
  Name-keyed, not value-keyed: matching the values (1000, 1.0, 30.0, 2.0) would
  false-positive across geometry code and unit conversions, while name-keying also
  catches a drifted value (e.g. ``queue_maxsize=500``).
* ``endpoints`` — a string constant matching ``^(udpin|udpout|tcpin|tcpout):\\S+``.
  Anchored with a required remainder, so the prefix-stripping tuple in
  ``mavlink_source.py`` (``"udpin:"`` etc.) and prose containing endpoints mid-string
  never match.

Exceptions are declared in the governance config as ``{path, rule, rationale}`` —
scoped to one rule (or ``*``), so a file waived for one literal class stays scanned
for the others. The defaults module itself is excluded in code: it is the canonical
home, not a waiver.

Usage::

    python tools/claude_hooks/literal_guard.py [--repo-root PATH]

Prints findings (file, line, rule) and exits 1 on any non-excepted finding, 0 when
clean; excepted findings are summarized to stderr so waivers stay visible.
"""

from __future__ import annotations

import argparse
import ast
import logging
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Final

if __package__ in (None, ""):
    # Executed directly (the invocation CI and validate-pre-pr.sh use); align the
    # import path with bind_guard.py so both resolve one module identity under mypy.
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from tools.claude_hooks.governance import (
    CLAUDE_DIR_NAME,
    GOVERNANCE_FILENAME,
    GovernanceConfigError,
    LiteralGuardConfig,
    find_repo_root,
    load_governance,
)

_log = logging.getLogger("claude_hooks.literal_guard")

#: Host strings whose exact value marks a re-typed service default.
HOST_LITERALS: Final[frozenset[str]] = frozenset({"127.0.0.1", "0.0.0.0"})

#: Parameter/field/keyword names whose numeric defaults must come from the
#: defaults module (name-keyed matching; see module docstring).
MAGIC_NAMES: Final[frozenset[str]] = frozenset(
    {"queue_maxsize", "backoff_initial_s", "backoff_max_s", "backoff_factor"}
)

#: MAVLink-style endpoint literals (anchored, remainder required).
ENDPOINT_RE: Final[re.Pattern[str]] = re.compile(r"^(udpin|udpout|tcpin|tcpout):\S+")

#: Repo-relative glob patterns enumerating the files the linter scans. tools/ is
#: deliberately absent: it holds no service defaults, and including it would need
#: bind_guard-style self-exclusion for this file's own fixture strings.
SCAN_GLOBS: Final[tuple[str, ...]] = (
    "packages/**/src/**/*.py",
    "flightctl/**/*.py",
)


@dataclass(frozen=True)
class Finding:
    """One finding: repo-relative path, 1-based line, rule name, and message."""

    rel_path: str
    line: int
    rule: str
    message: str

    def render(self) -> str:
        """Human-readable single-line form (``path:line: [rule] message``)."""
        return f"{self.rel_path}:{self.line}: [{self.rule}] {self.message}"


def load_port_table(defaults_source: str, defaults_path: str) -> frozenset[int]:
    """Derive the service-port set from ``PORT_*`` assignments in the defaults module.

    Refuses (raises :class:`GovernanceConfigError`) when no ``PORT_*`` rows parse:
    an empty set would silently disable the ports rule.
    """
    try:
        tree = ast.parse(defaults_source, filename=defaults_path)
    except SyntaxError as exc:  # pragma: no cover - defaults module must parse to ship
        raise GovernanceConfigError(f"cannot parse defaults module {defaults_path}: {exc}") from exc
    ports: set[int] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Assign):
            continue
        if not (isinstance(node.value, ast.Constant) and type(node.value.value) is int):
            continue
        for target in node.targets:
            if isinstance(target, ast.Name) and target.id.startswith("PORT_"):
                ports.add(node.value.value)
    if not ports:
        raise GovernanceConfigError(
            f"no PORT_* int assignments found in {defaults_path}; refusing to run the "
            f"ports rule against an empty set"
        )
    return frozenset(ports)


def _int_value(node: ast.expr) -> int | None:
    """The int value of a constant node, excluding bools; ``None`` otherwise."""
    if isinstance(node, ast.Constant) and type(node.value) is int:
        return node.value
    return None


def _num_value(node: ast.expr) -> float | None:
    """The numeric (int/float, not bool) value of a constant node; ``None`` otherwise."""
    if isinstance(node, ast.Constant):
        value = node.value
        if isinstance(value, int | float) and not isinstance(value, bool):
            return float(value)
    return None


def _iter_magic_bindings(tree: ast.Module) -> list[tuple[str, ast.expr, int]]:
    """Every (name, default-value expression, line) binding a MAGIC_NAMES name.

    Covers function-signature defaults (positional and keyword-only), call keywords
    (constructor call sites, ``Field(...)``-style), and module/class-level
    ``name = value`` / ``name: T = value`` assignments.
    """
    bindings: list[tuple[str, ast.expr, int]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
            positional = node.args.posonlyargs + node.args.args
            defaulted = positional[len(positional) - len(node.args.defaults) :]
            for arg, default in zip(defaulted, node.args.defaults, strict=True):
                if arg.arg in MAGIC_NAMES:
                    bindings.append((arg.arg, default, default.lineno))
            for arg, kw_default in zip(node.args.kwonlyargs, node.args.kw_defaults, strict=True):
                if kw_default is not None and arg.arg in MAGIC_NAMES:
                    bindings.append((arg.arg, kw_default, kw_default.lineno))
        elif isinstance(node, ast.Call):
            for keyword in node.keywords:
                if keyword.arg in MAGIC_NAMES:
                    bindings.append((keyword.arg, keyword.value, keyword.value.lineno))
        elif isinstance(node, ast.AnnAssign):
            if (
                node.value is not None
                and isinstance(node.target, ast.Name)
                and node.target.id in MAGIC_NAMES
            ):
                bindings.append((node.target.id, node.value, node.value.lineno))
        elif isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id in MAGIC_NAMES:
                    bindings.append((target.id, node.value, node.value.lineno))
    return bindings


def scan_file(source: str, rel_path: str, port_table: frozenset[int]) -> list[Finding]:
    """Lint one file's source against all four literal rules.

    Pure (no filesystem access), so tests can drive it with synthetic sources.
    Exceptions are applied by the caller (:func:`scan_repo`), keeping this function
    a complete report of what the file contains.
    """
    try:
        tree = ast.parse(source, filename=rel_path)
    except SyntaxError as exc:
        return [
            Finding(
                rel_path,
                exc.lineno or 1,
                "syntax-error",
                f"cannot parse file for literal-guard analysis: {exc.msg}",
            )
        ]

    findings: list[Finding] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Constant):
            continue
        int_val = _int_value(node)
        if int_val is not None and int_val in port_table:
            findings.append(
                Finding(
                    rel_path,
                    node.lineno,
                    "ports",
                    f"service port {int_val} re-typed outside the defaults module "
                    f"(use the PORT_* constant)",
                )
            )
        if isinstance(node.value, str):
            if node.value in HOST_LITERALS:
                findings.append(
                    Finding(
                        rel_path,
                        node.lineno,
                        "hosts",
                        f"host literal {node.value!r} re-typed outside the defaults module "
                        f"(use DEFAULT_LOOPBACK_HOST / DEFAULT_LOCAL_TARGET_HOST / "
                        f"DEFAULT_MULTICAST_IFACE)",
                    )
                )
            elif ENDPOINT_RE.match(node.value):
                findings.append(
                    Finding(
                        rel_path,
                        node.lineno,
                        "endpoints",
                        f"MAVLink endpoint literal {node.value!r} re-typed outside the "
                        f"defaults module (use DEFAULT_MAVLINK_ENDPOINT or a config field)",
                    )
                )

    for name, value, line in _iter_magic_bindings(tree):
        if _num_value(value) is not None:
            findings.append(
                Finding(
                    rel_path,
                    line,
                    "magics",
                    f"numeric default for {name!r} re-typed outside the defaults module "
                    f"(use the DEFAULT_* constant)",
                )
            )
    return findings


def iter_scan_files(repo_root: Path, config: LiteralGuardConfig) -> list[Path]:
    """The de-duplicated, sorted set of files selected by :data:`SCAN_GLOBS`.

    Excludes the defaults module itself (the canonical home of these literals).
    """
    files: set[Path] = set()
    for pattern in SCAN_GLOBS:
        files.update(p for p in repo_root.glob(pattern) if p.is_file())
    files.discard(repo_root / config.defaults_module)
    return sorted(files)


def split_findings(
    findings: list[Finding], config: LiteralGuardConfig
) -> tuple[list[Finding], list[Finding]]:
    """Partition ``findings`` into (violations, excepted) per the governance config."""
    waived: dict[str, set[str]] = {}
    for entry in config.exceptions:
        waived.setdefault(entry.path, set()).add(entry.rule)
    violations: list[Finding] = []
    excepted: list[Finding] = []
    for finding in findings:
        rules = waived.get(finding.rel_path, set())
        if "*" in rules or finding.rule in rules:
            excepted.append(finding)
        else:
            violations.append(finding)
    return violations, excepted


def scan_repo(
    repo_root: Path, config: LiteralGuardConfig
) -> tuple[list[Finding], list[Finding], int]:
    """Scan every selected file; returns (violations, excepted findings, files scanned)."""
    defaults_path = repo_root / config.defaults_module
    if not defaults_path.is_file():
        raise GovernanceConfigError(f"defaults module not found: {defaults_path}")
    port_table = load_port_table(defaults_path.read_text(encoding="utf-8"), config.defaults_module)
    findings: list[Finding] = []
    files = iter_scan_files(repo_root, config)
    for path in files:
        rel_path = path.relative_to(repo_root).as_posix()
        source = path.read_text(encoding="utf-8", errors="replace")
        findings.extend(scan_file(source, rel_path, port_table))
    violations, excepted = split_findings(findings, config)
    return violations, excepted, len(files)


def main(argv: list[str] | None = None) -> int:
    """CLI entry point; exits 1 on any non-excepted finding, 0 when clean."""
    logging.basicConfig(stream=sys.stderr, level=logging.INFO, format="%(name)s: %(message)s")
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--repo-root",
        type=Path,
        default=None,
        help="repository root to scan (default: CLAUDE_PROJECT_DIR or auto-detected)",
    )
    args = parser.parse_args(argv)
    repo_root = (args.repo_root or find_repo_root()).resolve()
    try:
        config = load_governance(repo_root / CLAUDE_DIR_NAME / GOVERNANCE_FILENAME)
    except GovernanceConfigError as exc:
        print(f"literal guard: {exc}", file=sys.stderr)
        return 1
    if config.literal_guard is None:
        print(
            f"literal guard: no literal_guard section in {CLAUDE_DIR_NAME}/{GOVERNANCE_FILENAME}",
            file=sys.stderr,
        )
        return 1
    try:
        violations, excepted, scanned = scan_repo(repo_root, config.literal_guard)
    except GovernanceConfigError as exc:
        print(f"literal guard: {exc}", file=sys.stderr)
        return 1
    for finding in violations:
        print(finding.render())
    for finding in excepted:
        _log.info("excepted: %s", finding.render())
    if violations:
        print(
            f"literal guard: {len(violations)} violation(s) "
            f"({len(excepted)} excepted) across {scanned} scanned file(s)"
        )
        return 1
    print(f"literal guard: clean ({len(excepted)} excepted, {scanned} file(s) scanned)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
