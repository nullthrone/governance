# governance

Central, Claude-native governance for all projects of the owner ([@t11z](https://github.com/t11z)).

Claude works autonomously; the owner decides only on product direction, user acceptance and cost.
Trust comes from the deterministic layer (CI, rulesets, hooks); model reviews are the second line of defence.

## How a project consumes this repo

| Building block | Where in the project repo | Pinned by |
| --- | --- | --- |
| Claude Code plugin (hooks, subagents, skills) | `.claude/settings.json` → `extraKnownMarketplaces` + `enabledPlugins` | commit SHA in `ref` |
| Reusable workflows | thin callers in `.github/workflows/` (copied from `callers/`) | commit SHA in `uses:` |
| Project parameters | `.governance/profile.yml` | — |
| Rulesets, labels | applied via `gh api` during onboarding | — |

Project repos never contain governance logic, only references. Changes to governance happen exclusively in this repo, in sessions started by the owner.

For interactive use outside governed repos: `/plugin install governance --marketplace nullthrone/governance`.

## Layout

```
.claude-plugin/marketplace.json   plugin marketplace
plugins/governance/               plugin: hooks, agents, skills, templates
.github/workflows/                reusable workflows (on: workflow_call); self-*.yml run for this repo only
callers/                          workflows installed into project repos (thin callers + scorecard.yml)
config/governance.json            central parameters: owner, bots, organizations, model tiers, limits
prompts/                          onboarding prompt, digest routine, prompts for Claude jobs (jobs/)
rulesets/                         ruleset templates (main, next, release tags)
labels.yml                        label taxonomy
scripts/                          governance-audit, detect-profile and helpers (Python, stdlib)
org-dotgithub/                    content for each organization's .github repo
template-repo/                    starting point for new projects
tests/                            unit and consistency tests (python3 -m unittest discover -s tests)
docs/                             MANUAL-STEPS.md
```

Open owner actions (app, secrets, project token, trusted publishing, routines): [`docs/MANUAL-STEPS.md`](docs/MANUAL-STEPS.md).

## Onboarding a repository

Run Claude Code locally in the target repo with the owner's `gh` login and give it [`prompts/onboard.md`](prompts/onboard.md).
The onboarding ends only when `scripts/governance_audit.py` passes. New projects: `python3 scripts/new_project.py ../my-tool --name my-tool`.

```bash
python3 scripts/governance_audit.py --repo-dir . --repo OWNER/NAME
```

## License

MIT
