import unittest

from helpers import make_repo
import detect_profile

PYPROJECT_LIB = """[project]
name = "acme-parse"
version = "1.2.3"
requires-python = ">=3.11"
[project.optional-dependencies]
dev = ["pytest", "ruff"]
"""
PYPROJECT_CLI = PYPROJECT_LIB + '[project.scripts]\nacme = "acme_parse.cli:main"\n'


class DetectProfileTest(unittest.TestCase):
    def detect(self, files):
        tmp, root = make_repo(files)
        self.addCleanup(tmp.cleanup)
        return detect_profile.detect(root), root

    def test_python_library(self):
        prof, _ = self.detect({"pyproject.toml": PYPROJECT_LIB, "src/acme_parse/__init__.py": "", "tests/test_x.py": ""})
        self.assertEqual(prof["language"], "python")
        self.assertIn("library", prof["profiles"])
        self.assertEqual(prof["package"], {"name": "acme-parse", "import_name": "acme_parse", "publish": "pypi"})
        self.assertEqual(prof["classification"]["api"], "griffe")
        self.assertEqual(prof["commands"]["test"], "pytest -q")
        self.assertEqual(prof["commands"]["lint"], "ruff check .")
        self.assertIn("importlib.metadata", prof["commands"]["version"])
        self.assertEqual(prof["preview"]["type"], "testpypi")
        self.assertTrue(prof["docs"]["site"])
        self.assertIn("profiles", prof["uncertain"])

    def test_python_cli(self):
        prof, _ = self.detect({"pyproject.toml": PYPROJECT_CLI, "src/acme_parse/__init__.py": ""})
        self.assertIn("cli", prof["profiles"])
        self.assertIn("input-processing", prof["profiles"])
        self.assertEqual(prof["commands"]["version"], "acme --version")
        self.assertEqual(prof["classification"]["surface"], ["acme --help"])

    def test_node_web_service(self):
        prof, _ = self.detect({
            "package.json": '{"name": "shop", "private": true, "scripts": {"build": "vite build", "lint": "eslint ."}, "dependencies": {"react": "19"}, "devDependencies": {"@playwright/test": "1"}}',
            "package-lock.json": "{}",
            "fly.toml": "",
        })
        self.assertEqual(prof["language"], "node")
        self.assertIn("web", prof["profiles"])
        self.assertIn("service", prof["profiles"])
        self.assertEqual(prof["commands"]["setup"], "npm ci")
        self.assertIn("e2e", prof["commands"])
        self.assertEqual(prof["preview"]["type"], "deployment")
        self.assertIn("commands.deploy", prof["uncertain"])

    def test_rust_bin_and_lib(self):
        prof, _ = self.detect({"Cargo.toml": '[package]\nname = "tool"\nversion = "0.1.0"\n', "src/main.rs": "fn main(){}", "src/lib.rs": "", "fuzz/fuzz_targets/parse.rs": ""})
        self.assertEqual(set(prof["profiles"]) & {"cli", "library"}, {"cli", "library"})
        self.assertEqual(prof["classification"]["api"], "cargo-semver-checks")
        self.assertEqual(prof["package"]["publish"], "crates")
        targets = detect_profile.fuzz_targets(prof, _)
        self.assertEqual(targets[0]["name"], "parse")

    def test_go_library_with_fuzz(self):
        prof, root = self.detect({"go.mod": "module example.com/lib\n\ngo 1.23\n", "lib.go": "package lib\n", "lib_test.go": "package lib\nfunc FuzzParse(f *testing.F) {}\n"})
        self.assertEqual(prof["classification"]["api"], "go-doc")
        self.assertEqual(prof["runtime_version"], "1.23")
        self.assertEqual(detect_profile.fuzz_targets(prof, root)[0]["name"], "FuzzParse")

    def test_unknown_language(self):
        prof, _ = self.detect({"main.c": ""})
        self.assertEqual(prof["language"], "other")
        self.assertIn("commands.test", prof["uncertain"])

    def test_locales(self):
        prof, _ = self.detect({"pyproject.toml": PYPROJECT_LIB, "locales/de.json": "{}", "locales/en.json": "{}", "locales/fr/x.json": "{}"})
        self.assertEqual(prof["docs"]["locales"], ["de", "fr"])

    def test_compare(self):
        prof, _ = self.detect({"pyproject.toml": PYPROJECT_CLI})
        self.assertEqual(detect_profile.compare(prof, prof), [])
        wrong = {**prof, "language": "node", "profiles": ["library"]}
        problems = detect_profile.compare(wrong, prof)
        self.assertTrue(any("language" in p for p in problems))
        self.assertTrue(any("cli" in p for p in problems))


if __name__ == "__main__":
    unittest.main()
