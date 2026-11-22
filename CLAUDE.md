# CLAUDE.md

This repository is the governance itself and its own specification: README.md, ARCHITECTURE.md, `config/`, `rulesets/`, `labels.yml`, workflows, scripts, plugin and prompts are normative. There is no separate spec document; do not create one. Keep README.md and ARCHITECTURE.md (Current decisions, max 60 lines) in sync with every change.

- Only the owner changes this repository, in sessions the owner starts.
- Tests: `python3 -m unittest discover -s tests`. Workflow lint: `pip install actionlint-py shellcheck-py && actionlint`.
- `tests/test_repo_consistency.py` ties callers, reusable workflows, rulesets, prompts and config together; extend it when adding a link between files.
- Project repos consume this repo by SHA pin. Changing `callers/`, templates or `org-dotgithub/` makes every project drift until it is re-onboarded (the audit reports it).
- English, Conventional Commits, no attribution.
