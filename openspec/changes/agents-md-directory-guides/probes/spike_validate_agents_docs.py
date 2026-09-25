#!/usr/bin/env python3
"""SPIKE for tools/validate_agents_docs.py — feasibility probe, not the deliverable.

Implements the rev.2 check set closely enough to answer one question: does the
authoring contract survive contact with real files? Run against the five existing
guides and a probe guide written to the contract.
"""

from __future__ import annotations

import json
import re
import sys
import unicodedata
from pathlib import Path

ROOT = Path(__file__).resolve()
while not (ROOT / ".git").exists():
    ROOT = ROOT.parent
    if ROOT.parent == ROOT:
        ROOT = Path("/home/user/GCP-Drone-Comms-Unit")
        break

# --- policy ---------------------------------------------------------------
TIER_SECTIONS = {
    0: ["Purpose", "Traps", "Rules", "Commands", "Subagents"],
    1: ["Purpose", "Traps", "Rules", "Subagents"],
    2: ["Traps", "Rules", "Subagents"],
    3: ["Purpose", "Rules"],
}
OPTIONAL = {0: {"Map"}, 1: {"Commands", "Map"}, 2: {"Commands", "Map"}, 3: set()}
CANONICAL = ["Purpose", "Traps", "Rules", "Commands", "Subagents", "Map"]
BUDGET = {0: 170, 1: 80, 2: 60, 3: 12}
FENCE_BODY_MAX = 22
ALLOWED_DIAGRAMS = ("flowchart", "sequenceDiagram")

PREFIXES = (
    "packages/",
    "docs/",
    "openspec/",
    "flightctl/",
    "tools/",
    "ops/",
    ".claude/",
    ".agents/",
    ".github/",
    "hardware/",
    "deliverables/",
    "archive/",
    "lib/",
    "artifacts/",
    "scripts/",
)
ROOT_FILES = {
    "AGENTS.md",
    "CLAUDE.md",
    "README.md",
    "CHANGELOG.md",
    "CONTRIBUTING.md",
    "NEXTSTEPS.md",
    "SECURITY.md",
    "Makefile",
    "mypy.ini",
    "ruff.toml",
    "package.json",
    "pnpm-workspace.yaml",
    ".gitignore",
    ".pre-commit-config.yaml",
    "eslint.config.js",
    "tsconfig.json",
}
PLACEHOLDER = set("<>*{}")
ACTION_DIRECTIVE = re.compile(
    r"\b(?:run|execute|call|invoke)\s+(?:the\s+)?(?:bash|sh|shell|command)\b"
    r"|\bbash\s+\S+\.sh\b|\bcurl\s+http",
    re.I,
)


def sections_of(lines: list[str]) -> list[tuple[str, int]]:
    out, in_fence = [], False
    for i, ln in enumerate(lines):
        if ln.lstrip().startswith("```"):
            in_fence = not in_fence
        if not in_fence and ln.startswith("## "):
            out.append((ln[3:].strip(), i))
    return out


def fences(lines: list[str]) -> list[tuple[int, int, str]]:
    out, start, info = [], None, ""
    for i, ln in enumerate(lines):
        if ln.lstrip().startswith("```"):
            if start is None:
                start, info = i, ln.strip().strip("`").strip()
            else:
                out.append((start, i, info))
                start = None
    return out


def make_targets(path: Path) -> set[str]:
    pat = re.compile(r"^([A-Za-z0-9_.-]+)\s*:")
    return {
        m.group(1)
        for ln in path.read_text().splitlines()
        if (m := pat.match(ln)) and not ln.startswith("\t")
    }


def pnpm_scripts() -> dict[str, set[str]]:
    out = {}
    for pj in ROOT.rglob("package.json"):
        if "node_modules" in pj.parts:
            continue
        try:
            d = json.loads(pj.read_text())
        except Exception:
            continue
        if "name" in d:
            out[d["name"]] = set(d.get("scripts", {}))
    return out


