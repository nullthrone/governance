#!/usr/bin/env python3
"""governance-audit: machine check of a project repository against nullthrone/governance.

  governance_audit.py [--repo-dir .] [--repo OWNER/NAME] [--local | --ci] [--visibility public|private]
                      [--expected-sha SHA] [--json report.json]

Modes
  default  all checks; remote checks use the owner's gh login. A remote check that cannot run fails.
  --ci     as default, but checks that need the owner's own token (app installation permissions) are skipped.
  --local  only checks on the working tree; remote checks are reported as skip.

Output: human summary on stdout, JSON report with --json. Exit code 1 if any check fails.
Statuses: pass, fail, skip (not run in this mode), info (reported, never fails; e.g. Scorecard score).
"""
from __future__ import annotations

import argparse
import json
import re
import shutil
import sys
import urllib.error
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import detect_profile  # noqa: E402
import govlib  # noqa: E402
import install  # noqa: E402
import repo_settings  # noqa: E402
import sync_labels  # noqa: E402

LEGACY_BRANCH_RE = re.compile(r"^(?:develop|development|dev|master|staging|release/.+|hotfix/.+|releases/.+)$")
PUBLISH_SECRET_RE = re.compile(r"^(?:PYPI|PYPI_API|TEST_PYPI|TESTPYPI|NPM|NPM_AUTH|NODE_AUTH|CARGO_REGISTRY|CRATES|CRATES_IO)(?:_API)?_TOKEN$|^TWINE_(?:PASSWORD|USERNAME)$", re.IGNORECASE)
FOREIGN_RELEASE_FILES = [
    ".goreleaser.yml", ".goreleaser.yaml", ".releaserc", ".releaserc.json", ".releaserc.yml", ".releaserc.yaml",
    "release.config.js", "release.config.cjs", "release.config.mjs", ".changeset/config.json", ".bumpversion.cfg",
    ".bumpversion.toml", "release-please-config.json", ".github/release-drafter.yml", "release.toml",
]
FOREIGN_RELEASE_NPM = {"semantic-release", "standard-version", "release-it", "@changesets/cli", "np"}
CONTRADICTING_RULES = [
    (re.compile(r"co-authored-by", re.IGNORECASE), "asks for attribution trailers"),
    (re.compile(r"\b(?:into|from|to)\s+(?:the\s+)?develop\b|\bdevelop branch\b", re.IGNORECASE), "refers to a develop branch"),
    (re.compile(r"--no-verify", re.IGNORECASE), "suggests skipping hooks"),
    (re.compile(r"force[- ]push", re.IGNORECASE), "mentions force pushes"),
    (re.compile(r"push(?:es)?\s+(?:directly\s+)?(?:to|into)\s+main", re.IGNORECASE), "suggests pushing to main"),
    (re.compile(r"skip(?:ping)?\s+(?:the\s+)?tests", re.IGNORECASE), "suggests skipping tests"),
]
# Governance pin of a caller (`uses: nullthrone/governance/...@<sha>`); third-party actions carry SHA pins too.
PIN_RE = re.compile(r"nullthrone/governance/[^@\s]+@([0-9a-f]{40})\b")


