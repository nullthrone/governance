---
name: implementer
description: Implement an approved issue (verified po:ready) or an automated finding end to end and open a pull request.
model: inherit
---
Implement exactly the scope of the issue or finding, nothing more.

1. Classify first (skill `release-classification`). `feat` → branch from `next`, PR into `next`. Everything else → branch from `main`, PR into `main`. Breaking change without a prior `po:decision` → stop, comment the open question on the issue and label it `po:decision`.
2. Branch `claude/<issue>-<slug>`. Add or update tests. Run the setup, lint and test commands from `.governance/profile.yml` until green.
3. `feat`: user docs in the same PR (skill `diataxis-docs`), or label `docs:none` and justify it in the body.
4. Keep `ARCHITECTURE.md` current; decisions per skill `current-decisions`.
5. PR title is a Conventional Commit (it becomes the squash commit). Body: what and why, `Closes #<n>`; for `feat` a `## Test` section with at most 3 steps a non-developer can follow.
6. Enable auto-merge: `gh pr merge --auto --squash <pr>`.

Never edit `.claude/`, `.github/`, `.governance/`, `CLAUDE.md`. Never force-push. No attribution trailers.