def cited_paths(text: str, base: Path) -> list[tuple[str, bool]]:
    toks = set(re.findall(r"`([^`\n]+)`", text))
    toks |= set(re.findall(r"\]\(([^)\s]+)\)", text))
    res = []
    for raw in toks:
        t = raw.strip().strip("\"'(),;:")
        t = t.split("::")[0].split("#")[0]
        t = re.sub(r"\[[^\]]*\]$", "", t)  # strip pip extras
        if not t or " " in t or PLACEHOLDER & set(t):
            continue
        if t.startswith(("http://", "https://", "@")):
            continue
        looks = (
            t.startswith(PREFIXES)
            or t in ROOT_FILES
            or t.startswith((".", "../"))
            or ("/" in t and not t.startswith("-"))
        )
        if not looks:
            continue
        ok = (base / t).exists() or (ROOT / t).exists()
        res.append((t, ok))
    return res


def norm(s: str) -> str:
    s = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", s)
    s = s.replace("`", "").lower()
    s = re.sub(r"—\s*why:.*$", "", s)
    s = re.sub(r"—\s*control:.*$", "", s)
    s = re.sub(r"[^a-z0-9 ]+", " ", s)
    return " ".join(s.split())


def root_rules() -> set[str]:
    lines = (ROOT / "AGENTS.md").read_text().splitlines()
    secs = sections_of(lines)
    for name, i in secs:
        if "Rule" in name:
            end = next((j for n, j in secs if j > i), len(lines))
            return {
                norm(line)
                for line in lines[i:end]
                if line.startswith("- ") and len(norm(line)) > 12
            }
    return set()


