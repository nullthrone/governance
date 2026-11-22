import json
import tempfile
import unittest

from helpers import ROOT  # noqa: F401
import checks

OWNER = "t11z"
BOTS = ["nullthrone-governance[bot]", "github-actions[bot]", "dependabot[bot]"]
PROTECTED = [".claude/", "CLAUDE.md", ".github/", ".governance/"]
TYPES = {"main": ["fix", "refactor", "chore", "docs", "test", "ci", "perf", "build", "revert"], "next": ["feat", "fix", "chore"]}


def pr(head="claude/1-x", base="main", same_repo=True, author="nullthrone-governance[bot]", title="fix: x"):
    return checks.PR(
        {
            "number": 7,
            "user": {"login": author},
            "title": title,
            "body": "",
            "base": {"ref": base},
            "head": {"ref": head, "sha": "abc", "repo": {"full_name": "o/r" if same_repo else "fork/r"}},
            "labels": [],
        },
        "o/r",
    )


class GuardTest(unittest.TestCase):
    def test_no_protected(self):
        self.assertTrue(checks.guard_decision(["src/a.py"], "x", ["x"], OWNER, PROTECTED, False)[0])

    def test_protected_by_bot_fails(self):
        self.assertFalse(checks.guard_decision([".github/workflows/a.yml"], "nullthrone-governance[bot]", [], OWNER, PROTECTED, False)[0])

    def test_nested_claude_md(self):
        self.assertFalse(checks.guard_decision(["pkg/CLAUDE.md"], "bot", [], OWNER, PROTECTED, False)[0])

    def test_owner_with_foreign_commit_fails(self):
        self.assertFalse(checks.guard_decision([".claude/settings.json"], OWNER, [OWNER, "bot"], OWNER, PROTECTED, False)[0])
        self.assertFalse(checks.guard_decision([".claude/settings.json"], OWNER, [None], OWNER, PROTECTED, False)[0])

    def test_owner_passes(self):
        self.assertTrue(checks.guard_decision(["CLAUDE.md"], OWNER, [OWNER, OWNER], OWNER, PROTECTED, False)[0])

    def test_promotion_passes(self):
        self.assertTrue(checks.guard_decision([".github/x"], "bot", ["bot"], OWNER, PROTECTED, True)[0])

    def test_promotion_requires_same_repo(self):
        self.assertTrue(pr(head="next", base="main").is_promotion)
        self.assertFalse(pr(head="next", base="main", same_repo=False).is_promotion)
        self.assertFalse(pr(head="main", base="main").is_promotion)


class TitleTest(unittest.TestCase):
    def test_feat_into_main_fails(self):
        ok, msg, _ = checks.title_decision("feat: x", "main", TYPES, False)
        self.assertFalse(ok)
        self.assertIn("next", msg)

    def test_fix_into_main(self):
        self.assertTrue(checks.title_decision("fix(security): x", "main", TYPES, False)[0])

    def test_not_conventional(self):
        self.assertFalse(checks.title_decision("Update stuff", "next", TYPES, False)[0])

    def test_promotion_exempt(self):
        self.assertTrue(checks.title_decision("Release candidate v1.2.0-rc.1", "main", TYPES, True)[0])

    def test_breaking_parsed(self):
        self.assertTrue(checks.title_decision("feat!: drop x", "next", TYPES, False)[2]["breaking"])


class DocsWipTest(unittest.TestCase):
    def test_docs(self):
        self.assertFalse(checks.docs_decision("feat: x", "next", ["src/a.py"], [])[0])
        self.assertTrue(checks.docs_decision("feat: x", "next", ["docs/how-to/a.md"], [])[0])
        self.assertTrue(checks.docs_decision("feat: x", "next", ["README.md"], [])[0])
        self.assertTrue(checks.docs_decision("feat: x", "next", ["src/a.py"], ["docs:none"])[0])
        self.assertTrue(checks.docs_decision("fix: x", "main", ["src/a.py"], [])[0])

    def test_wip(self):
        self.assertEqual(checks.count_feats(["feat: a (#1)", "fix: b", "feat(x)!: c", "chore: sync main into next"]), 2)
        self.assertFalse(checks.wip_decision("feat: x", "next", 3, 3)[0])
        self.assertTrue(checks.wip_decision("feat: x", "next", 2, 3)[0])
        self.assertTrue(checks.wip_decision("fix: x", "next", 5, 3)[0])


