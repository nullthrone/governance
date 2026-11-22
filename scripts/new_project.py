#!/usr/bin/env python3
"""Create a new project from template-repo/ that passes governance-audit right away.

  new_project.py TARGET_DIR --name my-tool [--sha SHA] [--visibility public|private] [--repo OWNER/NAME]

Copies template-repo/, fills {{PROJECT_NAME}}, {{PACKAGE}} and {{YEAR}}, runs install.py with the
governance pin (default: this checkout's HEAD, which must be pushed), commits on main and creates
next. Push the result and run the onboarding prompt once for the GitHub-side settings.
"""
from __future__ import annotations

import argparse
import datetime as dt
import re
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import govlib  # noqa: E402
import install  # noqa: E402

TEMPLATE = govlib.GOV_ROOT / "template-repo"
NAME_RE = re.compile(r"^[a-z][a-z0-9-]*[a-z0-9]$")


def create(target: Path, name: str, sha: str, visibility: str, repo: str | None) -> list[str]:
    package = name.replace("-", "_")
    values = {"{{PROJECT_NAME}}": name, "{{PACKAGE}}": package, "{{YEAR}}": str(dt.date.today().year)}
    target.mkdir(parents=True, exist_ok=True)
    if any(target.iterdir()):
        raise SystemExit(govlib.fail(f"{target} is not empty"))
    for src in sorted(TEMPLATE.rglob("*")):
        if src.is_dir():
            continue
        rel = src.relative_to(TEMPLATE).as_posix().replace("__package__", package)
        text = src.read_text(encoding="utf-8")
        for key, value in values.items():
            text = text.replace(key, value)
        dest = target / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(text, encoding="utf-8")
    govlib.git("init", "-q", "-b", "main", cwd=target)
    changes = install.Installer(target, False).run(sha, visibility, False, True, True, repo)
    govlib.git("add", "-A", cwd=target)
    govlib.git("commit", "-q", "-m", "chore: initial project from nullthrone/governance template", cwd=target)
    govlib.git("branch", "next", cwd=target)
    return changes


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("target")
    parser.add_argument("--name", required=True)
    parser.add_argument("--sha")
    parser.add_argument("--visibility", choices=["public", "private"], default="public")
    parser.add_argument("--repo")
    args = parser.parse_args(argv)
    if not NAME_RE.match(args.name):
        return govlib.fail("--name: lowercase letters, digits and dashes")
    sha = args.sha or govlib.git("rev-parse", "HEAD", cwd=govlib.GOV_ROOT)
    if not install.SHA_RE.match(sha):
        return govlib.fail("governance SHA must be 40 hex characters")
    changes = create(Path(args.target).resolve(), args.name, sha, args.visibility, args.repo)
    print("\n".join(changes))
    print(f"created {args.target} pinned to governance {sha[:12]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
