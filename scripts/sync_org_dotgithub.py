#!/usr/bin/env python3
"""Render org-dotgithub/ into a checkout of an organization's .github repository.

  sync_org_dotgithub.py --org ORG --target-dir DIR

Writes CONTRIBUTING, SECURITY, CODE_OF_CONDUCT, README and the issue/discussion forms with the
organization's Discussions URL. Stale files inside the managed form directories are removed;
everything else in the repository (for example profile/README.md) is left alone.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import install  # noqa: E402


def render(org: str, target: Path) -> list[str]:
    files = install.community_files(f"https://github.com/orgs/{org}/discussions", repo_level=False)
    changes = []
    for rel, content in files.items():
        path = target / rel
        if path.exists() and path.read_text(encoding="utf-8") == content:
            continue
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        changes.append(f"write {rel}")
    for managed in install.REPO_COMMUNITY_DIRS:
        d = target / managed
        if d.is_dir():
            for path in sorted(d.iterdir()):
                rel = path.relative_to(target).as_posix()
                if path.is_file() and rel not in files:
                    path.unlink()
                    changes.append(f"remove {rel}")
    return changes


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--org", required=True)
    parser.add_argument("--target-dir", required=True)
    args = parser.parse_args(argv)
    changes = render(args.org, Path(args.target_dir))
    print("\n".join(changes) if changes else "unchanged")
    return 0


if __name__ == "__main__":
    sys.exit(main())
