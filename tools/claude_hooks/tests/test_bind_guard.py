"""bind_guard linter tests on synthetic sources and tmp_path trees.

Deliberately independent of the current repo state: the two known in-repo
violations are being fixed in a parallel workstream, so every case here builds
its own fixture files.
"""

from __future__ import annotations

import subprocess
import sys
import textwrap
from pathlib import Path

from tools.claude_hooks.bind_guard import (
    LISTENER_TRIGGERS,
    SCAN_GLOBS,
    iter_scan_files,
    main,
    scan_file,
    scan_repo,
)
from tools.claude_hooks.governance import BindGuardConfig, BindGuardExceptionEntry
from tools.claude_hooks.tests.helpers import write_governance

TRANSPORT_REL_PATH = "packages/meshsa/src/meshsa/transports/udp_ingest.py"

LISTENER_NO_GUARD = textwrap.dedent(
    """
    import socket

    def start(host: str, port: int) -> socket.socket:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.bind((host, port))
        return sock
    """
)

LISTENER_WITH_GUARD = textwrap.dedent(
    """
    import socket

    from meshsa.netauth import validate_bind

    def start(host: str, port: int, token: str | None) -> socket.socket:
        validate_bind(host, token, service="udp-ingest", remedy="set TOKEN")
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.bind((host, port))
        return sock
    """
)

LISTENER_GUARD_IMPORTED_NOT_CALLED = textwrap.dedent(
    """
    import socket

    from meshsa.netauth import validate_bind  # imported for looks only

    def start(host: str, port: int) -> socket.socket:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.bind((host, port))
        return sock
    """
)

LISTENER_WITH_REEXPORTED_GUARD = textwrap.dedent(
    """
    import asyncio

    from meshsa.llm.server import validate_bind

    async def serve(host: str, port: int, token: str | None) -> None:
        validate_bind(host, token, service="svc", remedy="set TOKEN")
        loop = asyncio.get_running_loop()
        await loop.create_datagram_endpoint(lambda: None, local_addr=(host, port))
    """
)

LOCAL_REDEFINITION = textwrap.dedent(
    """
    def validate_bind(host: str, token: str | None) -> None:
        if host != "127.0.0.1" and not token:
            raise SystemExit("refusing to bind")
    """
)

DELEGATING_ADAPTER = textwrap.dedent(
    """
    from ..netauth import validate_bind as _validate_bind

    def validate_bind(host: str, token: str | None) -> None:
        _validate_bind(host, token, service="llm", remedy="set MESHSA_LLM_TOKEN")
    """
)

NON_DELEGATING_WITH_IMPORT = textwrap.dedent(
    """
    from meshsa.netauth import validate_bind as _validate_bind

    def validate_bind(host: str, token: str | None) -> None:
        # imports the canonical primitive but re-implements it instead of calling it
        if host != "127.0.0.1" and not token:
            raise SystemExit("refusing to bind")
    """
)


def _config(exceptions: list[BindGuardExceptionEntry] | None = None) -> BindGuardConfig:
    return BindGuardConfig(
        required_symbol="validate_bind",
        canonical_module="meshsa.netauth",
        exceptions=exceptions or [],
    )


