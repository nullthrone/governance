#!/usr/bin/env python3
"""classification-check: a non-feat PR into main must not change the public surface.

Surface = public API (per classification.api in .governance/profile.yml) plus the output of
every command in classification.surface (CLI help, route lists, ...). Both are computed for
the base commit and for the PR head; any difference fails the check.

  api: griffe               python, `griffe dump` of package.import_name, normalized
  api: api-extractor        node, API report (classification.api_report, default etc/*.api.md)
  api: cargo-semver-checks  rust, `cargo semver-checks --release-type patch`
  api: go-doc               go, `go doc -all` for every package
  api: none
"""
from __future__ import annotations

import argparse
import difflib
import glob
import json
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import govlib  # noqa: E402


def _members(obj: dict) -> list[dict]:
    members = obj.get("members") or {}
    if isinstance(members, dict):
        return list(members.values())
    return list(members)


def _param_text(params: list[dict]) -> str:
    parts = []
    for p in params or []:
        text = f"{p.get('kind', '')}:{p.get('name', '')}"
        if p.get("default") is not None:
            text += f"={p.get('default')}"
        parts.append(text)
    return ", ".join(parts)


def griffe_surface(dump: dict) -> list[str]:
    """Normalize a `griffe dump` JSON document to sorted public-surface lines."""
    lines: list[str] = []

    def visit(obj: dict, path: str) -> None:
        name = obj.get("name", "")
        if name.startswith("_") and name != "__init__":
            return
        kind = obj.get("kind", "")
        if kind == "alias":
            lines.append(f"alias {path} -> {obj.get('target_path', '')}")
            return
        if kind == "function":
            lines.append(f"function {path}({_param_text(obj.get('parameters', []))})")
        elif kind == "class":
            bases = ",".join(str(b) for b in obj.get("bases", []))
            lines.append(f"class {path}({bases})")
        elif kind == "attribute":
            lines.append(f"attribute {path}")
        elif kind == "module":
            lines.append(f"module {path}")
        for member in _members(obj):
            visit(member, f"{path}.{member.get('name', '')}")

    for top_name, top in dump.items():
        if isinstance(top, dict):
            visit({**top, "name": top.get("name", top_name)}, top.get("name", top_name))
    return sorted(set(lines))


def api_surface(tool: str, profile: dict, workdir: str, base_sha: str | None) -> list[str] | None:
    if tool in ("", "none", None):
        return None
    if tool == "griffe":
        package = govlib.dig(profile, "package.import_name") or govlib.dig(profile, "package.name")
        search = govlib.dig(profile, "classification.search_path") or ("src" if os.path.isdir(os.path.join(workdir, "src")) else ".")
        proc = govlib.run(["python", "-m", "griffe", "dump", package, "-s", search], cwd=workdir)
        if proc.returncode != 0:
            raise RuntimeError(f"griffe dump failed in {workdir}: {proc.stderr.strip()}")
        return griffe_surface(json.loads(proc.stdout))
    if tool == "api-extractor":
        command = govlib.dig(profile, "classification.api_command") or "npx api-extractor run --local"
        proc = govlib.run(command, cwd=workdir)
        if proc.returncode != 0:
            raise RuntimeError(f"api-extractor failed in {workdir}: {proc.stdout[-2000:]}{proc.stderr[-2000:]}")
        pattern = govlib.dig(profile, "classification.api_report") or "etc/*.api.md"
        lines: list[str] = []
        for path in sorted(glob.glob(os.path.join(workdir, pattern))):
            lines += Path(path).read_text(encoding="utf-8").splitlines()
        return lines
    if tool == "go-doc":
        pkgs = govlib.run(["go", "list", "./..."], cwd=workdir)
        lines = []
        for pkg in sorted(pkgs.stdout.split()):
            if "/internal/" in pkg or pkg.endswith("/internal"):
                continue
            doc = govlib.run(["go", "doc", "-all", pkg], cwd=workdir)
            lines += [f"{pkg}: {line}" for line in doc.stdout.splitlines() if line.strip()]
        return lines
    if tool == "cargo-semver-checks":
        return None  # handled separately (compares against base itself)
    raise RuntimeError(f"unknown classification.api tool: {tool}")


