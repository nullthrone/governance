#!/usr/bin/env python3
"""Set the package version in the working tree (used for release-candidate preview builds).

  set_version.py 1.4.0-rc.2 [--repo-dir .]

Updates the static version in pyproject.toml ([project] version), package.json, Cargo.toml
([package] version) and the release-please manifest's sibling files are left alone.
Python versions are written in PEP 440 form (1.4.0rc2). Nothing is committed.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path


def pep440(version: str) -> str:
    return re.sub(r"-rc\.(\d+)$", r"rc\1", version)


def set_toml_version(text: str, section: str, version: str) -> tuple[str, bool]:
    pattern = re.compile(rf"(^\[{re.escape(section)}\][^\[]*?^version\s*=\s*)\"[^\"]*\"", re.MULTILINE | re.DOTALL)
    new, n = pattern.subn(lambda m: f'{m.group(1)}"{version}"', text, count=1)
    return new, n == 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("version")
    parser.add_argument("--repo-dir", default=".")
    args = parser.parse_args(argv)
    root = Path(args.repo_dir)
    version = args.version.lstrip("v")
    changed = []
    py = root / "pyproject.toml"
    if py.exists():
        text, ok = set_toml_version(py.read_text(encoding="utf-8"), "project", pep440(version))
        if ok:
            py.write_text(text, encoding="utf-8")
            changed.append("pyproject.toml")
    pkg = root / "package.json"
    if pkg.exists():
        data = json.loads(pkg.read_text(encoding="utf-8"))
        data["version"] = version
        pkg.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
        changed.append("package.json")
    cargo = root / "Cargo.toml"
    if cargo.exists():
        text, ok = set_toml_version(cargo.read_text(encoding="utf-8"), "package", version)
        if ok:
            cargo.write_text(text, encoding="utf-8")
            changed.append("Cargo.toml")
    print(f"version {version}: {', '.join(changed) or 'no static version field found (dynamic versioning?)'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