class TestScanFile:
    def test_listener_without_guard_is_violation(self) -> None:
        findings = scan_file(LISTENER_NO_GUARD, TRANSPORT_REL_PATH, _config())
        assert len(findings) == 1
        assert findings[0].trigger == "bind"
        assert findings[0].rel_path == TRANSPORT_REL_PATH
        assert "validate_bind" in findings[0].message

    def test_listener_with_guard_import_and_call_is_clean(self) -> None:
        assert scan_file(LISTENER_WITH_GUARD, TRANSPORT_REL_PATH, _config()) == []

    def test_guard_import_without_call_is_violation(self) -> None:
        findings = scan_file(LISTENER_GUARD_IMPORTED_NOT_CALLED, TRANSPORT_REL_PATH, _config())
        assert [f.trigger for f in findings] == ["bind"]

    def test_reexported_guard_import_is_accepted(self) -> None:
        assert scan_file(LISTENER_WITH_REEXPORTED_GUARD, TRANSPORT_REL_PATH, _config()) == []

    def test_declared_exception_is_clean(self) -> None:
        config = _config(
            [BindGuardExceptionEntry(path=TRANSPORT_REL_PATH, rationale="multicast protocol")]
        )
        assert scan_file(LISTENER_NO_GUARD, TRANSPORT_REL_PATH, config) == []

    def test_exception_covers_only_its_path(self) -> None:
        config = _config([BindGuardExceptionEntry(path="somewhere/else.py", rationale="n/a")])
        assert scan_file(LISTENER_NO_GUARD, TRANSPORT_REL_PATH, config)

    def test_each_configured_trigger_name_fires(self) -> None:
        for trigger in sorted(LISTENER_TRIGGERS):
            source = f"import x\nx.{trigger}('arg')\n"
            findings = scan_file(source, TRANSPORT_REL_PATH, _config())
            assert [f.trigger for f in findings] == [trigger]


class TestRedefinitionRule:
    def test_local_redefinition_is_violation(self) -> None:
        findings = scan_file(LOCAL_REDEFINITION, "flightctl/run_commander.py", _config())
        assert len(findings) == 1
        assert findings[0].trigger == "def validate_bind"
        assert "single-primitive" in findings[0].message

    def test_redefinition_flagged_without_any_listener_trigger(self) -> None:
        findings = scan_file(LOCAL_REDEFINITION, "packages/meshsa/src/meshsa/util.py", _config())
        assert len(findings) == 1
        assert findings[0].trigger == "def validate_bind"

    def test_definition_in_canonical_module_is_clean(self) -> None:
        source = "def validate_bind(host, token, *, service, remedy):\n    pass\n"
        assert scan_file(source, "packages/meshsa/src/meshsa/netauth.py", _config()) == []

    def test_delegating_adapter_is_clean(self) -> None:
        # e.g. meshsa/llm/server.py: wrapper importing the canonical primitive
        # (relative import) and delegating to it.
        assert (
            scan_file(DELEGATING_ADAPTER, "packages/meshsa/src/meshsa/llm/server.py", _config())
            == []
        )

    def test_non_delegating_redefinition_with_import_is_violation(self) -> None:
        findings = scan_file(
            NON_DELEGATING_WITH_IMPORT, "packages/meshsa/src/meshsa/llm/server.py", _config()
        )
        assert [f.trigger for f in findings] == ["def validate_bind"]


def _make_tree(repo_root: Path, files: dict[str, str]) -> None:
    for rel_path, source in files.items():
        target = repo_root / rel_path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(source, encoding="utf-8")


class TestScanRepo:
    def test_scan_globs_cover_packages_and_flightctl(self, tmp_path: Path) -> None:
        _make_tree(
            tmp_path,
            {
                TRANSPORT_REL_PATH: LISTENER_NO_GUARD,
                "flightctl/run_commander.py": LOCAL_REDEFINITION,
                "docs/example.py": LISTENER_NO_GUARD,  # outside the scan globs
            },
        )
        findings, scanned = scan_repo(tmp_path, _config())
        assert scanned == 2
        assert {f.rel_path for f in findings} == {
            TRANSPORT_REL_PATH,
            "flightctl/run_commander.py",
        }

    def test_clean_tree_no_findings(self, tmp_path: Path) -> None:
        _make_tree(tmp_path, {TRANSPORT_REL_PATH: LISTENER_WITH_GUARD})
        findings, scanned = scan_repo(tmp_path, _config())
        assert findings == []
        assert scanned == 1

    def test_scan_globs_cover_tools(self, tmp_path: Path) -> None:
        # T-2.4: tools/**/*.py joined the scan scope.
        _make_tree(tmp_path, {"tools/claude_hooks/some_hook.py": LISTENER_NO_GUARD})
        findings, scanned = scan_repo(tmp_path, _config())
        assert scanned == 1
        assert {f.rel_path for f in findings} == {"tools/claude_hooks/some_hook.py"}

    def test_scan_skips_tools_tests_dir(self, tmp_path: Path) -> None:
        # T-2.4: tools/**/tests/** is excluded so the linter's own fixtures
        # (which deliberately contain unguarded bind() calls) never self-flag.
        _make_tree(
            tmp_path,
            {
                "tools/claude_hooks/tests/test_fixture.py": LISTENER_NO_GUARD,
                "tools/claude_hooks/real_hook.py": LISTENER_WITH_GUARD,
            },
        )
        findings, scanned = scan_repo(tmp_path, _config())
        assert scanned == 1
        assert findings == []

    def test_scan_skips_bind_guard_itself(self, tmp_path: Path) -> None:
        # T-2.4: tools/claude_hooks/bind_guard.py is excluded by name — it
        # redefines LISTENER_TRIGGERS/validate_bind-adjacent fixture text.
        _make_tree(tmp_path, {"tools/claude_hooks/bind_guard.py": LISTENER_NO_GUARD})
        findings, scanned = scan_repo(tmp_path, _config())
        assert scanned == 0
        assert findings == []


