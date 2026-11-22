#!/usr/bin/env python3
"""Apply governance repository settings via the GitHub API (idempotent). Needs admin rights.

  repo_settings.py --repo OWNER/NAME [--only rulesets,settings,actions,security,pages,environments] [--dry-run]

rulesets      rulesets/*.json, created or updated by name
settings      merge methods, auto-merge, branch deletion, squash commit = PR title + body, Discussions
actions       GITHUB_TOKEN read-only by default; fork PR workflows need approval (public repos)
security      public repos: Dependabot alerts + fixes, secret scanning + push protection,
              private vulnerability reporting, CodeQL default setup
pages         GitHub Pages from Actions, if the profile has a docs site
environments  release (always), production (if the profile deploys)
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import govlib  # noqa: E402

REPO_SETTINGS = {
    "allow_squash_merge": True,
    "allow_merge_commit": True,
    "allow_rebase_merge": False,
    "allow_auto_merge": True,
    "delete_branch_on_merge": True,
    "squash_merge_commit_title": "PR_TITLE",
    "squash_merge_commit_message": "PR_BODY",
}
ACTIONS_WORKFLOW_PERMISSIONS = {"default_workflow_permissions": "read", "can_approve_pull_request_reviews": False}
FORK_APPROVAL = {"approval_policy": "all_external_contributors"}
ALL_STEPS = ["rulesets", "settings", "actions", "security", "pages", "environments"]


def ruleset_templates() -> list[dict]:
    return [json.loads(p.read_text(encoding="utf-8")) for p in sorted((govlib.GOV_ROOT / "rulesets").glob("*.json"))]


class Applier:
    def __init__(self, repo: str, dry_run: bool):
        self.repo = repo
        self.dry_run = dry_run
        self.info = govlib.gh_api(f"repos/{repo}")
        self.public = not self.info.get("private", True)

    def call(self, path: str, method: str, body=None):
        print(f"{method} {path}{' ' + json.dumps(body) if body is not None else ''}")
        if self.dry_run:
            return None
        return govlib.gh_api(path, method=method, body=body)

    def try_call(self, path: str, method: str, body=None):
        try:
            return self.call(path, method, body)
        except govlib.GhError as exc:
            print(f"  warning: {exc}")
            return None

    def rulesets(self) -> None:
        existing = {r["name"]: r["id"] for r in govlib.gh_api(f"repos/{self.repo}/rulesets?per_page=100", paginate=True)}
        for template in ruleset_templates():
            if template["name"] in existing:
                self.call(f"repos/{self.repo}/rulesets/{existing[template['name']]}", "PUT", template)
            else:
                self.call(f"repos/{self.repo}/rulesets", "POST", template)

    def settings(self) -> None:
        body = dict(REPO_SETTINGS)
        if self.public:
            body["has_discussions"] = True
        self.call(f"repos/{self.repo}", "PATCH", body)

    def actions(self) -> None:
        self.call(f"repos/{self.repo}/actions/permissions/workflow", "PUT", ACTIONS_WORKFLOW_PERMISSIONS)
        if self.public:
            self.try_call(f"repos/{self.repo}/actions/permissions/fork-pr-contributor-approval", "PUT", FORK_APPROVAL)

    def security(self) -> None:
        if not self.public:
            print("private repository: security features depend on the plan; skipped")
            return
        self.try_call(f"repos/{self.repo}/vulnerability-alerts", "PUT")
        self.try_call(f"repos/{self.repo}/automated-security-fixes", "PUT")
        self.try_call(f"repos/{self.repo}/private-vulnerability-reporting", "PUT")
        self.try_call(
            f"repos/{self.repo}",
            "PATCH",
            {"security_and_analysis": {"secret_scanning": {"status": "enabled"}, "secret_scanning_push_protection": {"status": "enabled"}}},
        )
        self.try_call(f"repos/{self.repo}/code-scanning/default-setup", "PATCH", {"state": "configured", "query_suite": "default"})

    def pages(self, profile: dict) -> None:
        if not govlib.dig(profile, "docs.site"):
            print("no docs site in profile; Pages not configured")
            return
        try:
            govlib.gh_api(f"repos/{self.repo}/pages")
            self.try_call(f"repos/{self.repo}/pages", "PUT", {"build_type": "workflow"})
        except govlib.GhError:
            self.try_call(f"repos/{self.repo}/pages", "POST", {"build_type": "workflow"})

    def environments(self, profile: dict) -> None:
        self.call(f"repos/{self.repo}/environments/release", "PUT", {})
        if govlib.dig(profile, "commands.deploy"):
            self.call(f"repos/{self.repo}/environments/production", "PUT", {})


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--repo", required=True)
    parser.add_argument("--repo-dir", default=".")
    parser.add_argument("--only", default=",".join(ALL_STEPS))
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)

    profile = govlib.load_profile(args.repo_dir)
    applier = Applier(args.repo, args.dry_run)
    for step in [s.strip() for s in args.only.split(",") if s.strip()]:
        if step not in ALL_STEPS:
            return govlib.fail(f"unknown step {step}")
        print(f"== {step}")
        method = getattr(applier, step)
        method(profile) if step in ("pages", "environments") else method()
    return 0


if __name__ == "__main__":
    sys.exit(main())
