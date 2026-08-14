"""Static bind-guard linter: every network listener routes through the audited primitive.

Scans the repo (``packages/**/src/**/*.py`` and ``flightctl/*.py``) with :mod:`ast`
for network-listener creation and enforces the single-primitive rule from
``.claude/governance.yaml`` (``bind_guard`` section):

* a file that creates a listener must import the required symbol
  (``validate_bind``) via ``from <module> import validate_bind`` (aliases and
  re-exporting packages accepted) *and* call it — or be a declared exception;
* a ``def validate_bind`` outside the canonical module (``meshsa.netauth``) is a
  violation of the single-primitive rule **unless** it is a delegating adapter:
  the module imports the symbol from the canonical module (any ``from ...netauth
  import validate_bind [as alias]``, relative imports included) and the function
  body calls that imported alias. Local re-implementations are violations.

Usage::

    python tools/claude_hooks/bind_guard.py [--repo-root PATH]

Prints human-readable findings (file, line, trigger) and exits 1 on any
violation, 0 when clean.
"""

from __future__ import annotations

import argparse
import ast
import logging
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Final

if __package__ in (None, ""):
    # Executed directly (`python tools/claude_hooks/bind_guard.py` — the invocation both
    # .claude/settings.json and CI use), so the repo root is not on sys.path as a package
    # parent. Add it and import the fully-qualified module below, rather than maintaining a
    # second import path to a differently-named top-level module (that duplication is what
    # previously made this file and tools/claude_hooks/governance.py resolve as two distinct
    # module identities under mypy).
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from tools.claude_hooks.governance import (
    CLAUDE_DIR_NAME,
    GOVERNANCE_FILENAME,
    BindGuardConfig,
    GovernanceConfigError,
    find_repo_root,
    load_governance,
)

_log = logging.getLogger("claude_hooks.bind_guard")

#: Call names (plain names or attribute names) that indicate creation of a
#: network listener. Covers asyncio (`create_datagram_endpoint`, `create_server`,
#: `start_server`), raw sockets (`bind`), and aiohttp serving (`TCPSite`,
#: `run_app`). Extending this set is a code change reviewed like any policy edit.
LISTENER_TRIGGERS: Final[frozenset[str]] = frozenset(
    {
        "create_datagram_endpoint",
        "create_server",
        "bind",
        "TCPSite",
        "run_app",
        "start_server",
    }
)

#: Repo-relative glob patterns enumerating the files the linter scans.
#: T-2.4: widened to include tools/ (but excluding tests and the linter itself).
SCAN_GLOBS: Final[tuple[str, ...]] = (
    "packages/**/src/**/*.py",
    # Recursive, matching literal_guard: the one-level `flightctl/*.py` form left
    # flightctl/sim/ (and any future subpackage) invisible to the bind guard, while
    # tasks.md T-2.4 recorded the recursive form as landed.
    "flightctl/**/*.py",
    "tools/**/*.py",
)


@dataclass(frozen=True)
class Finding:
    """One violation: repo-relative path, 1-based line, trigger, and message."""

    rel_path: str
    line: int
    trigger: str
    message: str

    def render(self) -> str:
        """Human-readable single-line form (``path:line: message``)."""
        return f"{self.rel_path}:{self.line}: [{self.trigger}] {self.message}"


def _call_name(node: ast.Call) -> str | None:
    """The terminal name of a call target (``x()`` -> ``x``, ``a.b.x()`` -> ``x``)."""
    func = node.func
    if isinstance(func, ast.Name):
        return func.id
    if isinstance(func, ast.Attribute):
        return func.attr
    return None


def _module_name(rel_path: str) -> str:
    """Dotted module name for a repo-relative file path.

    Path components up to and including the first ``src`` are dropped (the
    src-layout root), so ``packages/meshsa/src/meshsa/netauth.py`` maps to
    ``meshsa.netauth``. ``__init__.py`` maps to its package name.
    """
    parts = list(Path(rel_path).parts)
    if "src" in parts:
        parts = parts[parts.index("src") + 1 :]
    if parts and parts[-1].endswith(".py"):
        parts[-1] = parts[-1][: -len(".py")]
    if parts and parts[-1] == "__init__":
        parts = parts[:-1]
    return ".".join(parts)


def _canonical_aliases(tree: ast.Module, symbol: str, canonical_module: str) -> set[str]:
    """Names bound by importing ``symbol`` from the canonical module.

    Accepts absolute and relative forms: any ``ImportFrom`` whose module string
    ends with the canonical module's last segment (e.g. ``meshsa.netauth``,
    ``..netauth``) and imports ``symbol`` (optionally aliased).
    """
    tail = canonical_module.rsplit(".", 1)[-1]
    aliases: set[str] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.ImportFrom):
            continue
        module = node.module or ""
        is_canonical = (node.level == 0 and module == canonical_module) or (
            node.level > 0 and module.rsplit(".", 1)[-1] == tail
        )
        if not is_canonical:
            continue
        for alias in node.names:
            if alias.name == symbol:
                aliases.add(alias.asname or alias.name)
    return aliases


