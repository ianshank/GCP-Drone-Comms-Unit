"""literal_guard tests: rule behavior on synthetic sources, exception scoping, CLI."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from tools.claude_hooks.governance import (
    GovernanceConfigError,
    LiteralGuardConfig,
    load_governance,
)
from tools.claude_hooks.literal_guard import (
    Finding,
    iter_scan_files,
    load_port_table,
    main,
    scan_file,
    scan_repo,
    split_findings,
)
from tools.claude_hooks.tests.helpers import governance_dict, write_governance

DEFAULTS_SOURCE = """\
PORT_FTS_TCP = 8087
PORT_TAK_TLS = 8089
PORT_UI = 8100
DEFAULT_QUEUE_MAXSIZE = 1000
NOT_A_PORT = "8087"
"""

PORTS = frozenset({8087, 8089, 8100})


def literal_guard_dict(**overrides: object) -> dict[str, object]:
    data: dict[str, object] = {
        "defaults_module": "packages/meshsa/src/meshsa/defaults.py",
        "exceptions": [],
    }
    data.update(overrides)
    return data


class TestPortTable:
    def test_derives_port_star_int_assignments_only(self) -> None:
        assert load_port_table(DEFAULTS_SOURCE, "defaults.py") == PORTS

    def test_refuses_empty_port_set(self) -> None:
        with pytest.raises(GovernanceConfigError, match="no PORT_"):
            load_port_table("X = 1\n", "defaults.py")


class TestPortsRule:
    def test_flags_port_value_anywhere(self) -> None:
        findings = scan_file("port: int = 8100\n", "a.py", PORTS)
        assert [(f.rule, f.line) for f in findings] == [("ports", 1)]

    def test_ignores_non_table_ints_and_bools(self) -> None:
        assert scan_file("x = 8098\ny = True\nz = 1\n", "a.py", PORTS) == []

    def test_ignores_port_valued_string(self) -> None:
        assert scan_file('x = "8100"\n', "a.py", PORTS) == []


class TestHostsRule:
    def test_flags_exact_loopback_and_any_interface(self) -> None:
        source = 'host = "127.0.0.1"\niface = "0.0.0.0"\n'
        findings = scan_file(source, "a.py", PORTS)
        assert [f.rule for f in findings] == ["hosts", "hosts"]

    def test_never_matches_substrings_in_prose(self) -> None:
        # Operator-remedy messages and docstrings contain addresses mid-string; the
        # rule is exact equality so they never fire (frozen files stay unpressured).
        source = 'msg = "set MESHSA_UI_TOKEN or bind to 127.0.0.1 instead"\n'
        assert scan_file(source, "a.py", PORTS) == []

    def test_never_matches_fstring_fragments(self) -> None:
        source = 'url = f"http://127.0.0.1:{port}/healthz"\n'
        assert scan_file(source, "a.py", PORTS) == []


class TestEndpointsRule:
    def test_flags_full_endpoint_literals(self) -> None:
        source = 'ep = "udpin:127.0.0.1:14550"\nout = "udpout:10.0.0.2:14550"\n'
        findings = scan_file(source, "a.py", PORTS)
        assert [f.rule for f in findings] == ["endpoints", "endpoints"]

    def test_ignores_bare_prefixes_and_mid_string_mentions(self) -> None:
        # The prefix-stripping tuple in mavlink_source.py and prose mentioning an
        # endpoint mid-sentence must not fire (anchored regex, remainder required).
        source = (
            '_PREFIXES = ("udpin:", "udpout:", "tcpin:", "tcpout:")\n'
            'doc = "pass e.g. udpin:0.0.0.0:14550 here"\n'
        )
        assert scan_file(source, "a.py", PORTS) == []


class TestMagicsRule:
    def test_flags_signature_call_and_field_defaults(self) -> None:
        source = (
            "def f(queue_maxsize: int = 1000): ...\n"
            "def g(*, backoff_max_s: float = 30.0): ...\n"
            "q = Queue(queue_maxsize=500)\n"
            "class C:\n"
            "    backoff_factor: float = 2.0\n"
            "backoff_initial_s = 1.0\n"
        )
        findings = scan_file(source, "a.py", PORTS)
        assert [f.rule for f in findings] == ["magics"] * 5

    def test_name_keyed_not_value_keyed(self) -> None:
        # The same numbers under other names (geometry offsets, ms conversions,
        # unrelated poll intervals) must not fire.
        source = (
            "gps_altitude_offset_m = 1000\n"
            "poll_interval_s: float = 2.0\n"
            "def f(timeout_s: float = 30.0): ...\n"
            "ms = seconds * 1000\n"
        )
        assert scan_file(source, "a.py", PORTS) == []

    def test_symbolic_defaults_are_clean(self) -> None:
        # Post-sweep shape: names sourced from the defaults module never fire.
        source = "def f(queue_maxsize: int = DEFAULT_QUEUE_MAXSIZE): ...\n"
        assert scan_file(source, "a.py", PORTS) == []


class TestSyntaxError:
    def test_unparsable_file_is_a_finding(self) -> None:
        findings = scan_file("def broken(:\n", "a.py", PORTS)
        assert [f.rule for f in findings] == ["syntax-error"]


class TestExceptionScoping:
    def _findings(self) -> list[Finding]:
        return [
            Finding("a.py", 1, "ports", "m"),
            Finding("a.py", 2, "hosts", "m"),
            Finding("b.py", 3, "endpoints", "m"),
        ]

    def test_rule_scoped_exception_waives_only_that_rule(self) -> None:
        config = LiteralGuardConfig.model_validate(
            literal_guard_dict(exceptions=[{"path": "a.py", "rule": "ports", "rationale": "r"}])
        )
        violations, excepted = split_findings(self._findings(), config)
        assert [(f.rel_path, f.rule) for f in excepted] == [("a.py", "ports")]
        assert [(f.rel_path, f.rule) for f in violations] == [
            ("a.py", "hosts"),
            ("b.py", "endpoints"),
        ]

    def test_star_exception_waives_every_rule_for_one_file(self) -> None:
        config = LiteralGuardConfig.model_validate(
            literal_guard_dict(exceptions=[{"path": "a.py", "rule": "*", "rationale": "r"}])
        )
        violations, excepted = split_findings(self._findings(), config)
        assert {f.rel_path for f in excepted} == {"a.py"}
        assert [f.rel_path for f in violations] == ["b.py"]


def _write_repo(tmp_path: Path, sources: dict[str, str]) -> Path:
    (tmp_path / "packages/meshsa/src/meshsa").mkdir(parents=True)
    (tmp_path / "packages/meshsa/src/meshsa/defaults.py").write_text(
        DEFAULTS_SOURCE, encoding="utf-8"
    )
    for rel, text in sources.items():
        target = tmp_path / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding="utf-8")
    return tmp_path


class TestScanRepo:
    def test_defaults_module_is_excluded_and_flightctl_recursed(self, tmp_path: Path) -> None:
        _write_repo(
            tmp_path,
            {
                "packages/meshsa/src/meshsa/a.py": "p = 8100\n",
                "flightctl/sim/fake.py": 'ep = "udpout:127.0.0.1:14550"\n',
            },
        )
        config = LiteralGuardConfig.model_validate(literal_guard_dict())
        violations, excepted, scanned = scan_repo(tmp_path, config)
        assert scanned == 2  # defaults.py itself is not scanned
        assert {(f.rel_path, f.rule) for f in violations} == {
            ("packages/meshsa/src/meshsa/a.py", "ports"),
            ("flightctl/sim/fake.py", "endpoints"),
        }
        assert excepted == []

    def test_missing_defaults_module_is_a_clean_error(self, tmp_path: Path) -> None:
        config = LiteralGuardConfig.model_validate(
            literal_guard_dict(defaults_module="nope/defaults.py")
        )
        with pytest.raises(GovernanceConfigError, match="defaults module not found"):
            scan_repo(tmp_path, config)

    def test_iter_scan_files_sorted_unique(self, tmp_path: Path) -> None:
        _write_repo(tmp_path, {"packages/meshsa/src/meshsa/a.py": "x = 1\n"})
        config = LiteralGuardConfig.model_validate(literal_guard_dict())
        files = iter_scan_files(tmp_path, config)
        assert files == sorted(set(files))
        assert tmp_path / config.defaults_module not in files


class TestMain:
    def test_clean_repo_exits_zero(self, tmp_path: Path) -> None:
        _write_repo(tmp_path, {"packages/meshsa/src/meshsa/a.py": "x = 1\n"})
        write_governance(tmp_path, literal_guard=literal_guard_dict())
        assert main(["--repo-root", str(tmp_path)]) == 0

    def test_violation_exits_one(self, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
        _write_repo(tmp_path, {"packages/meshsa/src/meshsa/a.py": "p = 8087\n"})
        write_governance(tmp_path, literal_guard=literal_guard_dict())
        assert main(["--repo-root", str(tmp_path)]) == 1
        assert "[ports]" in capsys.readouterr().out

    def test_excepted_finding_exits_zero(self, tmp_path: Path) -> None:
        _write_repo(tmp_path, {"packages/meshsa/src/meshsa/a.py": "p = 8087\n"})
        write_governance(
            tmp_path,
            literal_guard=literal_guard_dict(
                exceptions=[
                    {
                        "path": "packages/meshsa/src/meshsa/a.py",
                        "rule": "ports",
                        "rationale": "r",
                    }
                ]
            ),
        )
        assert main(["--repo-root", str(tmp_path)]) == 0

    def test_missing_section_exits_one(self, tmp_path: Path) -> None:
        _write_repo(tmp_path, {})
        write_governance(tmp_path)  # no literal_guard key
        assert main(["--repo-root", str(tmp_path)]) == 1

    def test_missing_config_exits_one(self, tmp_path: Path) -> None:
        assert main(["--repo-root", str(tmp_path)]) == 1


class TestLoaderIntegration:
    def test_literal_guard_section_loads(self, tmp_path: Path) -> None:
        config_path = write_governance(
            tmp_path,
            literal_guard=literal_guard_dict(
                exceptions=[{"path": "a.py", "rule": "*", "rationale": "frozen"}]
            ),
        )
        config = load_governance(config_path)
        assert config.literal_guard is not None
        assert config.literal_guard.exceptions[0].rule == "*"

    def test_absent_section_defaults_to_none(self, tmp_path: Path) -> None:
        # Rollout safety: the scope-freeze hook fails open on invalid config, so the
        # section must be optional — old yaml + new loader stays valid.
        config = load_governance(write_governance(tmp_path))
        assert config.literal_guard is None

    def test_unknown_literal_guard_key_rejected(self, tmp_path: Path) -> None:
        config_path = write_governance(
            tmp_path, literal_guard=literal_guard_dict(escape_hatch=True)
        )
        with pytest.raises(GovernanceConfigError, match="escape_hatch"):
            load_governance(config_path)

    def test_exception_missing_rule_rejected(self, tmp_path: Path) -> None:
        config_path = write_governance(
            tmp_path,
            literal_guard=literal_guard_dict(
                exceptions=[{"path": "a.py", "rationale": "no rule key"}]
            ),
        )
        with pytest.raises(GovernanceConfigError, match="rule"):
            load_governance(config_path)

    def test_real_repo_governance_config_is_valid(self) -> None:
        # The checked-in .claude/governance.yaml must always satisfy the loader —
        # the scope-freeze hook fails open when it cannot validate this file.
        repo_root = Path(__file__).resolve().parents[3]
        config = load_governance(repo_root / ".claude" / "governance.yaml")
        assert config.literal_guard is not None
        rules = {e.rule for e in config.literal_guard.exceptions}
        assert rules <= {"ports", "hosts", "magics", "endpoints", "*"}


def test_governance_dict_helper_still_omits_literal_guard() -> None:
    # Guard against helpers.py silently adding the key: several loader tests rely on
    # "absent means None".
    assert "literal_guard" not in governance_dict()


def test_yaml_roundtrip_of_exception_entries(tmp_path: Path) -> None:
    entries = [{"path": "a.py", "rule": "hosts", "rationale": "consumer of the set"}]
    config_path = write_governance(tmp_path, literal_guard=literal_guard_dict(exceptions=entries))
    raw = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    assert raw["literal_guard"]["exceptions"] == entries