class TestIterScanFiles:
    def test_includes_tools_glob(self, tmp_path: Path) -> None:
        assert "tools/**/*.py" in SCAN_GLOBS
        _make_tree(tmp_path, {"tools/claude_hooks/some_hook.py": LISTENER_NO_GUARD})
        found = {p.relative_to(tmp_path).as_posix() for p in iter_scan_files(tmp_path)}
        assert found == {"tools/claude_hooks/some_hook.py"}

    def test_excludes_any_depth_tests_dir(self, tmp_path: Path) -> None:
        _make_tree(
            tmp_path,
            {
                "tools/a/tests/test_x.py": LISTENER_NO_GUARD,
                "tools/a/b/tests/test_y.py": LISTENER_NO_GUARD,
                "tools/a/real.py": LISTENER_WITH_GUARD,
            },
        )
        found = {p.relative_to(tmp_path).as_posix() for p in iter_scan_files(tmp_path)}
        assert found == {"tools/a/real.py"}

    def test_excludes_bind_guard_module_only(self, tmp_path: Path) -> None:
        _make_tree(
            tmp_path,
            {
                "tools/claude_hooks/bind_guard.py": LISTENER_NO_GUARD,
                "tools/claude_hooks/governance.py": LISTENER_WITH_GUARD,
            },
        )
        found = {p.relative_to(tmp_path).as_posix() for p in iter_scan_files(tmp_path)}
        assert found == {"tools/claude_hooks/governance.py"}


class TestCli:
    def test_clean_tree_exits_zero(self, tmp_path: Path) -> None:
        write_governance(tmp_path)
        _make_tree(tmp_path, {TRANSPORT_REL_PATH: LISTENER_WITH_GUARD})
        assert main(["--repo-root", str(tmp_path)]) == 0

    def test_violation_exits_one(self, tmp_path: Path) -> None:
        write_governance(tmp_path)
        _make_tree(tmp_path, {TRANSPORT_REL_PATH: LISTENER_NO_GUARD})
        assert main(["--repo-root", str(tmp_path)]) == 1

    def test_missing_config_exits_one(self, tmp_path: Path) -> None:
        assert main(["--repo-root", str(tmp_path)]) == 1

    def test_script_execution_mode(self, tmp_path: Path) -> None:
        # Run the file directly (as CI does) so the script-mode import fallback
        # and the exit code are exercised end to end.
        write_governance(tmp_path)
        _make_tree(tmp_path, {TRANSPORT_REL_PATH: LISTENER_NO_GUARD})
        script = Path(__file__).resolve().parents[1] / "bind_guard.py"
        result = subprocess.run(
            [sys.executable, str(script), "--repo-root", str(tmp_path)],
            capture_output=True,
            text=True,
            timeout=60,
            check=False,
        )
        assert result.returncode == 1
        assert TRANSPORT_REL_PATH in result.stdout
        assert "bind" in result.stdout
