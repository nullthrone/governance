#!/usr/bin/env python3
"""PreToolUse guard for governed repositories.

Blocks (exit code 2, reason on stderr):
  * Edit/Write/MultiEdit/NotebookEdit on governance-protected paths
  * shell commands that write to protected paths (heuristic)
  * force pushes, history rewrites, deletion of main/next
  * commands that print secrets

This hook only saves tokens. Enforcement is the governance-guard check in CI.
The owner can disable it for an onboarding session by starting Claude Code with
GOVERNANCE_OWNER_SESSION=1 in the environment.
"""
from __future__ import annotations

import json
import os
import re
import shlex
import sys

PROTECTED_DIRS = (".claude/", ".github/", ".governance/")
PROTECTED_FILES = ("CLAUDE.md", "CLAUDE.local.md")
EDIT_TOOLS = {"Edit", "Write", "MultiEdit", "NotebookEdit"}

SECRET_NAME = r"[A-Za-z_]*(?:TOKEN|SECRET|PASSWORD|PASSWD|PRIVATE_KEY|API_KEY|APIKEY|CREDENTIAL|AUTH)[A-Za-z0-9_]*"

DESTRUCTIVE_PATTERNS: list[tuple[str, str]] = [
    (r"\bgit\b[^;&|]*\bpush\b[^;&|]*(?:\s--force\b|\s--force-with-lease\b|\s--force-if-includes\b|\s-[a-zA-Z]*f[a-zA-Z]*\b|\s--mirror\b)", "force push"),
    (r"\bgit\b[^;&|]*\bpush\b[^;&|]*\s\+\S+", "force push via +refspec"),
    (r"\bgit\b[^;&|]*\bpush\b[^;&|]*(?:\s--delete\b|\s-d\b)[^;&|]*\b(?:main|next)\b", "deleting main/next"),
    (r"\bgit\b[^;&|]*\bpush\b[^;&|]*\s:(?:refs/heads/)?(?:main|next)\b", "deleting main/next"),
    (r"\bgit\b[^;&|]*\bfilter-(?:branch|repo)\b", "history rewrite"),
    (r"\bgit\b[^;&|]*\breflog\s+(?:expire|delete)\b", "history rewrite"),
    (r"\bgit\b[^;&|]*\bupdate-ref\b[^;&|]*\brefs/heads/(?:main|next)\b", "rewriting main/next"),
    (r"\bgit\b[^;&|]*\bbranch\b[^;&|]*\s-(?:D|d|-delete)\b[^;&|]*\b(?:main|next)\b", "deleting main/next"),
    (r"\bgh\s+api\b[^;&|]*-X\s*DELETE\b[^;&|]*/(?:git/refs/heads/(?:main|next)|rulesets|branches/[^/\s]+/protection)", "deleting refs or rulesets"),
    (r"\bgh\s+(?:repo\s+delete|secret\s+(?:set|delete)|variable\s+(?:set|delete))\b", "repository/secret administration"),
]

SECRET_PATTERNS: list[tuple[str, str]] = [
    (r"(?:^|[;&|(]\s*)printenv\b", "printing the environment"),
    (r"(?:^|[;&|(]\s*)env\s*(?:$|[;&|>])", "printing the environment"),
    (r"(?:^|[;&|(]\s*)(?:export\s+-p|declare\s+-[a-zA-Z]*[px]|set)\s*(?:$|[;&|>])", "printing the environment"),
    (r"/proc/[^\s]*/environ", "reading process environment"),
    (r"\bgh\s+auth\s+(?:token|status\b[^;&|]*(?:-t\b|--show-token))", "printing a token"),
    (r"\bgit\s+credential\b|\bgit\b[^;&|]*config\b[^;&|]*credential", "reading git credentials"),
    (r"\b(?:echo|printf|cat\s*<<<|print)\b[^;&|]*\$\{?" + SECRET_NAME, "printing a secret variable"),
    (r"\b(?:cat|less|more|head|tail|bat|xxd|base64|strings|grep)\b[^;&|]*(?:\.env\b|\.pem\b|\bid_(?:rsa|ed25519|ecdsa)\b|\.netrc\b|\.pypirc\b|\.npmrc\b|gh/hosts\.yml|\.git-credentials\b|\.claude/\.credentials)", "printing credential files"),
]

PROTECTED_ARG = re.compile(r"(?:^|/)(?:\.claude|\.github|\.governance)(?:/|$)|(?:^|/)CLAUDE(?:\.local)?\.md$")
REDIRECT_TO_PROTECTED = re.compile(r">>?\s*['\"]?(?:\./)?(?:[^\s'\"]*/)?(?:\.claude/|\.github/|\.governance/|CLAUDE(?:\.local)?\.md\b)")
INLINE_WRITE = re.compile(r"open\([^)]*(?:\.claude/|\.github/|\.governance/|CLAUDE\.md)[^)]*['\"][wa]\+?['\"]|write_text|writeFileSync")


