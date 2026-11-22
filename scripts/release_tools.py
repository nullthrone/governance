#!/usr/bin/env python3
"""Release helpers for the reusable workflows.

  rc-version       next release-candidate version for the current next branch (vX.Y.Z-rc.N)
  version-smoke    run the profile's version command and require the expected version in its output
  previous-tag     stable tag released before the given tag (rollback target)
  candidate-body   body of the candidate PR next -> main
  release-gate     may the release PR auto-merge? Patches yes; minor/major only after an
                   owner-accepted candidate merge since the last release
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import govlib  # noqa: E402

TAG_RE = re.compile(r"^v?(\d+)\.(\d+)\.(\d+)(?:-rc\.(\d+))?$")
PR_REF_RE = re.compile(r"\(#(\d+)\)\s*$")
TEST_SECTION_RE = re.compile(r"^##+\s*Test\b.*?$\n(?P<body>.*?)(?=^##+\s|\Z)", re.MULTILINE | re.DOTALL | re.IGNORECASE)


def parse_tag(tag: str) -> tuple[int, int, int, int | None] | None:
    m = TAG_RE.match(tag.strip())
    if not m:
        return None
    return int(m.group(1)), int(m.group(2)), int(m.group(3)), (int(m.group(4)) if m.group(4) else None)


def stable_tags(tags: list[str]) -> list[str]:
    parsed = [(parse_tag(t), t) for t in tags]
    stable = [(p, t) for p, t in parsed if p and p[3] is None]
    return [t for _, t in sorted(stable, key=lambda x: x[0][:3])]


def next_rc(tags: list[str], subjects: list[str]) -> str:
    stable = stable_tags(tags)
    major, minor, patch = parse_tag(stable[-1])[:3] if stable else (0, 0, 0)
    parsed = [govlib.parse_cc(s) for s in subjects]
    breaking = any(p and p["breaking"] for p in parsed) or any("BREAKING CHANGE" in s for s in subjects)
    if breaking and major > 0:
        target = (major + 1, 0, 0)
    elif any(p and p["type"] == "feat" for p in parsed) or breaking:
        target = (major, minor + 1, 0)
    else:
        target = (major, minor, patch + 1)
    existing = [p[3] for p in (parse_tag(t) for t in tags) if p and p[:3] == target and p[3] is not None]
    n = max(existing, default=0) + 1
    return f"{target[0]}.{target[1]}.{target[2]}-rc.{n}"


def previous_tag(tags: list[str], current: str) -> str | None:
    stable = stable_tags(tags)
    cur = parse_tag(current)
    older = [t for t in stable if cur and parse_tag(t)[:3] < cur[:3]]
    return older[-1] if older else None


def version_in_output(expected: str, output: str) -> bool:
    expected = expected.lstrip("v")
    return re.search(rf"(?<![0-9A-Za-z.]){re.escape(expected)}(?![0-9A-Za-z.-])|(?<![0-9A-Za-z.])v{re.escape(expected)}(?![0-9A-Za-z.-])", output) is not None


def test_steps(body: str, limit: int = 3) -> list[str]:
    m = TEST_SECTION_RE.search(body or "")
    if not m:
        return []
    steps = []
    for line in m.group("body").splitlines():
        line = line.strip()
        if re.match(r"^(?:\d+[.)]|[-*])\s+", line):
            steps.append(re.sub(r"^(?:\d+[.)]|[-*])\s+", "", line))
    return steps[:limit]


def candidate_body(version: str, features: list[dict], preview: str, screenshots: str, run_url: str) -> str:
    lines = [f"## Release candidate {version}", "", "Approve this PR to release. Merge and minor release run automatically.", "", "### Changes", ""]
    for feat in features:
        ref = f" (#{feat['pr']})" if feat.get("pr") else ""
        lines.append(f"- {feat['subject']}{'' if ref and ref.strip() in feat['subject'] else ref}")
    lines += ["", "### Preview", "", preview or f"Build artifacts: {run_url}", ""]
    lines += ["### Test script", ""]
    any_steps = False
    for feat in features:
        if feat.get("steps"):
            any_steps = True
            lines.append(f"**{feat['subject']}**")
            lines += [f"{i}. {step}" for i, step in enumerate(feat["steps"], 1)]
            lines.append("")
    if not any_steps:
        lines += ["_No test steps provided by the feature PRs._", ""]
    lines += ["### Screenshots", "", screenshots or "_None for this project type._", ""]
    lines += ["Feedback: comment on this PR; Claude corrects on `next`.", ""]
    return "\n".join(lines)


def bump_kind(previous: str | None, new: str) -> str:
    old = parse_tag(previous) if previous else (0, 0, 0, None)
    cur = parse_tag(new)
    if cur is None or old is None:
        return "unknown"
    if cur[0] != old[0]:
        return "major"
    if cur[1] != old[1]:
        return "minor"
    return "patch"


def accepted_candidate(merged_candidates: list[dict], reviews_by_pr: dict[int, list[dict]], owner: str, since: str | None) -> int | None:
    """Number of a candidate PR merged after `since` whose latest owner review approved its final head."""
    for pr in merged_candidates:
        if not pr.get("merged_at") or (since and pr["merged_at"] <= since):
            continue
        reviews = sorted((r for r in reviews_by_pr.get(pr["number"], []) if (r.get("user") or {}).get("login") == owner and r.get("state") in ("APPROVED", "CHANGES_REQUESTED", "DISMISSED")), key=lambda r: r.get("submitted_at") or "")
        if reviews and reviews[-1]["state"] == "APPROVED" and reviews[-1].get("commit_id") == pr["head"]["sha"]:
            return pr["number"]
    return None


def git_tags(repo_dir: str) -> list[str]:
    govlib.run(["git", "fetch", "--tags", "--quiet", "origin"], cwd=repo_dir)
    return [t for t in govlib.git("tag", "--list", cwd=repo_dir).splitlines() if t]


def cmd_rc_version(args) -> int:
    subjects = govlib.git("log", "--no-merges", "--format=%s", "origin/main..origin/next", cwd=args.repo_dir).splitlines()
    version = next_rc(git_tags(args.repo_dir), subjects)
    govlib.set_output("version", version)
    govlib.set_output("tag", f"v{version}")
    print(version)
    return 0


def cmd_version_smoke(args) -> int:
    expected = args.expected
    if args.expected_from_manifest:
        manifest = json.loads(Path(args.repo_dir, ".release-please-manifest.json").read_text())
        expected = manifest.get(".") or next(iter(manifest.values()))
    command = args.command or govlib.dig(govlib.load_profile(args.repo_dir), "commands.version")
    if not command:
        return govlib.fail("No version command (commands.version in .governance/profile.yml).")
    if not expected or expected == "0.0.0":
        govlib.summary(f"ℹ️ No released version yet; only checking that `{command}` runs.")
        proc = govlib.run(command, cwd=args.repo_dir)
        return 0 if proc.returncode == 0 else govlib.fail(f"`{command}` failed: {proc.stderr.strip()}")
    proc = govlib.run(command, cwd=args.repo_dir)
    output = proc.stdout + proc.stderr
    if proc.returncode != 0 or not version_in_output(expected, output):
        return govlib.fail(f"Version smoke test: `{command}` must report {expected}, got: {output.strip()[:300]!r}")
    govlib.summary(f"✅ `{command}` reports {expected}.")
    return 0


def cmd_previous_tag(args) -> int:
    prev = previous_tag(git_tags(args.repo_dir), args.current)
    govlib.set_output("tag", prev or "")
    print(prev or "")
    return 0 if prev else govlib.fail(f"No stable tag before {args.current}.")


def cmd_candidate_body(args) -> int:
    log = govlib.git("log", "--no-merges", "--format=%s", "origin/main..origin/next", cwd=args.repo_dir).splitlines()
    features = []
    for subject in log:
        if not govlib.is_feat(subject):
            continue
        m = PR_REF_RE.search(subject)
        feat = {"subject": subject, "pr": m.group(1) if m else None, "steps": []}
        if m and args.repo:
            try:
                body = govlib.gh_api(f"repos/{args.repo}/pulls/{m.group(1)}").get("body") or ""
                feat["steps"] = test_steps(body)
            except govlib.GhError:
                pass
        features.append(feat)
    text = candidate_body(args.version, list(reversed(features)), args.preview, args.screenshots, args.run_url)
    Path(args.output).write_text(text, encoding="utf-8")
    govlib.set_output("feature_count", str(len(features)))
    govlib.set_output("pr_numbers", " ".join(f["pr"] for f in features if f["pr"]))
    return 0


def cmd_release_gate(args) -> int:
    repo = args.repo
    owner = govlib.load_config()["owner"]
    pr = govlib.gh_api(f"repos/{repo}/pulls/{args.pr}")
    m = re.search(r"(\d+\.\d+\.\d+)\s*$", pr.get("title", ""))
    if not m:
        govlib.set_output("allowed", "false")
        return govlib.fail(f"Cannot read the version from the release PR title {pr.get('title')!r}.")
    try:
        latest = govlib.gh_api(f"repos/{repo}/releases/latest")
        previous, since = latest.get("tag_name"), latest.get("published_at")
    except govlib.GhError:
        previous, since = None, None
    kind = bump_kind(previous, m.group(1))
    if kind == "patch":
        govlib.set_output("allowed", "true")
        govlib.summary(f"✅ Patch release {m.group(1)}: auto-merge allowed.")
        return 0
    closed = govlib.gh_api(f"repos/{repo}/pulls?state=closed&base=main&sort=updated&direction=desc&per_page=100", paginate=True)
    candidates = [p for p in closed if p["head"]["ref"] == "next" and (p["head"].get("repo") or {}).get("full_name") == repo and p.get("merged_at")]
    reviews = {p["number"]: govlib.gh_api(f"repos/{repo}/pulls/{p['number']}/reviews?per_page=100", paginate=True) for p in candidates if not since or p["merged_at"] > since}
    accepted = accepted_candidate(candidates, reviews, owner, since)
    if accepted:
        govlib.set_output("allowed", "true")
        govlib.summary(f"✅ {kind} release {m.group(1)} backed by owner-accepted candidate #{accepted}.")
        return 0
    govlib.set_output("allowed", "false")
    govlib.summary(f"⛔ {kind} release {m.group(1)} without an owner-accepted candidate since {previous or 'the beginning'}; auto-merge withheld.")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--repo-dir", default=".")
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("rc-version")
    vs = sub.add_parser("version-smoke")
    vs.add_argument("--expected")
    vs.add_argument("--expected-from-manifest", action="store_true")
    vs.add_argument("--command")
    pt = sub.add_parser("previous-tag")
    pt.add_argument("--current", required=True)
    cb = sub.add_parser("candidate-body")
    cb.add_argument("--repo")
    cb.add_argument("--version", required=True)
    cb.add_argument("--preview", default="")
    cb.add_argument("--screenshots", default="")
    cb.add_argument("--run-url", default="")
    cb.add_argument("--output", required=True)
    rg = sub.add_parser("release-gate")
    rg.add_argument("--repo", required=True)
    rg.add_argument("--pr", required=True, type=int)
    args = parser.parse_args(argv)
    return {
        "rc-version": cmd_rc_version,
        "version-smoke": cmd_version_smoke,
        "previous-tag": cmd_previous_tag,
        "candidate-body": cmd_candidate_body,
        "release-gate": cmd_release_gate,
    }[args.cmd](args)


if __name__ == "__main__":
    sys.exit(main())
