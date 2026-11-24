"""Cross-file consistency: callers, reusable workflows, rulesets, prompts, config."""
import json
import re
import unittest

from helpers import ROOT
import govlib
import housekeeping
import install

WF = ROOT / ".github" / "workflows"


def load(path):
    return govlib.yaml_load(path.read_text(encoding="utf-8"))


class ConsistencyTest(unittest.TestCase):
    def callers(self):
        return {p.name: load(p) for p in sorted((ROOT / "callers").glob("governance-*.yml"))}

    def test_callers_are_thin_and_reference_reusable_workflows(self):
        for name, doc in self.callers().items():
            for job_id, job in doc["jobs"].items():
                self.assertNotIn("steps", job, f"{name}:{job_id}")
                m = re.fullmatch(r"nullthrone/governance/\.github/workflows/([\w-]+\.yml)@__GOVERNANCE_SHA__", job["uses"])
                self.assertIsNotNone(m, f"{name}:{job_id}: {job['uses']}")
                target = WF / m.group(1)
                self.assertTrue(target.exists(), target)
                self.assertIn("workflow_call", load(target)["on"], target)

    def test_required_checks_exist(self):
        produced = set()
        for doc in self.callers().values():
            for job_id, job in doc["jobs"].items():
                called = load(WF / job["uses"].split("/")[-1].split("@")[0])
                for called_id, called_job in called["jobs"].items():
                    produced.add(f"{job_id} / {called_job.get('name', called_id)}")
        for path in (ROOT / "rulesets").glob("*.json"):
            for rule in json.loads(path.read_text())["rules"]:
                if rule["type"] == "required_status_checks":
                    for check in rule["parameters"]["required_status_checks"]:
                        self.assertIn(check["context"], produced, path.name)
                        self.assertEqual(check["integration_id"], 15368)

    def test_required_check_jobs_have_no_job_level_if(self):
        # A skipped job counts as success for required checks; decisions must happen in steps.
        # Documented exception: the base-change guard caller job in governance-pr-meta.yml.
        contexts = {c["context"] for p in (ROOT / "rulesets").glob("*.json") for r in json.loads(p.read_text())["rules"] if r["type"] == "required_status_checks" for c in r["parameters"]["required_status_checks"]}
        for name, doc in self.callers().items():
            for job_id, job in doc["jobs"].items():
                called = load(WF / job["uses"].split("/")[-1].split("@")[0])
                for called_id, called_job in called["jobs"].items():
                    if f"{job_id} / {called_job.get('name', called_id)}" in contexts:
                        self.assertNotIn("if", called_job, f"{job_id}/{called_id}")
                        if (name, job_id) != ("governance-pr-meta.yml", "guard"):
                            self.assertNotIn("if", job, f"{name}:{job_id}")

    def test_required_check_jobs_reject_shared_head_commits(self):
        contexts = {c["context"] for p in (ROOT / "rulesets").glob("*.json") for r in json.loads(p.read_text())["rules"] if r["type"] == "required_status_checks" for c in r["parameters"]["required_status_checks"]}
        via_load_pr = {"guard", "title", "docs", "wip", "gate", "candidate-approval", "review-mode", "unique-head"}
        for doc in self.callers().values():
            for job_id, job in doc["jobs"].items():
                called = load(WF / job["uses"].split("/")[-1].split("@")[0])
                for called_id, called_job in called["jobs"].items():
                    if f"{job_id} / {called_job.get('name', called_id)}" not in contexts:
                        continue
                    runs = " ".join(str(step.get("run", "")) for step in called_job["steps"])
                    self.assertTrue(any(f"checks.py\" {cmd}" in runs for cmd in via_load_pr), f"{job_id}/{called_id}")

    def test_callers_grant_nested_job_permissions(self):
        # GitHub validates this statically: one nested job asking for more than its caller job grants
        # makes the whole caller workflow fail at startup, even when that job would be skipped.
        level = {"none": 0, "read": 1, "write": 2}
        for name, doc in self.callers().items():
            for job_id, job in doc["jobs"].items():
                granted = job.get("permissions") or {}
                called = load(WF / job["uses"].split("/")[-1].split("@")[0])
                requests = [("workflow", called.get("permissions") or {})]
                requests += [(called_id, called_job.get("permissions") or {}) for called_id, called_job in called["jobs"].items()]
                for called_id, wanted in requests:
                    if not isinstance(wanted, dict):
                        continue
                    for scope, access in wanted.items():
                        self.assertGreaterEqual(
                            level[granted.get(scope, "none")], level[access], f"{name}:{job_id} -> {called_id} needs {scope}: {access}"
                        )

    def test_secrets_passed_match_declared(self):
        for name, doc in self.callers().items():
            for job_id, job in doc["jobs"].items():
                called = load(WF / job["uses"].split("/")[-1].split("@")[0])
                declared = set((called["on"]["workflow_call"] or {}).get("secrets") or {})
                passed = job.get("secrets")
                # Least privilege: callers pass named secrets, never all of them (Semgrep secrets-inherit).
                self.assertNotEqual(passed, "inherit", f"{name}:{job_id}")
                self.assertEqual(set(passed or {}) - declared, set(), f"{name}:{job_id}")
                required = {k for k, v in ((called["on"]["workflow_call"] or {}).get("secrets") or {}).items() if v and v.get("required")}
                self.assertEqual(required - set(passed or {}), set(), f"{name}:{job_id}")

    def test_schedule_matches_housekeeping(self):
        doc = self.callers()["governance-schedule.yml"]
        crons = [entry["cron"] for entry in doc["on"]["schedule"]]
        self.assertEqual(crons, [housekeeping.NIGHTLY, housekeeping.WEEKLY, housekeeping.MONTHLY])
        options = set(doc["on"]["workflow_dispatch"]["inputs"]["task"]["options"])
        self.assertEqual(options, set(housekeeping.TASKS) | set(housekeeping.DETERMINISTIC) | {"labels"})
        self.assertIn(housekeeping.WEEKLY, doc["jobs"]["labels"]["if"])

    def test_prompts_and_agents_exist(self):
        agents = {p.stem for p in (ROOT / "plugins/governance/agents").glob("*.md")}
        self.assertEqual(agents, {"triager", "reviewer", "implementer", "doc-writer"})
        for task, meta in housekeeping.TASKS.items():
            self.assertTrue((ROOT / "prompts/jobs" / f"{task}.md").exists(), task)
            if meta["agent"]:
                self.assertIn(meta["agent"], agents)
        for wf in WF.glob("*.yml"):
            text = wf.read_text()
            for job in re.findall(r"--job ([\w-]+)", text):
                self.assertTrue((ROOT / "prompts/jobs" / f"{job}.md").exists(), f"{wf.name}: {job}")
            for agent in re.findall(r"--agent ([\w-]+)", text):
                self.assertIn(agent, agents, wf.name)

    def test_reusable_workflows_check_out_governance_at_job_sha(self):
        for wf in WF.glob("*.yml"):
            if wf.name.startswith("self-"):
                continue
            text = wf.read_text()
            if "$GOV" in text:
                self.assertIn("ref: ${{ job.workflow_sha }}", text, wf.name)
            self.assertNotIn("pull_request_target", text, wf.name)

    def test_claude_steps_use_app_token_and_plugin(self):
        for wf in WF.glob("*.yml"):
            doc = load(wf)
            for job in doc.get("jobs", {}).values():
                for step in job.get("steps", []):
                    if str(step.get("uses", "")).startswith("anthropics/claude-code-action"):
                        args = step["with"]
                        self.assertIn("steps.", args["github_token"], wf.name)
                        self.assertIn("--plugin-dir", args["claude_args"], wf.name)
                        self.assertIn("--allowedTools", args["claude_args"], wf.name)

    def test_config(self):
        cfg = govlib.load_config()
        self.assertEqual(set(cfg["models"]), {"small", "medium", "large"})
        self.assertIn(f"{cfg['bot_app_slug']}[bot]", cfg["bots"])
        self.assertNotIn("feat", cfg["commit_types"]["main"])
        marketplace = json.loads((ROOT / ".claude-plugin/marketplace.json").read_text())
        self.assertEqual(marketplace["name"], cfg["marketplace_name"])
        self.assertEqual(f"{marketplace['plugins'][0]['name']}@{marketplace['name']}", cfg["plugin"])

    def test_labels_cover_workflow_usage(self):
        names = {lbl["name"] for lbl in govlib.yaml_load((ROOT / "labels.yml").read_text())}
        used = set()
        for path in list(WF.glob("*.yml")) + list((ROOT / "scripts").glob("*.py")) + list((ROOT / "prompts/jobs").glob("*.md")):
            used |= set(re.findall(r"(?:--add-label|--label|label(?:ed)?)\s+[\"'`]?((?:po|type|docs|automation):[a-z-]+|in-progress|blocked|adopting|needs-info|duplicate|idea)\b", path.read_text(encoding="utf-8")))
        self.assertEqual(used - names, set())

    def test_caller_names_cover_all_templates(self):
        self.assertEqual(len(install.caller_names("private")), 6)
        self.assertEqual(len(install.caller_names("public")), 7)


if __name__ == "__main__":
    unittest.main()