class Audit:
    def __init__(self, repo_dir: Path, repo: str | None, mode: str, visibility: str | None, expected_sha: str | None):
        self.root = repo_dir
        self.repo = repo
        self.mode = mode
        self.expected_sha = expected_sha
        self.cfg = govlib.load_config()
        self.results: list[dict] = []
        self.scorecard: dict | None = None
        self.info: dict | None = None
        self.remote_ok = mode != "local" and bool(repo) and govlib.gh_authenticated()
        if self.remote_ok:
            try:
                self.info = govlib.gh_api(f"repos/{repo}")
            except govlib.GhError as exc:
                self.remote_ok = False
                self.remote_error = str(exc)
        if visibility:
            self.visibility = visibility
        elif self.info is not None:
            self.visibility = "private" if self.info.get("private") else "public"
        else:
            self.visibility = "public" if (repo_dir / ".github" / "workflows" / "scorecard.yml").exists() else "private"
        self.profile = govlib.load_profile(repo_dir)
        self.pin: str | None = None

    # ----------------------------------------------------------------- bookkeeping

    def add(self, check_id: str, status: str, message: str) -> None:
        self.results.append({"id": check_id, "status": status, "message": message})

    def remote(self, check_id: str, func) -> None:
        if self.mode == "local":
            self.add(check_id, "skip", "remote check; not run with --local")
            return
        if not self.remote_ok:
            reason = getattr(self, "remote_error", "gh not authenticated or --repo missing")
            self.add(check_id, "fail", f"cannot verify: {reason}")
            return
        try:
            func()
        except govlib.GhError as exc:
            self.add(check_id, "fail", f"cannot verify: {exc}")

    def read(self, rel: str) -> str | None:
        path = self.root / rel
        return path.read_text(encoding="utf-8") if path.is_file() else None

    # ----------------------------------------------------------------- local checks

    def check_workflows(self) -> None:
        wf_dir = self.root / ".github" / "workflows"
        present = sorted(p.name for p in wf_dir.iterdir() if p.is_file()) if wf_dir.is_dir() else []
        wanted = install.caller_names(self.visibility)
        problems = []
        extra = sorted(set(present) - set(wanted))
        missing = sorted(set(wanted) - set(present))
        if extra:
            problems.append(f"not allowed: {', '.join(extra)}")
        if missing:
            problems.append(f"missing: {', '.join(missing)}")
        pins = set()
        for name in sorted(set(present) & set(wanted)):
            text = (wf_dir / name).read_text(encoding="utf-8")
            file_pins = set(PIN_RE.findall(text))
            pins |= file_pins
            pin = next(iter(file_pins)) if len(file_pins) == 1 else None
            if name != "scorecard.yml" and pin is None:
                problems.append(f"{name}: needs exactly one 40-hex governance pin (found {len(file_pins)})")
                continue
            if text != install.caller_content(name, pin or ""):
                problems.append(f"{name}: differs from the governance template")
        if len(pins) > 1:
            problems.append(f"inconsistent pins: {', '.join(sorted(pins))}")
        self.pin = next(iter(pins)) if len(pins) == 1 else None
        self.add("workflows", "fail" if problems else "pass", "; ".join(problems) or f"only pinned governance callers ({len(wanted)} files)")

    def check_claude_dir(self) -> None:
        claude = self.root / ".claude"
        problems = []
        if not claude.is_dir():
            self.add("claude-dir", "fail", ".claude/ missing")
            return
        others = sorted(p.name for p in claude.iterdir() if p.name != "settings.json")
        if others:
            problems.append(f"only settings.json allowed, found: {', '.join(others)}")
        text = self.read(".claude/settings.json")
        if text is None:
            problems.append("settings.json missing")
        else:
            try:
                settings = json.loads(text)
            except json.JSONDecodeError as exc:
                self.add("claude-dir", "fail", f"settings.json invalid: {exc}")
                return
            unknown = sorted(set(settings) - install.ALLOWED_SETTINGS_KEYS)
            if unknown:
                problems.append(f"settings keys not allowed: {', '.join(unknown)} (no hooks, no env)")
            attribution = settings.get("attribution")
            if not (attribution is False or (isinstance(attribution, dict) and attribution.get("commit") == "" and attribution.get("pr") == "")):
                problems.append("attribution not disabled")
            expected = install.settings_content(self.pin or "", settings)
            for key in ("extraKnownMarketplaces", "enabledPlugins"):
                if settings.get(key) != expected[key]:
                    problems.append(f"{key} does not pin {self.cfg['governance_repo']} at the workflow pin")
        self.add("claude-dir", "fail" if problems else "pass", "; ".join(problems) or "plugin pinned, attribution off, no own hooks")

    def check_pin(self) -> None:
        if not self.pin:
            self.add("pin", "fail", "no consistent governance pin in the workflows")
            return
        if self.expected_sha and self.pin != self.expected_sha:
            self.add("pin", "fail", f"pinned {self.pin[:12]}, expected {self.expected_sha[:12]}")
            return
        self.add("pin", "pass", f"governance pinned at {self.pin[:12]}")

    def check_issue_templates(self) -> None:
        offenders = []
        for base in (".github/ISSUE_TEMPLATE", ".github/DISCUSSION_TEMPLATE"):
            d = self.root / base
            if d.is_dir():
                for f in sorted(d.rglob("*")):
                    if f.is_file() and re.search(r"\bpo:[a-z]", f.read_text(encoding="utf-8", errors="ignore")):
                        offenders.append(f.relative_to(self.root).as_posix())
        problems = [f"po:* labels in templates: {', '.join(offenders)}"] if offenders else []
        if self.visibility == "public" and self.repo:
            for rel, content in install.community_files(f"https://github.com/{self.repo}/discussions", repo_level=True).items():
                if self.read(rel) != content:
                    problems.append(f"{rel} missing or differs from org-dotgithub")
        self.add("issue-templates", "fail" if problems else "pass", "; ".join(problems) or "governance issue forms, no po:* labels")

    def check_release_mechanism(self) -> None:
        problems = []
        text = self.read(".governance/release-please-config.json")
        language = self.profile.get("language") or "other"
        if text is None:
            problems.append(".governance/release-please-config.json missing")
        else:
            try:
                rp = json.loads(text)
                expected = install.RELEASE_TYPES.get(language, "simple")
                if rp.get("release-type") != expected:
                    problems.append(f"release-type {rp.get('release-type')!r}, expected {expected!r}")
            except json.JSONDecodeError:
                problems.append("release-please config is not valid JSON")
        manifest = self.read(".release-please-manifest.json")
        if manifest is None or "." not in (json.loads(manifest) if manifest.strip().startswith("{") else {}):
            problems.append(".release-please-manifest.json missing or without '.'")
        foreign = [f for f in FOREIGN_RELEASE_FILES if (self.root / f).exists()]
        pkg = self.read("package.json")
        if pkg:
            try:
                data = json.loads(pkg)
                deps = {**data.get("dependencies", {}), **data.get("devDependencies", {})}
                foreign += sorted(f"package.json:{d}" for d in FOREIGN_RELEASE_NPM & set(deps))
            except json.JSONDecodeError:
                pass
        py = self.read("pyproject.toml")
        if py and re.search(r"^\[tool\.(?:semantic_release|bumpversion|commitizen)\]", py, re.MULTILINE):
            foreign.append("pyproject.toml:[tool.*release*]")
        if foreign:
            problems.append(f"foreign release mechanisms: {', '.join(foreign)}")
        self.add("release-mechanism", "fail" if problems else "pass", "; ".join(problems) or "release-please only")

    def check_claude_md(self) -> None:
        text = self.read("CLAUDE.md")
        if text is None:
            self.add("claude-md", "fail", "CLAUDE.md missing")
            return
        block = install.BLOCK_RE.search(text)
        problems = []
        if not block:
            problems.append("managed governance block missing")
        elif block.group(0) != install.managed_block():
            problems.append("managed governance block differs from the template")
        local = sorted(p.relative_to(self.root).as_posix() for p in self.root.rglob("CLAUDE.local.md") if ".git" not in p.parts)
        if local:
            problems.append(f"CLAUDE.local.md files override the managed rules: {', '.join(local)}")
        rest = install.BLOCK_RE.sub("", text)
        for pattern, why in CONTRADICTING_RULES:
            if pattern.search(rest):
                problems.append(f"project notes {why}")
        self.add("claude-md", "fail" if problems else "pass", "; ".join(problems) or "template block intact, no contradicting rules")

    def check_architecture_md(self) -> None:
        text = self.read("ARCHITECTURE.md")
        if text is None:
            self.add("architecture-md", "fail", "ARCHITECTURE.md missing")
            return
        missing = [s for s in install.ARCH_SECTIONS if not re.search(rf"^{re.escape(s)}\s*$", text, re.MULTILINE)]
        problems = [f"missing sections: {', '.join(missing)}"] if missing else []
        m = re.search(r"^## Current decisions\s*$(.*?)(?=^## |\Z)", text, re.MULTILINE | re.DOTALL)
        if m:
            body = re.sub(r"<!--.*?-->", "", m.group(1), flags=re.DOTALL)
            lines = [line for line in body.splitlines() if line.strip()]
            if len(lines) > 60:
                problems.append(f"Current decisions has {len(lines)} lines (max 60)")
        for pattern, why in CONTRADICTING_RULES:
            if pattern.search(text):
                problems.append(f"ARCHITECTURE.md {why}")
        self.add("architecture-md", "fail" if problems else "pass", "; ".join(problems) or "template sections present, Current decisions within limit")

    def check_profile(self) -> None:
        text = self.read(govlib.PROFILE_PATH)
        if text is None:
            self.add("profile", "fail", f"{govlib.PROFILE_PATH} missing")
            return
        try:
            prof = govlib.yaml_load(text) or {}
        except govlib.YamlError as exc:
            self.add("profile", "fail", f"profile does not parse: {exc}")
            return
        problems = []
        for key in ("version", "language", "profiles", "commands.test", "commands.version"):
            if govlib.dig(prof, key) in (None, "", []):
                problems.append(f"{key} missing")
        if prof.get("uncertain"):
            problems.append(f"unconfirmed fields: {', '.join(prof['uncertain'])}")
        problems += detect_profile.compare(prof, detect_profile.detect(self.root))
        self.add("profile", "fail" if problems else "pass", "; ".join(problems) or "present, confirmed and consistent with the manifests")

    def check_version_smoke(self) -> None:
        command = govlib.dig(self.profile, "commands.version")
        self.add("version-smoke", "pass" if command else "fail", f"version smoke test: `{command}`" if command else "commands.version missing (version smoke test)")

    def check_dependabot(self) -> None:
        text = self.read(".github/dependabot.yml")
        expected = install.dependabot_content(self.profile, self.root)
        if text is None:
            self.add("dependabot", "fail", ".github/dependabot.yml missing")
        elif text != expected:
            self.add("dependabot", "fail", ".github/dependabot.yml differs from the governance template")
        else:
            self.add("dependabot", "pass", "package ecosystems only, no github-actions")

    def check_branches_local(self) -> None:
        refs = govlib.run(["git", "for-each-ref", "--format=%(refname:short)", "refs/heads", "refs/remotes/origin"], cwd=self.root).stdout.split()
        names = {r.removeprefix("origin/") for r in refs if r not in ("origin", "origin/HEAD")}
        self._branches(names, "local refs")

    def _branches(self, names: set[str], source: str) -> None:
        problems = [f"{b} missing" for b in ("main", "next") if b not in names]
        legacy = sorted(n for n in names if LEGACY_BRANCH_RE.match(n))
        if legacy:
            problems.append(f"legacy branches: {', '.join(legacy)}")
        self.add("branches", "fail" if problems else "pass", "; ".join(problems) or f"main and next present, no legacy branches ({source})")

    # ----------------------------------------------------------------- remote checks

    def check_branches_remote(self) -> None:
        names = {b["name"] for b in govlib.gh_api(f"repos/{self.repo}/branches?per_page=100", paginate=True)}
        self._branches(names, "GitHub")
        default = (self.info or {}).get("default_branch")
        self.add("default-branch", "pass" if default == "main" else "fail", f"default branch is {default!r}")

    def check_rulesets(self) -> None:
        listed = {r["name"]: r["id"] for r in govlib.gh_api(f"repos/{self.repo}/rulesets?per_page=100", paginate=True)}
        problems = []
        for template in repo_settings.ruleset_templates():
            if template["name"] not in listed:
                problems.append(f"{template['name']} missing")
                continue
            live = govlib.gh_api(f"repos/{self.repo}/rulesets/{listed[template['name']]}")
            if live.get("enforcement") != "active":
                problems.append(f"{template['name']} not active")
            live_ref = live.get("conditions", {}).get("ref_name", {})
            want_ref = template["conditions"]["ref_name"]
            if sorted(live_ref.get("include") or []) != sorted(want_ref["include"]) or sorted(live_ref.get("exclude") or []) != sorted(want_ref["exclude"]):
                problems.append(f"{template['name']} targets other refs (include/exclude)")
            if live.get("target") != template["target"]:
                problems.append(f"{template['name']} has target {live.get('target')!r}")
            live_rules = {r["type"]: r.get("parameters", {}) for r in live.get("rules", [])}
            for rule in template["rules"]:
                if rule["type"] not in live_rules:
                    problems.append(f"{template['name']}: rule {rule['type']} missing")
                    continue
                for key, value in (rule.get("parameters") or {}).items():
                    if key == "required_status_checks":
                        continue
                    have = live_rules[rule["type"]].get(key)
                    if (sorted(have) if isinstance(have, list) else have) != (sorted(value) if isinstance(value, list) else value):
                        problems.append(f"{template['name']}: {rule['type']}.{key} is {have!r}, want {value!r}")
            if "required_status_checks" in {r["type"] for r in template["rules"]}:
                want = {(c["context"], c["integration_id"]) for r in template["rules"] if r["type"] == "required_status_checks" for c in r["parameters"]["required_status_checks"]}
                have = {(c["context"], c.get("integration_id")) for c in live_rules.get("required_status_checks", {}).get("required_status_checks", [])}
                if want != have:
                    problems.append(f"{template['name']}: required checks differ or are not bound to GitHub Actions")
            if live.get("bypass_actors"):
                problems.append(f"{template['name']}: has bypass actors")
        self.add("rulesets", "fail" if problems else "pass", "; ".join(problems) or "rulesets match the templates; checks bound to GitHub Actions")

    def check_token_permissions(self) -> None:
        if self.mode == "ci":
            self.add("token-permissions", "skip", "needs the owner's token (run the audit locally)")
            return
        # user/installations accepts only GitHub App user tokens; a gh OAuth login gets 403 there.
        # For organization repositories the organization's installation list carries the same data.
        via_org = False
        try:
            installations = govlib.gh_api("user/installations?per_page=100", paginate=True)
        except govlib.GhError:
            owner = self.repo.split("/", 1)[0]
            installations = govlib.gh_api(f"orgs/{owner}/installations?per_page=100", paginate=True)
            via_org = True
        slug = self.cfg["bot_app_slug"]
        mine = [i for i in installations if i.get("app_slug") == slug]
        problems = []
        if not mine:
            self.add("token-permissions", "fail", f"governance app '{slug}' is not installed for this account")
            return
        covered = False
        for inst in mine:
            perms = inst.get("permissions", {})
            if perms.get("workflows") not in (None, "none"):
                problems.append(f"app '{slug}' has workflows:{perms['workflows']}")
            for needed in ("contents", "pull_requests", "issues"):
                if perms.get(needed) != "write":
                    problems.append(f"app '{slug}' lacks {needed}:write")
            if inst.get("repository_selection") == "all":
                covered = True
            elif via_org:
                problems.append(f"app '{slug}' is installed on selected repositories; coverage of {self.repo} needs an app user token")
                covered = True  # reported above; avoid a second, misleading message
            else:
                repos = govlib.gh_api(f"user/installations/{inst['id']}/repositories?per_page=100", paginate=True)
                covered = covered or any(r.get("full_name") == self.repo for r in repos)
        if not covered:
            problems.append(f"app '{slug}' is not installed on {self.repo}")
        claude_apps = [i for i in installations if i.get("app_slug") == "claude" and (i.get("permissions") or {}).get("workflows") == "write"]
        note = " (note: the official Claude app with workflows:write is installed; autonomous jobs never use it)" if claude_apps else ""
        self.add("token-permissions", "fail" if problems else "pass", ("; ".join(problems) or f"app '{slug}' without workflows permission") + note)

    def check_labels(self) -> None:
        existing = govlib.gh_api(f"repos/{self.repo}/labels?per_page=100", paginate=True)
        plan = sync_labels.diff_labels(sync_labels.taxonomy(), existing)
        problems = [f"missing: {', '.join(l['name'] for l in plan['create'])}"] if plan["create"] else []
        if plan["update"]:
            problems.append(f"differs: {', '.join(l['name'] for l in plan['update'])}")
        extra = f" ({len(plan['extra'])} extra labels kept)" if plan["extra"] else ""
        self.add("labels", "fail" if problems else "pass", ("; ".join(problems) or "taxonomy in sync") + extra)

    def check_publish_secrets(self) -> None:
        names = [s["name"] for s in govlib.gh_api(f"repos/{self.repo}/actions/secrets?per_page=100", paginate=True)]
        try:
            names += [f"org:{s['name']}" for s in govlib.gh_api(f"repos/{self.repo}/actions/organization-secrets?per_page=100", paginate=True)]
        except govlib.GhError:
            pass
        for env in govlib.gh_api(f"repos/{self.repo}/environments?per_page=100", paginate=True):
            names += [f"{env['name']}:{s['name']}" for s in govlib.gh_api(f"repos/{self.repo}/environments/{env['name']}/secrets?per_page=100", paginate=True)]
        bad = sorted(n for n in names if PUBLISH_SECRET_RE.match(n.split(":")[-1]))
        self.add("publish-secrets", "fail" if bad else "pass", f"publish secrets present (use trusted publishing): {', '.join(bad)}" if bad else "no publish secrets; trusted publishing only")

    def check_repo_settings(self) -> None:
        info = self.info or {}
        problems = [f"{k}={info.get(k)!r} (want {v!r})" for k, v in repo_settings.REPO_SETTINGS.items() if info.get(k) != v]
        wf = govlib.gh_api(f"repos/{self.repo}/actions/permissions/workflow")
        if wf.get("default_workflow_permissions") != "read":
            problems.append("GITHUB_TOKEN default is not read-only")
        if wf.get("can_approve_pull_request_reviews"):
            problems.append("Actions may approve pull requests")
        if self.visibility == "public":
            try:
                fork = govlib.gh_api(f"repos/{self.repo}/actions/permissions/fork-pr-contributor-approval")
                if fork.get("approval_policy") != "all_external_contributors":
                    problems.append(f"fork PR workflows: {fork.get('approval_policy')} (want all_external_contributors)")
            except govlib.GhError as exc:
                problems.append(f"fork PR approval policy unknown: {exc}")
        self.add("repo-settings", "fail" if problems else "pass", "; ".join(problems) or "merge, auto-merge and Actions settings as required")

    def check_security(self) -> None:
        if self.visibility != "public":
            self.add("security-features", "skip", "private repository (features depend on the plan)")
            return
        problems = []
        try:
            govlib.gh("api", f"repos/{self.repo}/vulnerability-alerts")
        except govlib.GhError:
            problems.append("Dependabot alerts disabled")
        sa = (self.info or {}).get("security_and_analysis") or {}
        for key in ("secret_scanning", "secret_scanning_push_protection"):
            if (sa.get(key) or {}).get("status") != "enabled":
                problems.append(f"{key} disabled")
        try:
            if not govlib.gh_api(f"repos/{self.repo}/private-vulnerability-reporting").get("enabled"):
                problems.append("private vulnerability reporting disabled")
        except govlib.GhError:
            problems.append("private vulnerability reporting unknown")
        try:
            if govlib.gh_api(f"repos/{self.repo}/code-scanning/default-setup").get("state") != "configured":
                problems.append("CodeQL default setup not configured")
        except govlib.GhError:
            problems.append("CodeQL default setup unknown")
        self.add("security-features", "fail" if problems else "pass", "; ".join(problems) or "Dependabot, secret scanning, push protection, PVR, CodeQL enabled")

    def check_pin_exists(self) -> None:
        if not self.pin:
            self.add("pin-exists", "fail", "no pin to verify")
            return
        govlib.gh_api(f"repos/{self.cfg['governance_repo']}/commits/{self.pin}")
        self.add("pin-exists", "pass", f"{self.pin[:12]} exists in {self.cfg['governance_repo']}")

    def check_scorecard(self) -> None:
        if self.visibility != "public":
            self.add("scorecard", "skip", "private repository")
            return
        proc = govlib.run(["scorecard", f"--repo=github.com/{self.repo}", "--format=json"]) if shutil.which("scorecard") else None
        if proc is not None and proc.returncode == 0 and proc.stdout.strip().startswith("{"):
            self.scorecard = json.loads(proc.stdout)
        else:
            url = f"https://api.securityscorecards.dev/projects/github.com/{self.repo}"
            try:
                with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "governance-audit"}), timeout=20) as resp:
                    self.scorecard = json.loads(resp.read())
            except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
                self.add("scorecard", "info", f"no Scorecard result yet ({exc})")
                return
        self.add("scorecard", "info", f"OpenSSF Scorecard score {self.scorecard.get('score')}")

    # ----------------------------------------------------------------- run

    def run(self) -> dict:
        self.check_workflows()
        self.check_pin()
        self.check_claude_dir()
        self.check_issue_templates()
        self.check_release_mechanism()
        self.check_claude_md()
        self.check_architecture_md()
        self.check_profile()
        self.check_version_smoke()
        self.check_dependabot()
        if self.mode == "local":
            self.check_branches_local()
        else:
            self.remote("branches", self.check_branches_remote)
        self.remote("rulesets", self.check_rulesets)
        self.remote("token-permissions", self.check_token_permissions)
        self.remote("labels", self.check_labels)
        self.remote("publish-secrets", self.check_publish_secrets)
        self.remote("repo-settings", self.check_repo_settings)
        self.remote("security-features", self.check_security)
        self.remote("pin-exists", self.check_pin_exists)
        self.remote("scorecard", self.check_scorecard)
        failed = [r for r in self.results if r["status"] == "fail"]
        return {
            "repo": self.repo,
            "mode": self.mode,
            "visibility": self.visibility,
            "pin": self.pin,
            "passed": not failed,
            "checks": self.results,
            "scorecard_score": (self.scorecard or {}).get("score"),
        }