class GateTest(unittest.TestCase):
    def test_owner_and_bots_pass(self):
        self.assertTrue(checks.gate_decision(OWNER, OWNER, BOTS, [])[0])
        self.assertTrue(checks.gate_decision("dependabot[bot]", OWNER, BOTS, [])[0])

    def test_external_needs_latest_owner_approval(self):
        self.assertFalse(checks.gate_decision("stranger", OWNER, BOTS, [])[0])
        self.assertFalse(checks.gate_decision("evil[bot]", OWNER, BOTS, [])[0])
        self.assertTrue(checks.gate_decision("stranger", OWNER, BOTS, [{"state": "APPROVED"}])[0])
        self.assertFalse(checks.gate_decision("stranger", OWNER, BOTS, [{"state": "APPROVED"}, {"state": "DISMISSED"}])[0])

    def test_candidate_needs_approval_on_head(self):
        self.assertTrue(checks.candidate_decision(False, "abc", [])[0])
        self.assertFalse(checks.candidate_decision(True, "abc", [])[0])
        self.assertFalse(checks.candidate_decision(True, "abc", [{"state": "APPROVED", "commit_id": "old"}])[0])
        self.assertTrue(checks.candidate_decision(True, "abc", [{"state": "APPROVED", "commit_id": "abc"}])[0])


class ReviewModeTest(unittest.TestCase):
    def test_modes(self):
        dep = ["dependabot[bot]", "renovate[bot]"]
        self.assertEqual(checks.review_mode(pr(head="next", base="main"), dep, 0, 3)[0], "skip")
        self.assertEqual(checks.review_mode(pr(head="release-please--branches--main"), dep, 0, 3)[0], "skip")
        self.assertEqual(checks.review_mode(pr(author="dependabot[bot]"), dep, 0, 3)[0], "skip")
        self.assertEqual(checks.review_mode(pr(same_repo=False, author="x"), dep, 0, 3)[0], "fork")
        self.assertEqual(checks.review_mode(pr(head="next", base="main", same_repo=False), dep, 0, 3)[0], "fork")
        self.assertEqual(checks.review_mode(pr(), dep, 3, 3)[0], "limit")
        self.assertEqual(checks.review_mode(pr(), dep, 2, 3)[0], "review")


class PoReadyTest(unittest.TestCase):
    def labeled(self, actor, name="po:ready", event="labeled"):
        return {"event": event, "label": {"name": name}, "actor": {"login": actor}}

    def test_owner(self):
        self.assertTrue(checks.po_ready_decision([self.labeled(OWNER)], ["po:ready"], OWNER)[0])

    def test_last_labeler_counts(self):
        timeline = [self.labeled(OWNER), self.labeled(OWNER, event="unlabeled"), self.labeled("nullthrone-governance[bot]")]
        self.assertFalse(checks.po_ready_decision(timeline, ["po:ready"], OWNER)[0])

    def test_label_must_be_present(self):
        self.assertFalse(checks.po_ready_decision([self.labeled(OWNER)], [], OWNER)[0])

    def test_other_labels_ignored(self):
        self.assertTrue(checks.po_ready_decision([self.labeled(OWNER), self.labeled("bot", name="type:bug")], ["po:ready"], OWNER)[0])


class VerdictTest(unittest.TestCase):
    def test_extract(self):
        text = 'Findings\n- a.py:1 — minor — x\n{"verdict": "approve", "classification_ok": true, "summary": "fine"}'
        verdict, body = checks.extract_verdict(text)
        self.assertEqual(verdict["verdict"], "approve")
        self.assertEqual(body, "Findings\n- a.py:1 — minor — x")

    def test_fenced_and_missing(self):
        self.assertEqual(checks.extract_verdict('x\n```\n{"verdict": "request_changes"}\n```')[0]["verdict"], "request_changes")
        self.assertIsNone(checks.extract_verdict("no verdict here")[0])
        self.assertIsNone(checks.extract_verdict('{"verdict": "maybe"}')[0])

    def test_execution_file(self):
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as fh:
            json.dump([{"type": "assistant", "message": {"content": [{"type": "text", "text": "old"}]}}, {"type": "result", "result": "final"}], fh)
        self.assertEqual(checks.final_text_from_execution(fh.name), "final")


if __name__ == "__main__":
    unittest.main()
