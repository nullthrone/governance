#!/usr/bin/env python3
"""Install or update the governance references in a project repository (idempotent).

  install.py --repo-dir . --sha <40-hex governance commit> [--visibility public|private]
             [--detect-profile] [--prune-workflows] [--prune-claude] [--dry-run]

Writes:
  .github/workflows/governance-*.yml   thin callers pinned to --sha (+ scorecard.yml for public repos)
  .github/dependabot.yml               package ecosystems of the profile, never github-actions
  .claude/settings.json                plugin marketplace pinned to --sha, plugin enabled, attribution off
  .governance/profile.yml              only if missing and --detect-profile
  .governance/release-please-config.json
  .release-please-manifest.json        only if missing (current version from manifests or tags)
  CLAUDE.md                            managed block replaced, project notes kept
  ARCHITECTURE.md                      created from template, or missing sections appended
  .github/ISSUE_TEMPLATE, DISCUSSION_TEMPLATE, pull_request_template.md   public repos (needs --repo)
A second run with the same arguments changes nothing.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import tomllib
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import detect_profile  # noqa: E402
import govlib  # noqa: E402

SHA_RE = re.compile(r"^[0-9a-f]{40}$")
PLACEHOLDER = "__GOVERNANCE_SHA__"
CALLERS_DIR = govlib.GOV_ROOT / "callers"
TEMPLATES = govlib.GOV_ROOT / "plugins" / "governance" / "templates"
BLOCK_RE = re.compile(r"<!-- governance:begin.*?<!-- governance:end -->", re.DOTALL)
ORG_DOTGITHUB = govlib.GOV_ROOT / "org-dotgithub"
REPO_COMMUNITY_DIRS = (".github/ISSUE_TEMPLATE", ".github/DISCUSSION_TEMPLATE")
ARCH_SECTIONS = ["## Components", "## Data flows", "## Boundaries", "## Current decisions"]
ALLOWED_SETTINGS_KEYS = {"$schema", "extraKnownMarketplaces", "enabledPlugins", "attribution", "permissions"}
RELEASE_TYPES = {"python": "python", "node": "node", "rust": "rust", "go": "go"}
ECOSYSTEMS = {"python": "pip", "node": "npm", "rust": "cargo", "go": "gomod"}


# --------------------------------------------------------------------------- expected content (shared with the audit)


def caller_names(visibility: str) -> list[str]:
    names = sorted(p.name for p in CALLERS_DIR.glob("*.yml") if p.name != "scorecard.yml")
    if visibility == "public":
        names.append("scorecard.yml")
    return sorted(names)


def caller_content(name: str, sha: str) -> str:
    return (CALLERS_DIR / name).read_text(encoding="utf-8").replace(PLACEHOLDER, sha)


def settings_content(sha: str, existing: dict | None = None) -> dict:
    cfg = govlib.load_config()
    settings: dict = {}
    if existing and isinstance(existing.get("permissions"), dict):
        settings["permissions"] = existing["permissions"]
    settings["extraKnownMarketplaces"] = {
        cfg["marketplace_name"]: {"source": {"source": "github", "repo": cfg["governance_repo"], "ref": sha}, "autoUpdate": False}
    }
    settings["enabledPlugins"] = {cfg["plugin"]: True}
    settings["attribution"] = False
    return settings


def release_please_config(profile: dict) -> dict:
    language = profile.get("language") or "other"
    package: dict = {"package-name": govlib.dig(profile, "package.name") or "", "changelog-path": "CHANGELOG.md"}
    return {
        "$schema": "https://raw.githubusercontent.com/googleapis/release-please/main/schemas/config.json",
        "release-type": RELEASE_TYPES.get(language, "simple"),
        "include-v-in-tag": True,
        # Tags are vX.Y.Z, matching the release-tags ruleset (refs/tags/v*) and release_tools.TAG_RE.
        "include-component-in-tag": False,
        "bump-minor-pre-major": True,
        "changelog-sections": [
            {"type": "feat", "section": "Features"},
            {"type": "fix", "section": "Bug Fixes"},
            {"type": "perf", "section": "Performance"},
            {"type": "revert", "section": "Reverts"},
            {"type": "docs", "section": "Documentation", "hidden": True},
            {"type": "refactor", "section": "Refactoring", "hidden": True},
            {"type": "chore", "section": "Chores", "hidden": True},
            {"type": "test", "section": "Tests", "hidden": True},
            {"type": "build", "section": "Build", "hidden": True},
            {"type": "ci", "section": "CI", "hidden": True},
        ],
        "packages": {".": package},
    }


def dependabot_content(profile: dict, repo_dir: Path) -> str:
    updates = []
    eco = ECOSYSTEMS.get(profile.get("language") or "")
    if eco:
        updates.append(eco)
    if (repo_dir / "Dockerfile").exists():
        updates.append("docker")
    lines = [
        "# Managed by nullthrone/governance. Workflows are governance-managed, so github-actions is not updated here.",
        "version: 2",
        "updates:",
    ]
    if not updates:
        lines[-1] = "updates: []"
    for ecosystem in updates:
        lines += [
            f"  - package-ecosystem: {ecosystem}",
            '    directory: "/"',
            "    schedule:",
            "      interval: weekly",
            "    open-pull-requests-limit: 5",
            "    commit-message:",
            "      prefix: fix",
            "      prefix-development: chore",
            "      include: scope",
            "    labels:",
            "      - dependencies",
        ]
    return "\n".join(lines) + "\n"


def community_files(discussions_url: str, repo_level: bool) -> dict[str, str]:
    """Files from org-dotgithub/ with {{DISCUSSIONS_URL}} filled in.

    repo_level=True: only issue/discussion forms and the PR template (for public project repos,
    so that the Ideas link points to the repository's own Discussions).
    """
    files = {}
    for path in sorted(ORG_DOTGITHUB.rglob("*")):
        if not path.is_file():
            continue
        rel = path.relative_to(ORG_DOTGITHUB).as_posix()
        if repo_level and not (rel.startswith(REPO_COMMUNITY_DIRS) or rel == ".github/pull_request_template.md"):
            continue
        files[rel] = path.read_text(encoding="utf-8").replace("{{DISCUSSIONS_URL}}", discussions_url.rstrip("/"))
    return files


def managed_block() -> str:
    m = BLOCK_RE.search((TEMPLATES / "CLAUDE.md").read_text(encoding="utf-8"))
    assert m, "template CLAUDE.md lacks the managed block"
    return m.group(0)


def current_version(repo_dir: Path) -> str:
    py = repo_dir / "pyproject.toml"
    if py.exists():
        try:
            version = tomllib.loads(py.read_text(encoding="utf-8")).get("project", {}).get("version")
            if version:
                return str(version)
        except tomllib.TOMLDecodeError:
            pass
    pkg = repo_dir / "package.json"
    if pkg.exists():
        try:
            version = json.loads(pkg.read_text(encoding="utf-8")).get("version")
            if version:
                return str(version)
        except json.JSONDecodeError:
            pass
    cargo = repo_dir / "Cargo.toml"
    if cargo.exists():
        try:
            version = tomllib.loads(cargo.read_text(encoding="utf-8")).get("package", {}).get("version")
            if version:
                return str(version)
        except tomllib.TOMLDecodeError:
            pass
    proc = govlib.run(["git", "describe", "--tags", "--abbrev=0", "--match", "v[0-9]*"], cwd=repo_dir)
    if proc.returncode == 0 and re.match(r"^v?\d+\.\d+\.\d+$", proc.stdout.strip()):
        return proc.stdout.strip().lstrip("v")
    return "0.0.0"


# --------------------------------------------------------------------------- install


class Installer:
    def __init__(self, repo_dir: Path, dry_run: bool):
        self.root = repo_dir
        self.dry_run = dry_run
        self.changes: list[str] = []

    def write(self, rel: str, content: str) -> None:
        path = self.root / rel
        if path.exists() and path.read_text(encoding="utf-8") == content:
            return
        self.changes.append(f"write {rel}")
        if not self.dry_run:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content, encoding="utf-8")

    def remove(self, rel: str) -> None:
        path = self.root / rel
        if not path.exists():
            return
        self.changes.append(f"remove {rel}")
        if self.dry_run:
            return
        if path.is_dir():
            for child in sorted(path.rglob("*"), reverse=True):
                child.rmdir() if child.is_dir() else child.unlink()
            path.rmdir()
        else:
            path.unlink()

    def run(self, sha: str, visibility: str, detect: bool, prune_workflows: bool, prune_claude: bool, repo: str | None = None) -> list[str]:
        wanted = caller_names(visibility)
        for name in wanted:
            self.write(f".github/workflows/{name}", caller_content(name, sha))
        workflows = self.root / ".github" / "workflows"
        if workflows.is_dir():
            for path in sorted(workflows.iterdir()):
                if path.name in wanted:
                    continue
                if prune_workflows or path.name.startswith("governance-") or path.name == "scorecard.yml":
                    self.remove(f".github/workflows/{path.name}")

        settings_path = self.root / ".claude" / "settings.json"
        existing = {}
        if settings_path.exists():
            try:
                existing = json.loads(settings_path.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                existing = {}
        self.write(".claude/settings.json", json.dumps(settings_content(sha, existing), indent=2) + "\n")
        if prune_claude and (self.root / ".claude").is_dir():
            for path in sorted((self.root / ".claude").iterdir()):
                if path.name != "settings.json":
                    self.remove(f".claude/{path.name}")

        profile_path = self.root / govlib.PROFILE_PATH
        if not profile_path.exists() and detect:
            prof = detect_profile.detect(self.root)
            self.write(govlib.PROFILE_PATH, detect_profile.HEADER + govlib.yaml_dump(prof))
        profile = govlib.yaml_load(profile_path.read_text(encoding="utf-8")) if profile_path.exists() else (detect_profile.detect(self.root) if detect else {})

        self.write(".governance/release-please-config.json", json.dumps(release_please_config(profile), indent=2) + "\n")
        if not (self.root / ".release-please-manifest.json").exists():
            self.write(".release-please-manifest.json", json.dumps({".": current_version(self.root)}, indent=2) + "\n")
        self.write(".github/dependabot.yml", dependabot_content(profile, self.root))
        if visibility == "public" and repo:
            for rel, content in community_files(f"https://github.com/{repo}/discussions", repo_level=True).items():
                self.write(rel, content)

        claude_md = self.root / "CLAUDE.md"
        template = (TEMPLATES / "CLAUDE.md").read_text(encoding="utf-8")
        if claude_md.exists():
            text = claude_md.read_text(encoding="utf-8")
            if BLOCK_RE.search(text):
                text = BLOCK_RE.sub(lambda _: managed_block(), text, count=1)
            else:
                body = re.sub(r"^#\s*CLAUDE\.md\s*\n", "", text).strip()
                text = template.rstrip() + ("\n\n" + body + "\n" if body else "\n")
            self.write("CLAUDE.md", text)
        else:
            self.write("CLAUDE.md", template)

        arch = self.root / "ARCHITECTURE.md"
        if arch.exists():
            text = arch.read_text(encoding="utf-8")
            missing = [s for s in ARCH_SECTIONS if not re.search(rf"^{re.escape(s)}\s*$", text, re.MULTILINE)]
            if missing:
                text = text.rstrip() + "\n\n" + "\n\n".join(missing) + "\n"
                self.write("ARCHITECTURE.md", text)
        else:
            self.write("ARCHITECTURE.md", (TEMPLATES / "ARCHITECTURE.md").read_text(encoding="utf-8"))
        return self.changes


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--repo-dir", default=".")
    parser.add_argument("--sha", required=True, help="governance commit to pin (40 hex)")
    parser.add_argument("--visibility", choices=["public", "private"], default="public")
    parser.add_argument("--repo", help="OWNER/NAME; public repos get issue forms linking to their Discussions")
    parser.add_argument("--detect-profile", action="store_true")
    parser.add_argument("--prune-workflows", action="store_true", help="remove every workflow that is not a governance caller")
    parser.add_argument("--prune-claude", action="store_true", help="remove everything in .claude/ except settings.json")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)
    if not SHA_RE.match(args.sha):
        return govlib.fail("--sha must be a full 40-character lowercase commit SHA")
    changes = Installer(Path(args.repo_dir).resolve(), args.dry_run).run(args.sha, args.visibility, args.detect_profile, args.prune_workflows, args.prune_claude, args.repo)
    print("\n".join(changes) if changes else "unchanged")
    return 0


if __name__ == "__main__":
    sys.exit(main())
