"""Prompt assembly for Claude jobs."""
import unittest

from helpers import ROOT  # noqa: F401
import build_prompt
import govlib


class BuildPromptTest(unittest.TestCase):
    def test_review_prompt_names_the_owner(self):
        owner = govlib.load_config()["owner"]
        prompt = build_prompt.build("review", "reviewer", {"pr": "7", "repo": "o/demo", "sast_file": "x", "owner": owner}, None)
        self.assertIn(f"The governance owner is `{owner}`.", prompt)
        self.assertIn("governance owner named in the job instructions", prompt)

    def test_main_supplies_the_owner_by_default(self):
        from unittest import mock

        with mock.patch.object(govlib, "set_output"), mock.patch("builtins.print") as printed:
            build_prompt.main(["--job", "review", "--agent", "reviewer", "--tier", "large",
                               "--var", "pr=7", "--var", "repo=o/demo", "--var", "sast_file=x"])
        self.assertIn(f"`{govlib.load_config()['owner']}`", printed.call_args.args[0])


if __name__ == "__main__":
    unittest.main()
