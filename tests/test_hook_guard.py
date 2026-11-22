import tempfile
import unittest
from pathlib import Path

from helpers import ROOT  # noqa: F401
import guard


class GuardHookTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        (self.root / ".git").mkdir()

    def tearDown(self):
        self.tmp.cleanup()

    def edit(self, path):
        return guard.decide({"tool_name": "Write", "tool_input": {"file_path": path}, "cwd": str(self.root)})

    def test_protected_paths_blocked(self):
        for path in (".github/workflows/x.yml", ".claude/settings.json", ".governance/profile.yml", "CLAUDE.md", "sub/CLAUDE.md", str(self.root / ".github" / "x")):
            self.assertIsNotNone(self.edit(path), path)

    def test_regular_paths_allowed(self):
        for path in ("src/app.py", "docs/index.md", "README.md", "githubstuff/x", ".githubx/y"):
            self.assertIsNone(self.edit(path), path)

    def test_notebook_path(self):
        self.assertIsNotNone(guard.decide({"tool_name": "NotebookEdit", "tool_input": {"notebook_path": ".claude/x.ipynb"}, "cwd": str(self.root)}))

    def test_bash(self):
        blocked = [
            "git push --force origin main", "git push -f", "git push origin +main", "git push --force-with-lease",
            "git filter-repo --path x", "git branch -D next", "git push origin --delete main", "git push origin :main",
            "printenv", "env", "echo $GITHUB_TOKEN", "gh auth token", "cat .env", "cat ~/.config/gh/hosts.yml",
            "echo x > .github/workflows/a.yml", "echo x | tee CLAUDE.md", "sed -i s/a/b/ .claude/settings.json",
            "rm -rf .governance", "cp /tmp/y .github/x", "git checkout -- .github/workflows/x.yml", "mkdir -p .github/workflows",
            "gh secret set FOO", "gh repo delete x/y",
        ]
        allowed = [
            "git push origin feature", "git push -u origin claude/12-x", "env FOO=1 make", "echo $HOME",
            "cat .github/workflows/ci.yml", "cat .github/workflows/ci.yml 2>/dev/null", "sed s/a/b/ .claude/settings.json",
            "cp .github/x /tmp/y", "git diff .github/", "set -euo pipefail; make test", "git branch -D feature", "pytest -q",
            "ls .claude/", "gh pr create --fill",
        ]
        for command in blocked:
            self.assertIsNotNone(guard.check_bash(command), command)
        for command in allowed:
            self.assertIsNone(guard.check_bash(command), command)


if __name__ == "__main__":
    unittest.main()
