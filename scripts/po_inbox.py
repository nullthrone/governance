#!/usr/bin/env python3
"""Add an issue or pull request to the owner's PO inbox (a GitHub Project on the owner's account).

  po_inbox.py add --node-id <issue/PR node id>

Needs GH_TOKEN with the `project` scope (secret PROJECT_TOKEN). Does nothing while
config/governance.json po_inbox.project_number is 0 (not configured).
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import govlib  # noqa: E402

PROJECT_QUERY = "query($login:String!,$number:Int!){user(login:$login){projectV2(number:$number){id}}}"
ADD_MUTATION = "mutation($project:ID!,$content:ID!){addProjectV2ItemById(input:{projectId:$project,contentId:$content}){item{id}}}"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="cmd", required=True)
    add = sub.add_parser("add")
    add.add_argument("--node-id", required=True)
    args = parser.parse_args(argv)
    inbox = govlib.load_config().get("po_inbox") or {}
    if not inbox.get("project_number"):
        print("PO inbox not configured (config/governance.json po_inbox.project_number); skipping.")
        return 0
    project = govlib.gh_graphql(PROJECT_QUERY, login=inbox["owner"], number=int(inbox["project_number"]))["data"]["user"]["projectV2"]["id"]
    govlib.gh_graphql(ADD_MUTATION, project=project, content=args.node_id)
    print(f"added {args.node_id} to the PO inbox")
    return 0


if __name__ == "__main__":
    sys.exit(main())
