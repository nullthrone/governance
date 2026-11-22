#!/usr/bin/env python3
"""Sync the label taxonomy (labels.yml) into a repository.

  sync_labels.py --repo OWNER/NAME [--prune] [--dry-run]

Creates missing labels and fixes color/description. --prune deletes labels outside the
taxonomy (irreversible: removes them from issues; onboarding asks the owner first).
"""
from __future__ import annotations

import argparse
import sys
import urllib.parse
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import govlib  # noqa: E402


def taxonomy() -> list[dict]:
    return govlib.yaml_load((govlib.GOV_ROOT / "labels.yml").read_text(encoding="utf-8"))


def diff_labels(wanted: list[dict], existing: list[dict]) -> dict[str, list]:
    have = {lbl["name"].lower(): lbl for lbl in existing}
    want_names = {w["name"].lower() for w in wanted}
    create, update = [], []
    for w in wanted:
        cur = have.get(w["name"].lower())
        if cur is None:
            create.append(w)
        elif cur["color"].lower() != str(w["color"]).lower() or (cur.get("description") or "") != w["description"] or cur["name"] != w["name"]:
            update.append({**w, "current_name": cur["name"]})
    extra = [lbl for lbl in existing if lbl["name"].lower() not in want_names]
    return {"create": create, "update": update, "extra": extra}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--repo", required=True)
    parser.add_argument("--prune", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)

    existing = govlib.gh_api(f"repos/{args.repo}/labels?per_page=100", paginate=True)
    plan = diff_labels(taxonomy(), existing)
    for label in plan["create"]:
        print(f"create {label['name']}")
        if not args.dry_run:
            govlib.gh_api(f"repos/{args.repo}/labels", method="POST", body={"name": label["name"], "color": label["color"], "description": label["description"]})
    for label in plan["update"]:
        print(f"update {label['current_name']}")
        if not args.dry_run:
            path = urllib.parse.quote(label["current_name"], safe="")
            govlib.gh_api(f"repos/{args.repo}/labels/{path}", method="PATCH", body={"new_name": label["name"], "color": label["color"], "description": label["description"]})
    for label in plan["extra"]:
        if args.prune:
            print(f"delete {label['name']}")
            if not args.dry_run:
                govlib.gh_api(f"repos/{args.repo}/labels/{urllib.parse.quote(label['name'], safe='')}", method="DELETE")
        else:
            print(f"extra (kept) {label['name']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