def repo_relative(path: str, cwd: str) -> str:
    """Return path relative to the enclosing git repository root (or cwd)."""
    if not os.path.isabs(path):
        path = os.path.join(cwd, path)
    path = os.path.normpath(path)
    root = find_repo_root(os.path.dirname(path)) or find_repo_root(cwd) or cwd
    rel = os.path.relpath(path, root)
    return rel.replace(os.sep, "/")


def find_repo_root(start: str) -> str | None:
    cur = os.path.abspath(start)
    while True:
        if os.path.exists(os.path.join(cur, ".git")):
            return cur
        parent = os.path.dirname(cur)
        if parent == cur:
            return None
        cur = parent


def is_protected(rel: str) -> bool:
    if rel.startswith("../"):
        return False
    if any(rel == d.rstrip("/") or rel.startswith(d) for d in PROTECTED_DIRS):
        return True
    return os.path.basename(rel) in PROTECTED_FILES


def check_edit(tool_input: dict, cwd: str) -> str | None:
    path = tool_input.get("file_path") or tool_input.get("notebook_path") or tool_input.get("path")
    if not path:
        return None
    rel = repo_relative(path, cwd)
    if is_protected(rel):
        return (
            f"'{rel}' is governance-protected (.claude/, .github/, .governance/, CLAUDE.md). "
            "Do not edit it. If a change is needed, open an issue labeled po:decision in nullthrone/governance."
        )
    return None


def check_bash(command: str) -> str | None:
    for pattern, label in DESTRUCTIVE_PATTERNS:
        if re.search(pattern, command, flags=re.MULTILINE):
            return f"Blocked: {label}. Destructive git and admin operations are not allowed."
    for pattern, label in SECRET_PATTERNS:
        if re.search(pattern, command, flags=re.MULTILINE):
            return f"Blocked: {label}. Never print secrets or credentials."
    for segment in re.split(r"&&|\|\||;|\||\n", command):
        if writes_protected(segment):
            return (
                "Blocked: shell command appears to modify governance-protected paths "
                "(.claude/, .github/, .governance/, CLAUDE.md). Open a po:decision issue in nullthrone/governance instead."
            )
    return None


def writes_protected(segment: str) -> bool:
    if REDIRECT_TO_PROTECTED.search(segment):
        return True
    if INLINE_WRITE.search(segment) and re.search(r"\.claude/|\.github/|\.governance/|CLAUDE\.md", segment):
        return True
    try:
        tokens = shlex.split(segment)
    except ValueError:
        tokens = segment.split()
    while tokens and (re.match(r"^[A-Za-z_][A-Za-z0-9_]*=", tokens[0]) or tokens[0] in {"sudo", "command", "exec", "nohup", "xargs"}):
        tokens = tokens[1:]
    if not tokens:
        return False
    cmd = os.path.basename(tokens[0])
    args = [t for t in tokens[1:] if not t.startswith("-")]
    protected_args = [a for a in args if PROTECTED_ARG.search(a.rstrip("/") or a)]
    if cmd in {"tee", "rm", "rmdir", "truncate", "chmod", "chown", "touch", "mkdir", "unlink", "shred"} and protected_args:
        return True
    if cmd in {"sed", "perl"} and any(t.startswith("-i") for t in tokens[1:]) and protected_args:
        return True
    if cmd in {"cp", "install", "ln", "rsync"} and args and PROTECTED_ARG.search(args[-1].rstrip("/") or args[-1]):
        return True
    if cmd == "mv" and protected_args:
        return True
    if cmd == "git" and len(tokens) > 1 and tokens[1] in {"rm", "mv", "checkout", "restore", "apply"} and protected_args:
        return True
    return False


def decide(event: dict) -> str | None:
    tool = event.get("tool_name", "")
    tool_input = event.get("tool_input") or {}
    cwd = event.get("cwd") or os.getcwd()
    if tool in EDIT_TOOLS:
        return check_edit(tool_input, cwd)
    if tool == "Bash":
        return check_bash(str(tool_input.get("command", "")))
    return None


def main() -> int:
    if os.environ.get("GOVERNANCE_OWNER_SESSION") == "1":
        return 0
    try:
        event = json.load(sys.stdin)
    except (json.JSONDecodeError, ValueError):
        return 0
    reason = decide(event)
    if reason:
        print(reason, file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