def repo_from_git(repo_dir: Path) -> str | None:
    url = govlib.run(["git", "remote", "get-url", "origin"], cwd=repo_dir).stdout.strip()
    m = re.search(r"github\.com[:/]([^/]+/[^/]+?)(?:\.git)?$", url)
    return m.group(1) if m else None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--repo-dir", default=".")
    parser.add_argument("--repo")
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--local", action="store_true")
    group.add_argument("--ci", action="store_true")
    parser.add_argument("--visibility", choices=["public", "private"])
    parser.add_argument("--expected-sha")
    parser.add_argument("--json", dest="json_path")
    args = parser.parse_args(argv)

    root = Path(args.repo_dir).resolve()
    mode = "local" if args.local else ("ci" if args.ci else "full")
    report = Audit(root, args.repo or repo_from_git(root), mode, args.visibility, args.expected_sha).run()
    if args.json_path:
        Path(args.json_path).write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    width = max(len(r["id"]) for r in report["checks"])
    print(f"governance-audit {report['repo'] or root.name} ({mode}, {report['visibility']})")
    for r in report["checks"]:
        print(f"  {r['status'].upper():5} {r['id']:<{width}}  {r['message']}")
    counts = {s: sum(1 for r in report["checks"] if r["status"] == s) for s in ("pass", "fail", "skip", "info")}
    print(f"result: {'PASS' if report['passed'] else 'FAIL'} — {counts['pass']} pass, {counts['fail']} fail, {counts['skip']} skip, {counts['info']} info")
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    sys.exit(main())
