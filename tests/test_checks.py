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

    def test_owner_passes_only_if_owner_pushed(self):
        self.assertTrue(checks.guard_decision(["CLAUDE.md"], OWNER, [OWNER, OWNER], OWNER, PROTECTED, False, [OWNER])[0])
        self.assertFalse(checks.guard_decision(["CLAUDE.md"], OWNER, [OWNER], OWNER, PROTECTED, False, [OWNER, "nullthrone-governance[bot]"])[0])
        self.assertFalse(checks.guard_decision(["CLAUDE.md"], OWNER, [OWNER], OWNER, PROTECTED, False, None)[0])

    def test_claude_local_md_protected_anywhere(self):
        protected = PROTECTED + ["CLAUDE.local.md"]
        self.assertTrue(checks.is_protected("CLAUDE.local.md", protected))
        self.assertTrue(checks.is_protected("pkg/CLAUDE.local.md", protected))
        self.assertFalse(checks.is_protected("docs/claude.md", protected))

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
        self.assertEqual(checks.review_mode(pr(head="release-please--branches--main"), dep, 0, 3, version_only=True)[0], "skip")
        self.assertEqual(checks.review_mode(pr(head="release-please--branches--main"), dep, 0, 3, version_only=False)[0], "review")
        self.assertEqual(checks.review_mode(pr(author="dependabot[bot]"), dep, 0, 3, commit_authors=["dependabot[bot]"])[0], "skip")
        self.assertEqual(checks.review_mode(pr(author="dependabot[bot]"), dep, 0, 3, commit_authors=["dependabot[bot]", "nullthrone-governance[bot]"])[0], "review")
        self.assertEqual(checks.review_mode(pr(head="next", base="main"), dep, 0, 3, duplicates=[9])[0], "duplicate")
        self.assertEqual(checks.review_mode(pr(same_repo=False, author="x"), dep, 0, 3)[0], "fork")
        self.assertEqual(checks.review_mode(pr(head="next", base="main", same_repo=False), dep, 0, 3)[0], "fork")
        self.assertEqual(checks.review_mode(pr(), dep, 3, 3)[0], "limit")
        self.assertEqual(checks.review_mode(pr(), dep, 2, 3)[0], "review")


class CommitMessageTest(unittest.TestCase):
    def test_feat_commit_into_main(self):
        self.assertTrue(checks.commit_message_problems("main", False, ["feat: sneaky"], ""))
        self.assertEqual(checks.commit_message_problems("next", False, ["feat: fine"], ""), [])

    def test_breaking_markers(self):
        self.assertTrue(checks.commit_message_problems("main", False, ["fix!: x"], ""))
        self.assertTrue(checks.commit_message_problems("main", False, ["fix: x\n\nBREAKING CHANGE: y"], ""))
        self.assertTrue(checks.commit_message_problems("main", False, ["fix: x"], "text\n\nBREAKING-CHANGE: z"))
        self.assertEqual(checks.commit_message_problems("next", True, ["feat!: x\n\nBREAKING CHANGE: y"], ""), [])
        self.assertEqual(checks.commit_message_problems("main", False, ["wip", "fix tests"], "Closes #3"), [])


class VersionOnlyDiffTest(unittest.TestCase):
    def test_release_please_diff(self):
        ok = [
            {"filename": "CHANGELOG.md", "patch": "+## 1.2.0\n+- feat: a"},
            {"filename": ".release-please-manifest.json", "patch": '-  ".": "1.1.0"\n+  ".": "1.2.0"'},
            {"filename": "pyproject.toml", "patch": '@@ -3 +3 @@\n-version = "1.1.0"\n+version = "1.2.0"'},
        ]
        self.assertTrue(checks.version_only_diff(ok))
        self.assertFalse(checks.version_only_diff(ok + [{"filename": "src/app.py", "patch": "+evil()"}]))
        self.assertFalse(checks.version_only_diff([{"filename": "pyproject.toml", "patch": '+dependencies = ["evil"]'}]))
        self.assertFalse(checks.version_only_diff([{"filename": "package.json"}]))


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


