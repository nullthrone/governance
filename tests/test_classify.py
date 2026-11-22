import unittest

from helpers import ROOT  # noqa: F401
import classify_check


class ClassifyTest(unittest.TestCase):
    dump = {
        "pkg": {
            "kind": "module",
            "name": "pkg",
            "members": {
                "run": {"kind": "function", "name": "run", "parameters": [{"name": "x", "kind": "positional or keyword", "default": None}]},
                "_private": {"kind": "function", "name": "_private", "parameters": []},
                "Thing": {"kind": "class", "name": "Thing", "bases": ["object"], "members": [{"kind": "function", "name": "__init__", "parameters": []}, {"kind": "attribute", "name": "size"}]},
            },
        }
    }

    def test_griffe_surface(self):
        lines = classify_check.griffe_surface(self.dump)
        self.assertIn("function pkg.run(positional or keyword:x)", lines)
        self.assertIn("class pkg.Thing(object)", lines)
        self.assertIn("attribute pkg.Thing.size", lines)
        self.assertFalse(any("_private" in line for line in lines))

    def test_compare(self):
        base = {"api": ["a"], "surface": {"tool --help": ["-h"]}}
        same = {"api": ["a"], "surface": {"tool --help": ["-h"]}}
        added = {"api": ["a", "b"], "surface": {"tool --help": ["-h", "--new"]}}
        self.assertEqual(classify_check.compare(base, same), [])
        self.assertEqual(len(classify_check.compare(base, added)), 2)


if __name__ == "__main__":
    unittest.main()
