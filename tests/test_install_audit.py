import json
import unittest
from pathlib import Path

from helpers import FAKE_SHA, git, make_repo
import govlib
import governance_audit
import install

PYPROJECT = """[project]
name = "demo-tool"
version = "0.4.1"
requires-python = ">=3.12"
[project.scripts]
demo = "demo_tool:main"
[project.optional-dependencies]
dev = ["pytest"]
"""


def onboard(root: Path, visibility: str = "public") -> list[str]:
    changes = install.Installer(root, False).run(FAKE_SHA, visibility, True, True, True, "o/demo")
    prof_path = root / govlib.PROFILE_PATH
    prof = govlib.yaml_load(prof_path.read_text())
    prof["uncertain"] = []  # owner confirmed
    prof_path.write_text(govlib.yaml_dump(prof))
    git(root, "add", "-A")
    git(root, "commit", "-q", "-m", "chore: onboard")
    git(root, "branch", "-f", "next")
    return changes


def audit(root: Path, visibility: str = "public") -> dict:
    return governance_audit.Audit(root, "o/demo", "local", visibility, None).run()


def failed(report: dict) -> set[str]:
    return {c["id"] for c in report["checks"] if c["status"] == "fail"}


class InstallAuditTest(unittest.TestCase):
    def setUp(self):
        self.tmp, self.root = make_repo({
            "pyproject.toml": PYPROJECT,
            "src/demo_tool/__init__.py": "def main():\n    print('0.4.1')\n",
            ".github/workflows/old-ci.yml": "name: old\non: push\njobs: {}\n",
            ".claude/hooks/custom.sh": "echo hi\n",
            "CLAUDE.md": "# CLAUDE.md\n\nUse pytest.\n",
        })
        self.addCleanup(self.tmp.cleanup)

    def test_legacy_repo_fails_before_onboarding(self):
        report = audit(self.root)
        self.assertFalse(report["passed"])
        self.assertTrue({"workflows", "claude-dir", "profile", "branches", "claude-md"} <= failed(report))

    def test_onboarding_makes_audit_green_and_is_idempotent(self):
        changes = onboard(self.root)
        self.assertIn("remove .github/workflows/old-ci.yml", changes)
        self.assertIn("remove .claude/hooks", changes)
        report = audit(self.root)
        self.assertEqual(failed(report), set(), json.dumps(report["checks"], indent=1))
        self.assertTrue(all(c["status"] in ("pass", "skip") for c in report["checks"]))
        self.assertEqual(install.Installer(self.root, False).run(FAKE_SHA, "public", True, True, True, "o/demo"), [])
        config = (self.root / ".github/ISSUE_TEMPLATE/config.yml").read_text()
        self.assertIn("https://github.com/o/demo/discussions/categories/ideas", config)
        self.assertIn("blank_issues_enabled: false", config)
        self.assertIn("Use pytest.", (self.root / "CLAUDE.md").read_text())
        self.assertEqual(json.loads((self.root / ".release-please-manifest.json").read_text()), {".": "0.4.1"})

    def test_private_repo_has_no_scorecard(self):
        onboard(self.root, "private")
        self.assertFalse((self.root / ".github/workflows/scorecard.yml").exists())
        self.assertEqual(failed(audit(self.root, "private")), set())

    def test_drift_is_detected(self):
        onboard(self.root)
        cases = {
            "workflows": lambda r: (r / ".github/workflows/extra.yml").write_text("name: x\n"),
            "claude-dir": lambda r: (r / ".claude/agents").mkdir(),
            "claude-md": lambda r: (r / "CLAUDE.md").write_text((r / "CLAUDE.md").read_text().replace("read-only for Claude", "editable")),
            "issue-templates": lambda r: (r / ".github/ISSUE_TEMPLATE/bug.yml").write_text("labels: [po:ready]\n"),
            "release-mechanism": lambda r: (r / ".releaserc.json").write_text("{}"),
            "architecture-md": lambda r: (r / "ARCHITECTURE.md").write_text((r / "ARCHITECTURE.md").read_text() + "\n".join(f"- d{i}" for i in range(61))),
            "dependabot": lambda r: (r / ".github/dependabot.yml").write_text("version: 2\nupdates:\n  - package-ecosystem: github-actions\n"),
            "pin": lambda r: (r / ".github/workflows/governance-push.yml").write_text((r / ".github/workflows/governance-push.yml").read_text().replace(FAKE_SHA, "f" * 40, 1)),
        }
        for check_id, mutate in cases.items():
            with self.subTest(check=check_id):
                tmp, root = make_repo({})
                self.addCleanup(tmp.cleanup)
                for f in self.root.rglob("*"):
                    if ".git" in f.relative_to(self.root).parts or f.is_dir():
                        continue
                    target = root / f.relative_to(self.root)
                    target.parent.mkdir(parents=True, exist_ok=True)
                    target.write_bytes(f.read_bytes())
                git(root, "add", "-A")
                git(root, "commit", "-q", "-m", "copy")
                git(root, "branch", "-f", "next")
                self.assertEqual(failed(audit(root)), set())
                mutate(root)
                expected = "workflows" if check_id == "pin" else check_id
                self.assertIn(expected, failed(audit(root)))

    def test_settings_shape(self):
        settings = install.settings_content(FAKE_SHA, {"permissions": {"allow": ["Bash(pytest:*)"]}, "hooks": {}})
        self.assertNotIn("hooks", settings)
        self.assertEqual(settings["attribution"], False)
        self.assertEqual(settings["extraKnownMarketplaces"]["nullthrone-governance"]["source"]["ref"], FAKE_SHA)
        self.assertEqual(settings["permissions"], {"allow": ["Bash(pytest:*)"]})


if __name__ == "__main__":
    unittest.main()


class NewProjectTest(unittest.TestCase):
    def test_template_passes_audit(self):
        import tempfile

        import new_project

        for visibility in ("public", "private"):
            with self.subTest(visibility=visibility), tempfile.TemporaryDirectory() as tmp:
                target = Path(tmp) / "proj"
                new_project.create(target, "acme-tool", FAKE_SHA, visibility, "o/acme-tool")
                report = governance_audit.Audit(target, "o/acme-tool", "local", visibility, None).run()
                self.assertEqual(failed(report), set(), json.dumps(report["checks"], indent=1))
                self.assertTrue((target / "src/acme_tool/cli.py").exists())
                self.assertNotIn("{{", (target / "pyproject.toml").read_text())
