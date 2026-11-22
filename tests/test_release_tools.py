import unittest

from helpers import ROOT  # noqa: F401
import release_tools as rt
import set_version


class ReleaseToolsTest(unittest.TestCase):
    def test_next_rc(self):
        tags = ["v1.2.0", "v1.3.0", "v1.3.1", "v1.4.0-rc.1", "v1.4.0-rc.2", "junk"]
        self.assertEqual(rt.next_rc(tags, ["feat: a", "fix: b"]), "1.4.0-rc.3")
        self.assertEqual(rt.next_rc(tags, ["feat!: drop"]), "2.0.0-rc.1")
        self.assertEqual(rt.next_rc(tags, ["fix: b"]), "1.3.2-rc.1")
        self.assertEqual(rt.next_rc([], ["feat: a"]), "0.1.0-rc.1")
        self.assertEqual(rt.next_rc(["v0.3.0"], ["feat!: a"]), "0.4.0-rc.1")

    def test_previous_tag(self):
        tags = ["v1.0.0", "v1.10.0", "v1.9.0", "v1.10.0-rc.1"]
        self.assertEqual(rt.previous_tag(tags, "v1.10.0"), "v1.9.0")
        self.assertIsNone(rt.previous_tag(tags, "v1.0.0"))

    def test_version_in_output(self):
        self.assertTrue(rt.version_in_output("1.4.0", "tool 1.4.0\n"))
        self.assertTrue(rt.version_in_output("1.4.0", "v1.4.0"))
        self.assertFalse(rt.version_in_output("1.4.0", "1.4.01"))
        self.assertFalse(rt.version_in_output("1.4.0", "11.4.0"))
        self.assertFalse(rt.version_in_output("1.4.0", "1.4.0-rc.1"))

    def test_test_steps(self):
        body = "What\n\n## Test\n1. Open app\n2. Click X\n- See Y\n4. extra\n\n## Notes\n- n"
        self.assertEqual(rt.test_steps(body), ["Open app", "Click X", "See Y"])
        self.assertEqual(rt.test_steps("no section"), [])

    def test_candidate_body(self):
        text = rt.candidate_body("1.4.0-rc.1", [{"subject": "feat: a (#3)", "pr": "3", "steps": ["Do"]}], "", "", "https://run")
        self.assertIn("feat: a (#3)", text)
        self.assertNotIn("(#3) (#3)", text)
        self.assertIn("1. Do", text)
        self.assertIn("https://run", text)

    def test_bump_kind(self):
        self.assertEqual(rt.bump_kind("v1.2.3", "1.2.4"), "patch")
        self.assertEqual(rt.bump_kind("v1.2.3", "1.3.0"), "minor")
        self.assertEqual(rt.bump_kind("v1.2.3", "2.0.0"), "major")
        self.assertEqual(rt.bump_kind(None, "0.1.0"), "minor")

    def test_accepted_candidate(self):
        merged = [{"number": 5, "merged_at": "2026-11-20T10:00:00Z", "head": {"sha": "abc"}}]
        approved = {5: [{"user": {"login": "t11z"}, "state": "APPROVED", "commit_id": "abc", "submitted_at": "2026-11-20T09:00:00Z"}]}
        stale = {5: [{"user": {"login": "t11z"}, "state": "APPROVED", "commit_id": "old", "submitted_at": "2026-11-20T09:00:00Z"}]}
        by_bot = {5: [{"user": {"login": "nullthrone-governance[bot]"}, "state": "APPROVED", "commit_id": "abc", "submitted_at": "x"}]}
        self.assertEqual(rt.accepted_candidate(merged, approved, "t11z", "2026-11-01T00:00:00Z"), 5)
        self.assertIsNone(rt.accepted_candidate(merged, approved, "t11z", "2026-11-21T00:00:00Z"))
        self.assertIsNone(rt.accepted_candidate(merged, stale, "t11z", None))
        self.assertIsNone(rt.accepted_candidate(merged, by_bot, "t11z", None))

    def test_set_version(self):
        self.assertEqual(set_version.pep440("1.4.0-rc.2"), "1.4.0rc2")
        text, ok = set_version.set_toml_version('[project]\nname = "x"\nversion = "1.0.0"\n[tool.x]\nversion = "9"\n', "project", "1.1.0")
        self.assertTrue(ok)
        self.assertIn('version = "1.1.0"', text)
        self.assertIn('version = "9"', text)


if __name__ == "__main__":
    unittest.main()
