import unittest
from unittest import mock

from helpers import ROOT  # noqa: F401
import housekeeping as hk

BOT = "nullthrone-governance[bot]"
CFG = {"bot_app_slug": "nullthrone-governance"}


def issue(number=12, state="open", labels=("po:ready", "in-progress")):
    return {"number": number, "state": state, "labels": [{"name": n} for n in labels]}


def attempt(user=BOT):
    return {"event": "commented", "user": {"login": user}, "body": f"ended without a PR\n\n{hk.ATTEMPT_MARKER}"}


class RoadmapFinishTest(unittest.TestCase):
    def test_closing_pr(self):
        prs = [
            {"number": 1, "state": "open", "title": "fix: x", "body": "Closes #123", "head": {"ref": "claude/123-x"}},
            {"number": 2, "state": "closed", "merged_at": None, "title": "fix: y", "body": "Fixes #12", "head": {"ref": "y"}},
        ]
        self.assertIsNone(hk.closing_pr(prs, 12))
        self.assertEqual(hk.closing_pr(prs + [{"number": 3, "state": "open", "title": "fix: z", "body": "What.\n\nResolves #12", "head": {"ref": "z"}}], 12), 3)
        self.assertEqual(hk.closing_pr([{"number": 4, "state": "open", "title": "feat: a", "body": "", "head": {"ref": "claude/12-a"}}], 12), 4)
        # A feat PR merged into next does not close the issue, but the work is done.
        self.assertEqual(hk.closing_pr([{"number": 5, "state": "closed", "merged_at": "2026-11-24T01:00:00Z", "title": "feat: b", "body": "Closes #12", "head": {"ref": "b"}}], 12), 5)

    def test_failed_attempts(self):
        self.assertEqual(hk.failed_attempts([], BOT), 0)
        self.assertEqual(hk.failed_attempts([attempt(), attempt()], BOT), 2)
        self.assertEqual(hk.failed_attempts([attempt(user="stranger")], BOT), 0)
        removed = {"event": "unlabeled", "label": {"name": "blocked"}}
        self.assertEqual(hk.failed_attempts([attempt(), attempt(), removed, attempt()], BOT), 1)

    def test_plan(self):
        self.assertFalse(hk.roadmap_finish_plan(issue(state="closed"), [], [], BOT)["release"])
        self.assertFalse(hk.roadmap_finish_plan(issue(labels=("po:ready",)), [], [], BOT)["release"])
        pr = {"number": 7, "state": "open", "title": "fix: x", "body": "Closes #12", "head": {"ref": "x"}}
        self.assertFalse(hk.roadmap_finish_plan(issue(), [pr], [], BOT)["release"])
        self.assertEqual(hk.roadmap_finish_plan(issue(), [], [], BOT), {"release": True, "attempt": 1, "block": False})
        self.assertEqual(hk.roadmap_finish_plan(issue(), [], [attempt()], BOT), {"release": True, "attempt": 2, "block": True})

    def run_finish(self, timeline):
        calls = []

        def gh_api(path, **kwargs):
            if "/timeline" in path:
                return timeline
            if "/pulls" in path:
                return []
            return issue()

        with mock.patch.object(hk.govlib, "gh_api", gh_api), mock.patch.object(hk.govlib, "gh", lambda *a, **k: calls.append(a)), \
             mock.patch.object(hk.govlib, "summary"):
            self.assertEqual(hk.roadmap_finish("o/r", CFG, 12, "https://run/1"), 0)
        return calls

    def test_first_failure_releases_and_comments(self):
        calls = self.run_finish([])
        comment = next(c for c in calls if c[:2] == ("issue", "comment"))
        self.assertIn("https://run/1", comment[-1])
        self.assertIn(hk.ATTEMPT_MARKER, comment[-1])
        edit = next(c for c in calls if c[:2] == ("issue", "edit"))
        self.assertIn("in-progress", edit)
        self.assertNotIn("blocked", edit)

    def test_second_failure_blocks(self):
        edit = next(c for c in self.run_finish([attempt()]) if c[:2] == ("issue", "edit"))
        self.assertEqual(edit[edit.index("--remove-label") + 1], "in-progress")
        self.assertEqual(edit[edit.index("--add-label") + 1], "blocked")


if __name__ == "__main__":
    unittest.main()