class CommandLevelAttackTest(unittest.TestCase):
    """Gates decide per head commit and per event, against a fake GitHub API."""

    def pr_json(self, number, head, base, sha, author="nullthrone-governance[bot]", repo="o/r"):
        return {"number": number, "user": {"login": author}, "title": "fix: x", "body": "", "base": {"ref": base},
                "head": {"ref": head, "sha": sha, "repo": {"full_name": repo}}, "labels": [], "changed_files": 1, "commits": 1}

    def run_cmd(self, argv, api, payload=None):
        from unittest import mock

        def gh_api(path, method="GET", fields=None, paginate=False, body=None):
            for prefix, value in api.items():
                if path.startswith(prefix):
                    return value
            raise checks.govlib.GhError(f"404 {path}")

        with mock.patch.object(checks.govlib, "gh_api", gh_api), \
             mock.patch.object(checks.govlib, "event_payload", return_value=payload or {}), \
             mock.patch.object(checks.govlib, "summary"), mock.patch.object(checks.govlib, "fail", side_effect=lambda m, code=1: code):
            try:
                return checks.main(argv)
            except SystemExit as exc:
                return exc.code

    def test_decoy_pr_cannot_pass_candidate_approval(self):
        candidate = self.pr_json(1, "next", "main", "s1")
        decoy = self.pr_json(2, "decoy", "main", "s1")
        api = {"repos/o/r/pulls/2": decoy, "repos/o/r/pulls?state=open": [candidate, decoy], "repos/o/r/pulls/1/reviews": []}
        self.assertNotEqual(self.run_cmd(["--repo", "o/r", "--pr", "2", "candidate-approval"], api), 0)
        self.assertNotEqual(self.run_cmd(["--repo", "o/r", "--pr", "2", "unique-head"], api), 0)

    def test_candidate_per_sha_without_duplicates(self):
        candidate = self.pr_json(1, "next", "main", "s1")
        approved = [{"user": {"login": "t11z"}, "state": "APPROVED", "commit_id": "s1", "submitted_at": "x"}]
        api = {"repos/o/r/pulls/1/reviews": approved, "repos/o/r/pulls/1": candidate, "repos/o/r/pulls?state=open": [candidate]}
        self.assertEqual(self.run_cmd(["--repo", "o/r", "--pr", "1", "candidate-approval"], api), 0)
        api["repos/o/r/pulls/1/reviews"] = []
        self.assertNotEqual(self.run_cmd(["--repo", "o/r", "--pr", "1", "candidate-approval"], api), 0)

    def test_base_change_fails_guard(self):
        pr_ = self.pr_json(3, "feature", "main", "s3")
        api = {"repos/o/r/pulls/3/files": [{"filename": "src/a.py"}], "repos/o/r/pulls/3/commits": [{"author": {"login": "x"}}],
               "repos/o/r/pulls/3": pr_, "repos/o/r/pulls?state=open": [pr_]}
        payload = {"action": "edited", "changes": {"base": {"ref": {"from": "x"}}}, "pull_request": {"number": 3}}
        self.assertNotEqual(self.run_cmd(["--repo", "o/r", "--pr", "3", "guard"], api, payload), 0)
        self.assertEqual(self.run_cmd(["--repo", "o/r", "--pr", "3", "guard"], api, {"action": "synchronize"}), 0)

    def test_truncated_file_list_fails_guard(self):
        pr_ = {**self.pr_json(4, "feature", "main", "s4"), "changed_files": 3001}
        api = {"repos/o/r/pulls/4/files": [{"filename": "a"}] * 3000, "repos/o/r/pulls/4": pr_, "repos/o/r/pulls?state=open": [pr_]}
        self.assertNotEqual(self.run_cmd(["--repo", "o/r", "--pr", "4", "guard"], api), 0)
