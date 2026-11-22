#!/usr/bin/env python3
"""Deterministic pull-request and issue checks used by the reusable workflows.

Subcommands (all read GITHUB_REPOSITORY and the event payload; --repo/--pr override):
  guard               governance-guard: protected paths only from the owner
  title               Conventional Commit PR title, allowed type per base branch, breaking needs verified po:ready
  docs                docs-required: feat PRs into next touch docs/ or README, or carry docs:none
  wip                 wip-limit: at most N unreleased feats on next
  gate                external-contribution-gate: non-owner, non-bot PRs need the owner's approval
  candidate-approval  next -> main needs the owner's approval on the current head commit
  review-mode         decide whether the Claude review runs (review|skip|fork|limit)
  review-verdict      extract the verdict from the Claude execution file and post the review
  po-ready            verify that the owner applied po:ready (optionally remove it if not)
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import govlib  # noqa: E402

REVIEW_MARKER = "<!-- governance-review verdict={verdict} -->"
REVIEW_MARKER_RE = re.compile(r"<!-- governance-review verdict=(\w+) -->")
CLOSES_RE = re.compile(r"\b(?:close[sd]?|fix(?:e[sd])?|resolve[sd]?)\s+#(\d+)\b", re.IGNORECASE)


# --------------------------------------------------------------------------- context


class PR:
    def __init__(self, data: dict, repo: str):
        self.data = data
        self.repo = repo
        self.number = data["number"]
        self.author = (data.get("user") or {}).get("login", "")
        self.title = data.get("title") or ""
        self.body = data.get("body") or ""
        self.base = data["base"]["ref"]
        self.head = data["head"]["ref"]
        self.head_sha = data["head"]["sha"]
        head_repo = (data["head"].get("repo") or {}).get("full_name")
        self.same_repo = head_repo == repo
        self.labels = [lbl["name"] for lbl in data.get("labels", [])]

    @property
    def is_promotion(self) -> bool:
        return self.same_repo and {self.head, self.base} == {"main", "next"}

    @property
    def is_candidate(self) -> bool:
        return self.same_repo and self.head == "next" and self.base == "main"


def load_pr(args) -> PR:
    repo = args.repo or os.environ.get("GITHUB_REPOSITORY", "")
    if args.pr:
        return PR(govlib.gh_api(f"repos/{repo}/pulls/{args.pr}"), repo)
    payload = govlib.event_payload()
    if "pull_request" not in payload:
        raise SystemExit(govlib.fail("no pull_request in event payload; pass --pr"))
    # Payload can be stale for labels/title on re-runs; fetch fresh state.
    number = payload["pull_request"]["number"]
    return PR(govlib.gh_api(f"repos/{repo}/pulls/{number}"), repo)


def pr_files(pr: PR) -> list[str]:
    names: list[str] = []
    for item in govlib.gh_api(f"repos/{pr.repo}/pulls/{pr.number}/files?per_page=100", paginate=True):
        names.append(item["filename"])
        if item.get("previous_filename"):
            names.append(item["previous_filename"])
    return names


def owner_reviews(pr: PR, owner: str) -> list[dict]:
    reviews = govlib.gh_api(f"repos/{pr.repo}/pulls/{pr.number}/reviews?per_page=100", paginate=True)
    relevant = [r for r in reviews if (r.get("user") or {}).get("login") == owner and r.get("state") in ("APPROVED", "CHANGES_REQUESTED", "DISMISSED")]
    return sorted(relevant, key=lambda r: r.get("submitted_at") or "")


# --------------------------------------------------------------------------- pure decisions (unit-tested)


def is_protected(path: str, protected: list[str]) -> bool:
    for entry in protected:
        if entry.endswith("/"):
            if path.startswith(entry):
                return True
        elif path == entry or path.endswith("/" + entry) and entry == "CLAUDE.md":
            return True
    return False


def guard_decision(files: list[str], author: str, commit_authors: list[str | None], owner: str, protected: list[str], promotion: bool) -> tuple[bool, str]:
    touched = sorted({f for f in files if is_protected(f, protected)})
    if not touched:
        return True, "No governance-protected paths changed."
    if promotion:
        return True, "Promotion between main and next; protected changes were checked when they entered the source branch."
    if author != owner:
        return False, f"PR author '{author}' is not the owner; protected paths changed: {', '.join(touched)}"
    foreign = sorted({a or "<unlinked>" for a in commit_authors if a != owner})
    if foreign:
        return False, f"Commits by {', '.join(foreign)} in a PR that changes protected paths ({', '.join(touched)})"
    return True, f"Owner changed protected paths: {', '.join(touched)}"


def title_decision(title: str, base: str, allowed: dict[str, list[str]], promotion: bool) -> tuple[bool, str, dict | None]:
    if promotion:
        return True, "Promotion PR; title not checked.", None
    parsed = govlib.parse_cc(title)
    if not parsed:
        return False, f"PR title is not a Conventional Commit: '{title}' (expected 'type(scope)?: description')", None
    types = allowed.get(base)
    if types is not None and parsed["type"] not in types:
        hint = " Features go to next." if parsed["type"] == "feat" and base == "main" else ""
        return False, f"Type '{parsed['type']}' is not allowed into {base} (allowed: {', '.join(types)}).{hint}", parsed
    return True, f"Title OK ({parsed['type']} into {base}).", parsed


def docs_decision(title: str, base: str, files: list[str], labels: list[str]) -> tuple[bool, str]:
    if base != "next" or not govlib.is_feat(title):
        return True, "Not a feature PR into next; docs not required."
    if "docs:none" in labels:
        return True, "docs:none set; the reviewer checks the justification."
    docs = [f for f in files if f.startswith("docs/") or re.match(r"^(?:.*/)?README(?:\.[A-Za-z]+)?$", f)]
    if docs:
        return True, f"Docs changed: {', '.join(docs[:5])}"
    return False, "Feature PR without user docs: change docs/ or README, or label docs:none and justify it in the PR body."


def count_feats(subjects: list[str]) -> int:
    return sum(1 for s in subjects if govlib.is_feat(s))


def wip_decision(title: str, base: str, unreleased_feats: int, limit: int) -> tuple[bool, str]:
    if base != "next" or not govlib.is_feat(title):
        return True, "Not a feature PR into next."
    if unreleased_feats >= limit:
        return False, f"WIP limit reached: {unreleased_feats} unreleased features on next (limit {limit}). Wait for the candidate release."
    return True, f"{unreleased_feats} unreleased features on next (limit {limit})."


def gate_decision(author: str, owner: str, bots: list[str], reviews: list[dict]) -> tuple[bool, str]:
    if author == owner or author in bots:
        return True, f"Author '{author}' is the owner or a governance bot."
    latest = reviews[-1] if reviews else None
    if latest and latest.get("state") == "APPROVED":
        return True, "The owner approved this external contribution (roadmap decision)."
    return False, f"External contribution by '{author}': waiting for the owner's approval (roadmap decision)."


def candidate_decision(is_candidate: bool, head_sha: str, reviews: list[dict]) -> tuple[bool, str]:
    if not is_candidate:
        return True, "Not a candidate PR."
    latest = reviews[-1] if reviews else None
    if latest and latest.get("state") == "APPROVED" and latest.get("commit_id") == head_sha:
        return True, "The owner accepted this candidate at the current head commit."
    if latest and latest.get("state") == "APPROVED":
        return False, "The owner's approval is for an older commit; next changed since. Approval needed again."
    return False, "Candidate waiting for the owner's acceptance."


def review_mode(pr: PR, bots_without_review: list[str], previous_rejections: int, max_rounds: int) -> tuple[str, str]:
    if pr.is_promotion:
        return "skip", "Promotion PR: content was reviewed when it entered the source branch."
    if pr.same_repo and pr.head.startswith("release-please--"):
        return "skip", "release-please PR: version and changelog only."
    if pr.author in bots_without_review:
        return "skip", f"{pr.author} PR: deterministic checks only; red updates are fixed by the deps housekeeping job."
    if not pr.same_repo:
        return "fork", "Fork PR: never reviewed or merged directly. After the owner's approval Claude ports it to an own branch."
    if previous_rejections >= max_rounds:
        return "limit", f"{previous_rejections} review rounds requested changes (limit {max_rounds}); labeled blocked."
    return "review", "Claude review."


def po_ready_decision(timeline: list[dict], current_labels: list[str], owner: str) -> tuple[bool, str]:
    if "po:ready" not in current_labels:
        return False, "Issue does not carry po:ready."
    actor = None
    for event in timeline:
        if event.get("event") == "labeled" and (event.get("label") or {}).get("name") == "po:ready":
            actor = (event.get("actor") or {}).get("login")
    if actor == owner:
        return True, "po:ready applied by the owner."
    return False, f"po:ready was applied by '{actor}', not by the owner."


def extract_verdict(text: str) -> tuple[dict | None, str]:
    """Return the last JSON verdict line and the review text without it."""
    lines = text.rstrip().splitlines()
    for idx in range(len(lines) - 1, -1, -1):
        candidate = lines[idx].strip().strip("`")
        if candidate.startswith("{") and '"verdict"' in candidate:
            try:
                verdict = json.loads(candidate)
            except json.JSONDecodeError:
                continue
            if verdict.get("verdict") in ("approve", "request_changes"):
                body = "\n".join(lines[:idx]).rstrip().rstrip("`").rstrip()
                return verdict, body
    return None, text


def final_text_from_execution(path: str) -> str:
    with open(path, encoding="utf-8") as fh:
        data = json.load(fh)
    messages = data if isinstance(data, list) else data.get("messages", [])
    for msg in reversed(messages):
        if msg.get("type") == "result" and isinstance(msg.get("result"), str):
            return msg["result"]
    for msg in reversed(messages):
        if msg.get("type") == "assistant":
            content = (msg.get("message") or {}).get("content") or []
            texts = [c.get("text", "") for c in content if c.get("type") == "text"]
            if texts:
                return "\n".join(texts)
    return ""


# --------------------------------------------------------------------------- commands


def report(ok: bool, message: str) -> int:
    if ok:
        govlib.summary(f"✅ {message}")
        return 0
    return govlib.fail(message)


def cmd_guard(args) -> int:
    cfg = govlib.load_config()
    pr = load_pr(args)
    files = pr_files(pr)
    commits = govlib.gh_api(f"repos/{pr.repo}/pulls/{pr.number}/commits?per_page=100", paginate=True)
    authors = [(c.get("author") or {}).get("login") for c in commits]
    ok, msg = guard_decision(files, pr.author, authors, cfg["owner"], cfg["protected_paths"], pr.is_promotion)
    return report(ok, msg)


def cmd_title(args) -> int:
    cfg = govlib.load_config()
    pr = load_pr(args)
    ok, msg, parsed = title_decision(pr.title, pr.base, cfg["commit_types"], pr.is_promotion)
    if ok and parsed and parsed["breaking"]:
        issues = CLOSES_RE.findall(pr.body)
        if not issues:
            return report(False, "Breaking change must close an issue that the owner released with po:ready after a po:decision.")
        for number in issues:
            issue = govlib.gh_api(f"repos/{pr.repo}/issues/{number}")
            timeline = govlib.gh_api(f"repos/{pr.repo}/issues/{number}/timeline?per_page=100", paginate=True)
            good, why = po_ready_decision(timeline, [lbl["name"] for lbl in issue.get("labels", [])], cfg["owner"])
            if not good:
                return report(False, f"Breaking change: issue #{number}: {why}")
        msg += " Breaking change backed by owner-released issue."
    return report(ok, msg)


def cmd_docs(args) -> int:
    pr = load_pr(args)
    ok, msg = docs_decision(pr.title, pr.base, pr_files(pr), pr.labels)
    return report(ok, msg)


def unreleased_subjects(repo_dir: str = ".") -> list[str]:
    for ref in ("main", "next"):
        govlib.run(["git", "fetch", "--no-tags", "--quiet", "origin", f"+refs/heads/{ref}:refs/remotes/origin/{ref}"], cwd=repo_dir)
    proc = govlib.run(["git", "log", "--no-merges", "--format=%s", "origin/main..origin/next"], cwd=repo_dir)
    return [line for line in proc.stdout.splitlines() if line.strip()] if proc.returncode == 0 else []


def cmd_wip(args) -> int:
    cfg = govlib.load_config()
    pr = load_pr(args)
    count = count_feats(unreleased_subjects())
    ok, msg = wip_decision(pr.title, pr.base, count, cfg["wip_limit"])
    return report(ok, msg)


def cmd_gate(args) -> int:
    cfg = govlib.load_config()
    pr = load_pr(args)
    ok, msg = gate_decision(pr.author, cfg["owner"], cfg["bots"], owner_reviews(pr, cfg["owner"]))
    return report(ok, msg)


def cmd_candidate(args) -> int:
    cfg = govlib.load_config()
    pr = load_pr(args)
    reviews = owner_reviews(pr, cfg["owner"]) if pr.is_candidate else []
    ok, msg = candidate_decision(pr.is_candidate, pr.head_sha, reviews)
    return report(ok, msg)


def cmd_review_mode(args) -> int:
    cfg = govlib.load_config()
    pr = load_pr(args)
    rejections = 0
    if pr.same_repo:
        reviews = govlib.gh_api(f"repos/{pr.repo}/pulls/{pr.number}/reviews?per_page=100", paginate=True)
        rejections = sum(1 for r in reviews if (m := REVIEW_MARKER_RE.search(r.get("body") or "")) and m.group(1) == "request_changes")
    mode, why = review_mode(pr, ["dependabot[bot]", "renovate[bot]"], rejections, cfg["review_max_rounds"])
    govlib.set_output("mode", mode)
    govlib.set_output("author_is_bot", str(pr.author in cfg["bots"]).lower())
    govlib.set_output("pr", str(pr.number))
    govlib.summary(f"Review mode: **{mode}** — {why}")
    if mode == "limit":
        govlib.gh("pr", "edit", str(pr.number), "--repo", pr.repo, "--add-label", "blocked", check=False)
    return 0


def cmd_review_verdict(args) -> int:
    pr = load_pr(args)
    text = final_text_from_execution(args.execution_file) if args.execution_file and os.path.exists(args.execution_file) else ""
    verdict, body = extract_verdict(text)
    if verdict is None:
        return govlib.fail("Claude review produced no parseable verdict line.")
    marker = REVIEW_MARKER.format(verdict=verdict["verdict"])
    review_body = f"{body}\n\n**Verdict:** {verdict['verdict']} — {verdict.get('summary', '')}\n\n{marker}"
    if not args.dry_run:
        govlib.gh("pr", "review", str(pr.number), "--repo", pr.repo, "--comment", "--body", review_body)
    govlib.set_output("verdict", verdict["verdict"])
    if verdict["verdict"] != "approve" or not verdict.get("classification_ok", True):
        return govlib.fail(f"Claude review requested changes: {verdict.get('summary', '')}")
    govlib.summary(f"✅ Claude review approved: {verdict.get('summary', '')}")
    return 0


def cmd_po_ready(args) -> int:
    cfg = govlib.load_config()
    repo = args.repo or os.environ.get("GITHUB_REPOSITORY", "")
    number = args.issue or (govlib.event_payload().get("issue") or {}).get("number")
    if not number:
        return govlib.fail("no issue number")
    issue = govlib.gh_api(f"repos/{repo}/issues/{number}")
    timeline = govlib.gh_api(f"repos/{repo}/issues/{number}/timeline?per_page=100", paginate=True)
    ok, msg = po_ready_decision(timeline, [lbl["name"] for lbl in issue.get("labels", [])], cfg["owner"])
    govlib.set_output("approved", str(ok).lower())
    if not ok and args.enforce and "po:ready" in [lbl["name"] for lbl in issue.get("labels", [])]:
        govlib.gh("issue", "edit", str(number), "--repo", repo, "--remove-label", "po:ready")
        govlib.gh("issue", "comment", str(number), "--repo", repo, "--body", "Removed `po:ready`: only the owner can release issues for implementation.")
    return report(ok, msg)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--repo")
    parser.add_argument("--pr", type=int)
    sub = parser.add_subparsers(dest="cmd", required=True)
    for name in ("guard", "title", "docs", "wip", "gate", "candidate-approval", "review-mode"):
        sub.add_parser(name)
    rv = sub.add_parser("review-verdict")
    rv.add_argument("--execution-file")
    rv.add_argument("--dry-run", action="store_true")
    po = sub.add_parser("po-ready")
    po.add_argument("--issue", type=int)
    po.add_argument("--enforce", action="store_true")
    args = parser.parse_args(argv)
    handlers = {
        "guard": cmd_guard,
        "title": cmd_title,
        "docs": cmd_docs,
        "wip": cmd_wip,
        "gate": cmd_gate,
        "candidate-approval": cmd_candidate,
        "review-mode": cmd_review_mode,
        "review-verdict": cmd_review_verdict,
        "po-ready": cmd_po_ready,
    }
    try:
        return handlers[args.cmd](args)
    except govlib.GhError as exc:
        return govlib.fail(str(exc))


if __name__ == "__main__":
    sys.exit(main())