def _guard_import_aliases(tree: ast.Module, symbol: str) -> set[str]:
    """Names bound by ``from X import <symbol> [as alias]`` for any module X.

    Re-exporting packages are accepted deliberately: the canonical module check
    for *definitions* is separate (see :func:`scan_file`).
    """
    aliases: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            for alias in node.names:
                if alias.name == symbol:
                    aliases.add(alias.asname or alias.name)
    return aliases


def _calls_any(tree: ast.AST, names: set[str]) -> bool:
    """Whether any call in ``tree`` targets one of ``names`` (name or attribute)."""
    if not names:
        return False
    return any(isinstance(node, ast.Call) and _call_name(node) in names for node in ast.walk(tree))


def scan_file(source: str, rel_path: str, config: BindGuardConfig) -> list[Finding]:
    """Lint one file's source against the bind-guard policy.

    Pure (no filesystem access), so tests can drive it with synthetic sources.
    """
    symbol = config.required_symbol
    canonical = config.canonical_module
    try:
        tree = ast.parse(source, filename=rel_path)
    except SyntaxError as exc:
        return [
            Finding(
                rel_path,
                exc.lineno or 1,
                "syntax-error",
                f"cannot parse file for bind-guard analysis: {exc.msg}",
            )
        ]

    findings: list[Finding] = []
    module = _module_name(rel_path)
    canonical_aliases = _canonical_aliases(tree, symbol, canonical)

    # Single-primitive rule: def <symbol> outside the canonical module must be a
    # delegating adapter (imports the canonical symbol and its body calls it).
    if module != canonical:
        for node in ast.walk(tree):
            if not isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
                continue
            if node.name != symbol:
                continue
            delegating_aliases = canonical_aliases - {node.name}
            body_tree = ast.Module(body=node.body, type_ignores=[])
            if _calls_any(body_tree, delegating_aliases):
                continue  # adapter delegating to the canonical primitive: clean
            findings.append(
                Finding(
                    rel_path,
                    node.lineno,
                    f"def {symbol}",
                    f"re-definition of {symbol!r} outside canonical module {canonical!r} "
                    f"without delegating to it violates the single-primitive rule",
                )
            )

    # Listener rule: a triggering file must import-and-call the symbol, or be a
    # declared exception in the governance config.
    triggers = [
        (node.lineno, name)
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and (name := _call_name(node)) in LISTENER_TRIGGERS
    ]
    if triggers:
        exception_paths = {entry.path for entry in config.exceptions}
        guard_aliases = _guard_import_aliases(tree, symbol)
        guarded = _calls_any(tree, guard_aliases)
        if not guarded and rel_path not in exception_paths and module != canonical:
            findings.extend(
                Finding(
                    rel_path,
                    line,
                    name,
                    f"network-listener call {name!r} without a {symbol!r} guard "
                    f"(import it from {canonical!r} and call it, or declare an "
                    f"exception in {CLAUDE_DIR_NAME}/{GOVERNANCE_FILENAME})",
                )
                for line, name in triggers
            )
    return findings


def iter_scan_files(repo_root: Path) -> list[Path]:
    """The de-duplicated, sorted set of files selected by :data:`SCAN_GLOBS`.

    Excludes tools/**/tests/** and tools/claude_hooks/bind_guard.py itself
    (which redefines LISTENER_TRIGGERS and has fixture patterns).
    """
    files: set[Path] = set()
    for pattern in SCAN_GLOBS:
        files.update(p for p in repo_root.glob(pattern) if p.is_file())

    # Exclude test files and the linter itself
    excluded = {
        repo_root / "tools/claude_hooks/bind_guard.py",
    }
    for test_pattern in (repo_root / "tools").glob("**/tests/**/*.py"):
        excluded.add(test_pattern)

    return sorted(files - excluded)


def scan_repo(repo_root: Path, config: BindGuardConfig) -> tuple[list[Finding], int]:
    """Scan every selected file under ``repo_root``; returns (findings, files scanned)."""
    findings: list[Finding] = []
    files = iter_scan_files(repo_root)
    for path in files:
        rel_path = path.relative_to(repo_root).as_posix()
        source = path.read_text(encoding="utf-8", errors="replace")
        findings.extend(scan_file(source, rel_path, config))
    return findings, len(files)


def main(argv: list[str] | None = None) -> int:
    """CLI entry point; exits 1 on any violation, 0 when clean."""
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
        print(f"bind guard: {exc}", file=sys.stderr)
        return 1
    findings, scanned = scan_repo(repo_root, config.bind_guard)
    for finding in findings:
        print(finding.render())
    if findings:
        print(f"bind guard: {len(findings)} violation(s) across {scanned} scanned file(s)")
        return 1
    print(f"bind guard: clean ({scanned} file(s) scanned)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