def check(path: Path, tier: int, rootset: set[str]) -> list[str]:
    f = []
    text = path.read_text()
    lines = text.splitlines()
    base = path.parent

    # 3 budget
    if len(lines) > BUDGET[tier]:
        f.append(f"[3 budget] {len(lines)} lines > {BUDGET[tier]} (tier {tier})")

    # 2 sections
    names = [n for n, _ in sections_of(lines)]
    req = TIER_SECTIONS[tier]
    missing = [r for r in req if r not in names]
    if missing:
        f.append(f"[2 sections] missing required: {missing}")
    unknown = [n for n in names if n not in CANONICAL]
    if unknown:
        f.append(f"[2 sections] non-canonical section(s): {unknown}")
    known = [n for n in names if n in CANONICAL]
    if known != sorted(known, key=CANONICAL.index):
        f.append(f"[2 order] {known} not in canonical order")

    # rationale on rules
    secs = sections_of(lines)
    for name, i in secs:
        if name == "Rules":
            end = next((j for n, j in secs if j > i), len(lines))
            body = lines[i + 1 : end]
            bullets, cur = [], ""
            for line in body:
                if line.startswith("- "):
                    if cur:
                        bullets.append(cur)
                    cur = line
                elif cur and line.strip():
                    cur += " " + line.strip()
            if cur:
                bullets.append(cur)
            for b in bullets:
                if "why:" not in b:
                    f.append(f"[rationale] rule without why: {b[:58]}...")
            # 10 duplicate vs root
            for b in bullets:
                if tier != 3 and norm(b) in rootset:
                    f.append(f"[10 dup] exact duplicate of a root rule: {b[:48]}...")

    # 5 citations
    for t, ok in cited_paths(text, base):
        if not ok:
            f.append(f"[5 path] cited path does not resolve: {t}")

    # 6 diagrams
    fs = [x for x in fences(lines) if x[2].startswith("mermaid")]
    if tier == 3 and fs:
        f.append("[6 diagram] tier 3 must be prose-only")
    if len(fs) > 1:
        f.append(f"[6 diagram] {len(fs)} diagrams; at most 1 allowed")
    for s, e, _ in fs:
        body = lines[s + 1 : e]
        if not any(line.strip().startswith("accTitle") for line in body):
            f.append("[6 diagram] missing accTitle")
        if not any(line.strip().startswith("accDescr") for line in body):
            f.append("[6 diagram] missing accDescr")
        if len(body) > FENCE_BODY_MAX:
            f.append(f"[6 diagram] fence body {len(body)} > {FENCE_BODY_MAX}")
        if not any(body[0].strip().startswith(d) for d in ALLOWED_DIAGRAMS):
            f.append(f"[6 diagram] disallowed type: {body[0].strip()[:30]}")
        nxt = next((line for line in lines[e + 1 :] if line.strip()), "")
        if nxt[:3] in ("## ", "###") or nxt.startswith(("```", "|", "- ", "* ")):
            f.append("[6 diagram] no prose summary after fence")

    # 8 commands
    roott = make_targets(ROOT / "Makefile")
    toolt = make_targets(ROOT / "tools" / "Makefile")
    scripts = pnpm_scripts()
    for m in re.finditer(r"\bmake\b([^\n`]*)", text):
        toks = m.group(1).split()
        use, i = roott, 0
        while i < len(toks):
            if toks[i] == "-f":
                use = toolt if "tools/Makefile" in toks[i + 1] else roott
                i += 2
                continue
            if toks[i].startswith("-") or "=" in toks[i]:
                i += 1
                continue
            if toks[i] not in use:
                f.append(
                    f"[8 make] target not in {'tools/' if use is toolt else 'root '}Makefile: {toks[i]}"
                )
            i += 1
    for m in re.finditer(r"pnpm --filter (\S+) run (\S+)", text):
        pkg, scr = m.group(1).strip("'\""), m.group(2)
        if pkg in scripts and scr not in scripts[pkg]:
            f.append(f"[8 pnpm] {pkg} has no script {scr}")
    if re.search(r"\bnpm run\b", text):
        f.append("[8 npm] npm run is rejected by the repo preinstall guard")

    # 7 subagents
    names_idx = {p.stem for p in (ROOT / ".claude/agents").glob("*.md")}
    names_idx |= {p.parent.name for p in (ROOT / ".agents/skills").glob("*/SKILL.md")}
    names_idx |= {
        p.name.replace(".agent.md", "") for p in (ROOT / ".github/agents").glob("*.agent.md")
    }
    for name, i in secs:
        if name == "Subagents":
            end = next((j for n, j in secs if j > i), len(lines))
            for line in lines[i:end]:
                if line.startswith("- "):
                    m = re.search(r"`([^`]+)`", line)
                    if not m:
                        f.append(f"[7 subagent] bullet has no backtick name: {line[:44]}...")
                    elif m.group(1) not in names_idx:
                        f.append(f"[7 subagent] unresolved: {m.group(1)}")

    # 11 action directives outside Commands
    cmd_range = None
    for name, i in secs:
        if name == "Commands":
            cmd_range = (i, next((j for n, j in secs if j > i), len(lines)))
    for i, line in enumerate(lines):
        if cmd_range and cmd_range[0] <= i < cmd_range[1]:
            continue
        if ACTION_DIRECTIVE.search(line):
            f.append(
                f"[11 directive] action directive outside Commands (L{i + 1}): {line.strip()[:52]}"
            )

    # 13 unicode
    for i, ch in enumerate(text):
        if ch in "​‌‍‪‫‭‮⁦⁧⁨":
            f.append(f"[13 unicode] control char {unicodedata.name(ch, hex(ord(ch)))} at {i}")
            break
    return f


TARGETS = [
    (ROOT / "AGENTS.md", 0),
    (ROOT / "packages/meshsa/AGENTS.md", 1),
    (ROOT / "packages/jetson_yolo_gcs/AGENTS.md", 1),
    (ROOT / "ops/AGENTS.md", 1),
    (ROOT / "hardware/AGENTS.md", 1),
]
probe = Path(sys.argv[1]) if len(sys.argv) > 1 else None
if probe:
    TARGETS.append((probe, 1))

rs = root_rules()
print(f"root rules indexed: {len(rs)}\n" + "=" * 68)
total = 0
for p, tier in TARGETS:
    fs = check(p, tier, rs if p != ROOT / "AGENTS.md" else set())
    total += len(fs)
    label = p.name if p == probe else str(p.relative_to(ROOT))
    print(
        f"\n{label}  (tier {tier}, {len(p.read_text().splitlines())} lines) -> {len(fs)} findings"
    )
    for x in fs:
        print("   ", x)
print("\n" + "=" * 68 + f"\nTOTAL: {total} findings")
