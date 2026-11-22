import unittest

from helpers import ROOT  # noqa: F401
import govlib


class YamlTest(unittest.TestCase):
    def test_nested_structures(self):
        doc = """
version: 1
profiles: [library, cli]
commands:
  setup: pip install -e ".[dev]"  # comment
  multi: |
    echo a
    echo b
fuzz:
  targets:
  - name: parse
    command: run -t={seconds}
empty: []
flag: true
"""
        data = govlib.yaml_load(doc)
        self.assertEqual(data["profiles"], ["library", "cli"])
        self.assertEqual(data["commands"]["setup"], 'pip install -e ".[dev]"')
        self.assertEqual(data["commands"]["multi"], "echo a\necho b\n")
        self.assertEqual(data["fuzz"]["targets"][0], {"name": "parse", "command": "run -t={seconds}"})
        self.assertEqual(data["empty"], [])
        self.assertIs(data["flag"], True)

    def test_roundtrip_tricky_scalars(self):
        for value in ["yes", "1.0", "- x", "a: b", "#x", " pad", "", "null", "3", "@x", "-x", "${{ x }}", "000000", "a#b"]:
            self.assertEqual(govlib.yaml_load(govlib.yaml_dump({"k": value}))["k"], value, value)

    def test_roundtrip_document(self):
        data = {"a": {"b": [1, "two", {"c": None}], "d": {}}, "e": [[1, 2], []], "f": "x y"}
        self.assertEqual(govlib.yaml_load(govlib.yaml_dump(data)), data)

    def test_rejects_bad_indentation(self):
        with self.assertRaises(govlib.YamlError):
            govlib.yaml_load("a:\n  b: 1\n   c: 2\n")


class ConventionalCommitTest(unittest.TestCase):
    def test_parse(self):
        self.assertEqual(govlib.parse_cc("feat(api)!: add x")["breaking"], True)
        self.assertEqual(govlib.parse_cc("fix: y")["type"], "fix")
        self.assertIsNone(govlib.parse_cc("Fix: y"))
        self.assertIsNone(govlib.parse_cc("feat:missing space"))
        self.assertTrue(govlib.is_feat("feat: z (#12)"))
        self.assertFalse(govlib.is_feat("fix(feat): z"))


if __name__ == "__main__":
    unittest.main()