def surface_outputs(commands: list[str], workdir: str) -> dict[str, list[str]]:
    out = {}
    for command in commands or []:
        proc = govlib.run(command, cwd=workdir, timeout=600)
        out[command] = (proc.stdout + proc.stderr).splitlines()
    return out


def diff_text(name: str, before: list[str], after: list[str]) -> str:
    return "\n".join(list(difflib.unified_diff(before, after, f"base:{name}", f"head:{name}", lineterm=""))[:80])


def compute(workdir: str, profile: dict, tool: str, base_sha: str | None) -> dict:
    setup = govlib.dig(profile, "commands.setup")
    if setup:
        proc = govlib.run(setup, cwd=workdir, timeout=1800)
        if proc.returncode != 0:
            raise RuntimeError(f"setup failed in {workdir}: {proc.stderr[-2000:]}")
    build = govlib.dig(profile, "commands.build")
    if build and tool == "api-extractor":
        govlib.run(build, cwd=workdir, timeout=1800)
    return {
        "api": api_surface(tool, profile, workdir, base_sha),
        "surface": surface_outputs(govlib.dig(profile, "classification.surface") or [], workdir),
    }


def compare(base: dict, head: dict) -> list[str]:
    problems = []
    if base["api"] is not None and base["api"] != head["api"]:
        problems.append("Public API changed:\n" + diff_text("api", base["api"], head["api"]))
    for command, before in base["surface"].items():
        after = head["surface"].get(command, [])
        if before != after:
            problems.append(f"Output of `{command}` changed:\n" + diff_text(command, before, after))
    return problems


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--repo-dir", default=".")
    parser.add_argument("--base-sha", help="base commit (default: PR base sha from the event)")
    parser.add_argument("--title", help="PR title (default: from the event)")
    parser.add_argument("--base-ref", help="PR base branch (default: from the event)")
    parser.add_argument("--head-ref", help="PR head branch (default: from the event)")
    args = parser.parse_args(argv)

    pr = govlib.event_payload().get("pull_request") or {}
    title = args.title if args.title is not None else pr.get("title", "")
    base_ref = args.base_ref or (pr.get("base") or {}).get("ref", "")
    head_ref = args.head_ref or (pr.get("head") or {}).get("ref", "")
    base_sha = args.base_sha or (pr.get("base") or {}).get("sha")

    if base_ref != "main":
        govlib.summary("✅ Not a PR into main; classification check not applicable.")
        return 0
    if head_ref == "next" or head_ref.startswith("release-please--"):
        govlib.summary("✅ Candidate or release PR; classification check not applicable.")
        return 0
    if govlib.is_feat(title):
        return govlib.fail("feat PRs must target next (see pr-title check).")

    profile = govlib.load_profile(args.repo_dir)
    tool = govlib.dig(profile, "classification.api") or "none"
    commands = govlib.dig(profile, "classification.surface") or []
    if tool == "none" and not commands:
        govlib.summary("✅ Profile defines no public surface (classification.api: none, no surface commands).")
        return 0

    problems: list[str] = []
    if tool == "cargo-semver-checks":
        proc = govlib.run(["cargo", "semver-checks", "check-release", "--baseline-rev", base_sha, "--release-type", "patch"], cwd=args.repo_dir, timeout=3600)
        if proc.returncode != 0:
            problems.append("cargo-semver-checks reports changes that need more than a patch release:\n" + (proc.stdout + proc.stderr)[-4000:])
        tool = "none"

    with tempfile.TemporaryDirectory(prefix="gov-base-") as tmp:
        base_dir = os.path.join(tmp, "base")
        govlib.git("worktree", "add", "--detach", base_dir, base_sha, cwd=args.repo_dir)
        try:
            base = compute(base_dir, profile, tool, base_sha)
        finally:
            govlib.run(["git", "worktree", "remove", "--force", base_dir], cwd=args.repo_dir)
        head = compute(os.path.abspath(args.repo_dir), profile, tool, base_sha)
    problems += compare(base, head)

    if problems:
        return govlib.fail(
            "This non-feat PR into main changes the public surface. If it is new for users, retitle it as feat and target next.\n\n"
            + "\n\n".join(problems)
        )
    govlib.summary("✅ Public surface unchanged.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
