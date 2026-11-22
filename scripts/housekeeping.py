#!/usr/bin/env python3
"""Deterministic pre-filters and actions for scheduled housekeeping.

  housekeeping.py plan --schedule "<cron>" [--task NAME]   tasks to run for this trigger (JSON)
  housekeeping.py check <task>                             run the pre-filter; outputs run, vars, agent, tier
  housekeeping.py audit-issue --report audit.json          open/update the po:decision issue for a failed audit
  housekeeping.py cleanup                                  delete merged branches, close stale bot PRs

Claude is started only when `check` outputs run=true. Every check is cheap and token-free.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import checks  # noqa: E402
import classify_check  # noqa: E402
import govlib  # noqa: E402

NIGHTLY = "17 2 * * *"
WEEKLY = "37 3 * * 1"
MONTHLY = "57 4 1 * *"
CADENCE = {NIGHTLY: "nightly", WEEKLY: "weekly", MONTHLY: "monthly"}

# task: cadence, agent (None = job prompt only), model tier, required profile
TASKS: dict[str, dict] = {
    "roadmap": {"cadence": "nightly", "agent": "implementer", "tier": "large"},
    "fork-prequal": {"cadence": "nightly", "agent": None, "tier": "medium"},
    "fork-adopt": {"cadence": "nightly", "agent": "implementer", "tier": "large"},
    "deps": {"cadence": "nightly", "agent": "implementer", "tier": "medium"},
    "dead-code": {"cadence": "weekly", "agent": "implementer", "tier": "medium"},
    "flaky": {"cadence": "weekly", "agent": "implementer", "tier": "medium"},
    "doc-drift": {"cadence": "weekly", "agent": "doc-writer", "tier": "medium"},
    "web-checks": {"cadence": "weekly", "agent": "implementer", "tier": "medium", "requires": "web"},
    "deprecations": {"cadence": "weekly", "agent": "implementer", "tier": "medium", "requires": "library"},
    "security-sweep": {"cadence": "monthly", "agent": "implementer", "tier": "large"},
    "ideas": {"cadence": "monthly", "agent": None, "tier": "small"},
}
DETERMINISTIC = {"audit": "weekly", "cleanup": "weekly", "fuzz": "nightly"}
DEP_BOTS = ("dependabot[bot]", "renovate[bot]")


def repo_name() -> str:
    return os.environ.get("GITHUB_REPOSITORY", "")


def now() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


# --------------------------------------------------------------------------- plan


def plan(schedule: str, task: str | None, profile: dict) -> dict:
    profiles = profile.get("profiles") or []
    if task:
        cadence_tasks = [task]
    else:
        cadence = CADENCE.get(schedule)
        if cadence is None:
            return {"model": [], "deterministic": [], "fuzz": False}
        cadence_tasks = [n for n, t in TASKS.items() if t["cadence"] == cadence] + [n for n, c in DETERMINISTIC.items() if c == cadence]
    model_tasks = []
    for name in cadence_tasks:
        meta = TASKS.get(name)
        if not meta:
            continue
        if meta.get("requires") and meta["requires"] not in profiles:
            continue
        if name == "doc-drift" and (govlib.dig(profile, "classification.api") or "none") == "none":
            continue
        model_tasks.append(name)
    deterministic = [n for n in cadence_tasks if n in ("audit", "cleanup")]
    fuzz = "fuzz" in cadence_tasks and bool(govlib.dig(profile, "fuzz.targets"))
    return {"model": model_tasks, "deterministic": deterministic, "fuzz": fuzz}


# --------------------------------------------------------------------------- helpers


def open_issues(repo: str, label: str) -> list[dict]:
    items = govlib.gh_api(f"repos/{repo}/issues?state=open&labels={label}&sort=created&direction=asc&per_page=100", paginate=True)
    return [i for i in items if "pull_request" not in i]


def open_prs(repo: str) -> list[dict]:
    return govlib.gh_api(f"repos/{repo}/pulls?state=open&sort=created&direction=asc&per_page=100", paginate=True)


def labels_of(item: dict) -> set[str]:
    return {lbl["name"] for lbl in item.get("labels", [])}


def commits_since(days: int, ref: str = "origin/main") -> int:
    govlib.run(["git", "fetch", "--no-tags", "--quiet", "origin", "+refs/heads/main:refs/remotes/origin/main"])
    proc = govlib.run(["git", "rev-list", "--count", f"--since={days} days ago", ref])
    return int(proc.stdout.strip() or 0) if proc.returncode == 0 else 0


def checks_state(repo: str, sha: str) -> str:
    runs = govlib.gh_api(f"repos/{repo}/commits/{sha}/check-runs?per_page=100").get("check_runs", [])
    if not runs or any(r["status"] != "completed" for r in runs):
        return "pending"
    if any(r["conclusion"] in ("failure", "timed_out", "cancelled", "action_required") for r in runs):
        return "red"
    return "green"


def run_profile_command(command: str, timeout: int = 1800) -> tuple[int, str]:
    proc = govlib.run(command, timeout=timeout)
    return proc.returncode, (proc.stdout + proc.stderr)


# --------------------------------------------------------------------------- checks (return run, vars, context)


def check_roadmap(repo: str, cfg: dict, profile: dict):
    wip = checks.count_feats(checks.unreleased_subjects())
    for issue in open_issues(repo, "po:ready"):
        lbls = labels_of(issue)
        if lbls & {"in-progress", "blocked", "po:decision"}:
            continue
        if "type:feature" in lbls and wip >= cfg["wip_limit"]:
            continue
        timeline = govlib.gh_api(f"repos/{repo}/issues/{issue['number']}/timeline?per_page=100", paginate=True)
        ok, _ = checks.po_ready_decision(timeline, list(lbls), cfg["owner"])
        if not ok:
            continue
        govlib.gh("issue", "edit", str(issue["number"]), "--repo", repo, "--add-label", "in-progress")
        return True, {"issue": str(issue["number"]), "wip": str(wip), "wip_limit": str(cfg["wip_limit"])}, None
    return False, {}, None


def check_fork_prequal(repo: str, cfg: dict, profile: dict):
    for pr in open_prs(repo):
        if (pr["head"].get("repo") or {}).get("full_name") == repo:
            continue
        if labels_of(pr) & {"po:review", "adopting"}:
            continue
        return True, {"pr": str(pr["number"])}, None
    return False, {}, None


def check_fork_adopt(repo: str, cfg: dict, profile: dict):
    for pr in open_prs(repo):
        if (pr["head"].get("repo") or {}).get("full_name") == repo or "adopting" in labels_of(pr):
            continue
        reviews = govlib.gh_api(f"repos/{repo}/pulls/{pr['number']}/reviews?per_page=100", paginate=True)
        owner = sorted([r for r in reviews if (r.get("user") or {}).get("login") == cfg["owner"] and r["state"] in ("APPROVED", "CHANGES_REQUESTED", "DISMISSED")], key=lambda r: r.get("submitted_at") or "")
        if owner and owner[-1]["state"] == "APPROVED":
            user = pr["user"]
            govlib.gh("pr", "edit", str(pr["number"]), "--repo", repo, "--add-label", "adopting")
            email = f"{user['id']}+{user['login']}@users.noreply.github.com"
            return True, {"pr": str(pr["number"]), "author": user["login"], "author_email": email}, None
    return False, {}, None


def check_deps(repo: str, cfg: dict, profile: dict):
    red = None
    for pr in open_prs(repo):
        if pr["user"]["login"] not in DEP_BOTS or pr["head"]["repo"]["full_name"] != repo:
            continue
        state = checks_state(repo, pr["head"]["sha"])
        if state == "green" and not pr.get("auto_merge"):
            govlib.gh("pr", "merge", str(pr["number"]), "--repo", repo, "--auto", "--squash", check=False)
            govlib.summary(f"Auto-merge enabled for #{pr['number']} ({pr['title']}).")
        elif state == "red" and red is None and "blocked" not in labels_of(pr):
            red = pr
    if red:
        return True, {"pr": str(red["number"]), "head": red["head"]["ref"]}, None
    return False, {}, None


def check_dead_code(repo: str, cfg: dict, profile: dict):
    command = govlib.dig(profile, "housekeeping.dead_code")
    if not command or commits_since(7) == 0:
        return False, {}, None
    code, output = run_profile_command(command)
    if code == 0 and not output.strip():
        return False, {}, None
    return True, {}, output


def check_flaky(repo: str, cfg: dict, profile: dict):
    since = (now() - dt.timedelta(days=7)).strftime("%Y-%m-%d")
    runs = govlib.gh_api(f"repos/{repo}/actions/runs?created=%3E%3D{since}&per_page=100").get("workflow_runs", [])
    lines = []
    for run in runs:
        if run.get("run_attempt", 1) > 1 and run.get("conclusion") == "success":
            jobs = govlib.gh_api(f"repos/{repo}/actions/runs/{run['id']}/attempts/1/jobs?per_page=100").get("jobs", [])
            for job in jobs:
                if job.get("conclusion") == "failure":
                    lines.append(f"{run['name']} / {job['name']} @ {run['head_sha'][:7]} — {job['html_url']}")
    return (True, {}, "\n".join(lines)) if lines else (False, {}, None)


def check_doc_drift(repo: str, cfg: dict, profile: dict):
    tool = govlib.dig(profile, "classification.api") or "none"
    if tool in ("none", "cargo-semver-checks"):
        return False, {}, None
    base = govlib.run(["git", "rev-list", "-1", "--before=7 days ago", "origin/main"]).stdout.strip()
    if not base or commits_since(7) == 0:
        return False, {}, None
    with tempfile.TemporaryDirectory(prefix="gov-drift-") as tmp:
        old_dir = os.path.join(tmp, "old")
        govlib.git("worktree", "add", "--detach", old_dir, base)
        try:
            old = classify_check.compute(old_dir, profile, tool, base)
        finally:
            govlib.run(["git", "worktree", "remove", "--force", old_dir])
        new = classify_check.compute(os.getcwd(), profile, tool, base)
    if old["api"] == new["api"]:
        return False, {}, None
    return True, {}, classify_check.diff_text("api", old["api"] or [], new["api"] or [])


def check_web(repo: str, cfg: dict, profile: dict):
    outputs = []
    for command in govlib.dig(profile, "housekeeping.web_checks") or []:
        code, output = run_profile_command(command)
        if code != 0:
            outputs.append(f"$ {command}\n{output[-6000:]}")
    return (True, {}, "\n\n".join(outputs)) if outputs else (False, {}, None)


def check_deprecations(repo: str, cfg: dict, profile: dict):
    from release_tools import parse_tag, stable_tags

    govlib.run(["git", "fetch", "--tags", "--quiet", "origin"])
    tags = stable_tags(govlib.git("tag", "--list").splitlines())
    if not tags:
        return False, {}, None
    latest = tags[-1]
    major, minor, patch, _ = parse_tag(latest)
    if major < 1 or minor or patch:
        return False, {}, None
    created = int(govlib.git("log", "-1", "--format=%ct", latest))
    if now().timestamp() - created > 7 * 86400:
        return False, {}, None
    return True, {"tag": latest}, None


def check_security_sweep(repo: str, cfg: dict, profile: dict):
    return (commits_since(30) > 0), {}, None


def check_ideas(repo: str, cfg: dict, profile: dict):
    owner, name = repo.split("/", 1)
    query = """query($owner:String!,$name:String!){repository(owner:$owner,name:$name){discussions(first:50,orderBy:{field:UPDATED_AT,direction:DESC}){nodes{title url upvoteCount createdAt updatedAt category{name}}}}}"""
    data = govlib.gh_graphql(query, owner=owner, name=name)
    cutoff = (now() - dt.timedelta(days=30)).isoformat()
    nodes = [n for n in data["data"]["repository"]["discussions"]["nodes"] if (n.get("category") or {}).get("name", "").lower() == "ideas" and n["updatedAt"] >= cutoff[:19]]
    if not nodes:
        return False, {}, None
    lines = [f"- {n['title']} — {n['url']} — upvotes: {n['upvoteCount']} — created {n['createdAt'][:10]}" for n in nodes]
    return True, {"month": now().strftime("%Y-%m")}, "\n".join(lines)


CHECKS = {
    "roadmap": check_roadmap,
    "fork-prequal": check_fork_prequal,
    "fork-adopt": check_fork_adopt,
    "deps": check_deps,
    "dead-code": check_dead_code,
    "flaky": check_flaky,
    "doc-drift": check_doc_drift,
    "web-checks": check_web,
    "deprecations": check_deprecations,
    "security-sweep": check_security_sweep,
    "ideas": check_ideas,
}


# --------------------------------------------------------------------------- deterministic tasks


def audit_issue(repo: str, report_path: str) -> int:
    report = json.loads(Path(report_path).read_text(encoding="utf-8"))
    failed = [c for c in report.get("checks", []) if c["status"] == "fail"]
    title = "Governance audit failed"
    existing = [i for i in open_issues(repo, "po:decision") if i["title"] == title]
    if not failed:
        for issue in existing:
            govlib.gh("issue", "close", str(issue["number"]), "--repo", repo, "--comment", "Governance audit passes again.")
        return 0
    body = "The weekly governance audit failed. Run the onboarding prompt (`prompts/onboard.md` in nullthrone/governance) to restore compliance.\n\n"
    body += "\n".join(f"- **{c['id']}**: {c['message']}" for c in failed)
    if existing:
        govlib.gh("issue", "edit", str(existing[0]["number"]), "--repo", repo, "--body", body)
    else:
        govlib.gh("issue", "create", "--repo", repo, "--title", title, "--label", "po:decision", "--body", body)
    return 0


def cleanup(repo: str, cfg: dict) -> int:
    keep_prefixes = ("release-please--", "gh-pages", "dependabot/", "renovate/")
    open_heads = {pr["head"]["ref"] for pr in open_prs(repo) if (pr["head"].get("repo") or {}).get("full_name") == repo}
    for branch in govlib.gh_api(f"repos/{repo}/branches?per_page=100", paginate=True):
        name = branch["name"]
        if name in ("main", "next") or name.startswith(keep_prefixes) or name in open_heads or branch.get("protected"):
            continue
        merged = False
        for base in ("main", "next"):
            try:
                cmp = govlib.gh_api(f"repos/{repo}/compare/{base}...{name}")
            except govlib.GhError:
                continue
            if cmp.get("ahead_by") == 0:
                merged = True
                break
        if merged:
            govlib.gh("api", "-X", "DELETE", f"repos/{repo}/git/refs/heads/{name}", check=False)
            govlib.summary(f"Deleted merged branch {name}")
    cutoff = now() - dt.timedelta(days=cfg["stale_bot_pr_days"])
    for pr in open_prs(repo):
        if pr["user"]["login"] not in cfg["bots"] or pr["head"].get("ref") in ("main", "next"):
            continue
        updated = dt.datetime.fromisoformat(pr["updated_at"].replace("Z", "+00:00"))
        if updated < cutoff:
            govlib.gh("pr", "close", str(pr["number"]), "--repo", repo, "--delete-branch", "--comment", f"Closed automatically: no activity for {cfg['stale_bot_pr_days']} days.", check=False)
            govlib.summary(f"Closed stale PR #{pr['number']}")
    return 0


# --------------------------------------------------------------------------- CLI


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("plan")
    p.add_argument("--schedule", default="")
    p.add_argument("--task", default="")
    c = sub.add_parser("check")
    c.add_argument("task", choices=sorted(CHECKS))
    out_dir = os.environ.get("RUNNER_TEMP", tempfile.gettempdir())
    c.add_argument("--context-out", default=os.path.join(out_dir, "housekeeping-context.txt"))
    c.add_argument("--vars-out", default=os.path.join(out_dir, "housekeeping-vars.json"))
    a = sub.add_parser("audit-issue")
    a.add_argument("--report", required=True)
    sub.add_parser("cleanup")
    args = parser.parse_args(argv)

    cfg = govlib.load_config()
    profile = govlib.load_profile(".")
    repo = repo_name()
    if args.cmd == "plan":
        result = plan(args.schedule, args.task or None, profile)
        govlib.set_output("model_tasks", json.dumps(result["model"]))
        govlib.set_output("deterministic", json.dumps(result["deterministic"]))
        govlib.set_output("fuzz", str(result["fuzz"]).lower())
        govlib.summary(f"Plan: {json.dumps(result)}")
        return 0
    if args.cmd == "check":
        meta = TASKS[args.task]
        should_run, variables, context = CHECKS[args.task](repo, cfg, profile)
        variables = {"repo": repo, **variables}
        Path(args.context_out).write_text(context or "", encoding="utf-8")
        govlib.set_output("run", str(bool(should_run)).lower())
        Path(args.vars_out).write_text(json.dumps(variables), encoding="utf-8")
        govlib.set_output("agent", meta["agent"] or "")
        govlib.set_output("tier", meta["tier"])
        govlib.set_output("context_file", args.context_out if context else "")
        govlib.summary(f"{args.task}: {'run Claude' if should_run else 'nothing to do'}")
        return 0
    if args.cmd == "audit-issue":
        return audit_issue(repo, args.report)
    if args.cmd == "cleanup":
        return cleanup(repo, cfg)
    return 1


if __name__ == "__main__":
    sys.exit(main())
