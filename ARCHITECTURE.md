# Architecture

This repository is the governance. Its files are the normative source: workflows, scripts, rulesets, labels, `config/governance.json`, the plugin and the prompts define behaviour; this file explains how they fit together.

## Components

Five layers. The lower a layer, the less the model can influence it.

| Layer | Implemented by |
| --- | --- |
| 1 Owner | Approvals (`po:ready`, candidate PR, fork PR, cost) and changes to this repository |
| 2 Orchestration | Reusable workflows `.github/workflows/*.yml`, thin callers `callers/`, digest routine `prompts/digest.md` |
| 3 Model | Plugin `plugins/governance/` (subagents, skills, templates), job prompts `prompts/jobs/` |
| 4 Deterministic layer | `scripts/` (gates, classification diff, audit, pre-filters), CI, PreToolUse hook `hooks/guard.py` |
| 5 Platform | `rulesets/`, `scripts/repo_settings.py`, governance app permissions, secrets |

## Data flows

Branch and release model per project repository: `main` is released, `next` collects new user-visible features, at most one acceptance PR `next → main`.

| Change | Target | Gate |
| --- | --- | --- |
| `fix`, `fix(security)`, `fix(deps)`, `refactor`, `perf`, `chore`, `test`, `build`, maintainer `docs` | `main` | CI + Claude review, squash auto-merge, patch release |
| `feat` with its user docs | `next` | CI + Claude review + docs-required + WIP limit, squash auto-merge |
| `feat!` / breaking | `next` | only from an issue the owner released after a `po:decision` |

- Issue → triage (small model) → owner applies `po:ready` → po-ready-gate verifies the actor in the issue timeline → nightly roadmap pre-filter picks one issue → implementer PR.
- Push to `main` → release-please (release PR auto-merges; minor/major only after an owner-accepted candidate) → docs to Pages, deploy, smoke test, automatic rollback to the previous tag; plus sync PR `main → next` (merge commit).
- Push to `next` → RC tag, preview (deployment, TestPyPI or build artifact), screenshots, candidate PR with changes, preview link, test script from the feature PRs → owner approves the current head → merge commit → minor release.
- Schedule → pre-filters (`scripts/housekeeping.py`) → Claude only when a tool found something; audit, cleanup and fuzzing need no model.
- Fork PR → scheduled pre-qualification (`po:review`) → owner approval (roadmap decision) → Claude ports it with co-author credit and closes the fork PR.

## Boundaries

- Self-modification is excluded in four layers: project repos hold only references (SHA pin, callers, profile); the bot token has no `workflows` permission; the required check `governance-guard` rejects protected-path changes not made and pushed by the owner, and required checks are bound to the GitHub Actions app; the PreToolUse hook blocks the edits early (saves tokens).
- A required check is decided per head commit: every gate fails while another open PR shares the commit, because GitHub applies the latest check run of a name to every PR with that head.
- Text from issues, PRs and discussions is data and never starts implementation. Fork code never runs privileged; no `pull_request_target`.
- An approval counts only if a deterministic step proves the owner gave it: label actor in the timeline, owner review on the current head commit.
- Interactive sessions with the owner's `gh` login act as the owner; there Claude applies `po:ready` only on explicit instruction.
- Only the owner changes this repository, in sessions the owner starts. No routine or autonomous agent runs here.

## Current decisions

- **Bot identity**: autonomous jobs use the app `nullthrone-governance` without `workflows` permission; its token goes to `claude-code-action`. The official Claude app requests workflows:write. (2026-11-22)
- **No `pull_request_target`**: blocked by default in public repos since 2026-12-02 and a privilege risk; fork PRs are handled by scheduled jobs. (2026-11-22)
- **Required-check jobs never use job-level `if`**: GitHub counts a skipped job as success. Decisions happen in steps. Exception: the base-change guard in `governance-pr-meta.yml`, whose skipped caller job produces no check of that name. (2026-11-22)
- **Promotions use merge commits, issue PRs squash**: release-please sees each feature in the changelog; one squash commit per issue keeps features revertible. (2026-11-22)
- **Minor/major releases require an owner-accepted candidate**: the release PR auto-merges only for patches or when an approved `next → main` merge is in the range; otherwise `po:decision`. Covers commit messages that bypass the title check. (2026-11-22)
- **`security`/`deps` as `fix(security)`/`fix(deps)`**: release-please cuts patches only for `fix`. (2026-11-22)
- **release-please config in `.governance/`** (protected), manifest at the repo root because every release changes it. (2026-11-22)
- **Governance tooling is checked out at `job.workflow_sha`** (GitHub, Sept 2026; not on GHES), so callers carry one pin only. (2026-11-22)
- **Scorecard runs as an own workflow** in public repos; scorecard-action cannot publish from a reusable workflow. It is the only non-caller workflow the audit allows. (2026-11-22)
- **Model tiers are aliases** (`haiku`/`sonnet`/`opus`) in `config/governance.json`; cost is controlled only here: frequencies, tiers, new jobs. (2026-11-22)
- **Owner decisions (`po:decision`)**: cost (recurring job, higher frequency, larger model, paid service or dependency, monitoring), breaking changes, governance changes and audit failures, yanking releases, design system for a new docs site, publishing advisories/CVEs. (2026-11-22)
- **Extended monitoring** (error rates, Sentry) is a per-project cost decision, not standard. (2026-11-22)
- **Language**: English for code, docs and repository communication; user docs are translated into the software's locales at each release. (2026-11-22)
- **Accepted risks**: Claude reviews Claude (correlated errors; the deterministic layer comes first). A feature misclassified as `fix` reaches production without acceptance (API/CLI diff and rollback limit it). Interactive owner sessions bypass the actor check. Prompt injection via issues and fork PRs (minimal rights, `po:ready`/`po:review` gates). A fork PR that changes `.github/` can fake checks once the owner approves its workflow run: never approve runs of such PRs. (2026-11-22)
