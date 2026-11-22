#!/usr/bin/env python3
"""Read .governance/profile.yml for workflows.

  profile.py get <dotted.key> [--default VALUE]   print one value (lists: one per line, maps: JSON)
  profile.py outputs                              write common values to $GITHUB_OUTPUT
  profile.py run <dotted.key> [--allow-missing]   run a command from the profile in the repo dir
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import govlib  # noqa: E402


def outputs(profile: dict) -> dict[str, str]:
    profiles = profile.get("profiles") or []
    commands = profile.get("commands") or {}
    fuzz_targets = govlib.dig(profile, "fuzz.targets") or []
    return {
        "language": str(profile.get("language") or "other"),
        "runtime_version": str(profile.get("runtime_version") or ""),
        "profiles": json.dumps(profiles),
        "is_library": str("library" in profiles).lower(),
        "is_web": str("web" in profiles).lower(),
        "is_service": str("service" in profiles).lower(),
        "publish": str(govlib.dig(profile, "package.publish") or "none"),
        "preview_type": str(govlib.dig(profile, "preview.type") or "artifact"),
        "has_deploy": str(bool(commands.get("deploy"))).lower(),
        "has_e2e": str(bool(commands.get("e2e"))).lower(),
        "docs_site": str(bool(govlib.dig(profile, "docs.site"))).lower(),
        "docs_locales": json.dumps(govlib.dig(profile, "docs.locales") or []),
        "fuzz_targets": json.dumps(fuzz_targets),
        "artifacts": str(profile.get("artifacts") or ""),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--repo-dir", default=".")
    sub = parser.add_subparsers(dest="cmd", required=True)
    g = sub.add_parser("get")
    g.add_argument("key")
    g.add_argument("--default", default="")
    sub.add_parser("outputs")
    r = sub.add_parser("run")
    r.add_argument("key")
    r.add_argument("--allow-missing", action="store_true")
    r.add_argument("--env", action="append", default=[], help="NAME=VALUE passed to the command; {NAME} placeholders are substituted")
    args = parser.parse_args(argv)

    profile = govlib.load_profile(args.repo_dir)
    if args.cmd == "get":
        value = govlib.dig(profile, args.key, None)
        if value is None:
            print(args.default)
        elif isinstance(value, list):
            print("\n".join(json.dumps(v) if isinstance(v, (dict, list)) else str(v) for v in value))
        elif isinstance(value, dict):
            print(json.dumps(value))
        else:
            print(value)
        return 0
    if args.cmd == "outputs":
        for key, value in outputs(profile).items():
            govlib.set_output(key, value)
        return 0
    if args.cmd == "run":
        command = govlib.dig(profile, args.key)
        if not command:
            if args.allow_missing:
                print(f"{args.key} not set in profile; skipping.")
                return 0
            return govlib.fail(f"{args.key} missing in .governance/profile.yml")
        extra = dict(item.split("=", 1) for item in args.env)
        for name, value in extra.items():
            command = command.replace("{" + name + "}", value)
        print(f"$ {command}", flush=True)
        return subprocess.run(command, shell=True, cwd=args.repo_dir, env={**os.environ, **extra}).returncode
    return 1


if __name__ == "__main__":
    sys.exit(main())
