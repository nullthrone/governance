---
name: release-classification
description: Classify a change as a Conventional Commit type and choose the target branch (main or next). Use before branching, when writing PR titles and when reviewing.
---
| Change | PR title type | Target |
| --- | --- | --- |
| Bug fix, no new behaviour | `fix` | main |
| Security fix | `fix(security)` | main |
| Dependency update | `fix(deps)` runtime, `chore(deps)` dev-only | main |
| Refactor, performance without visible change | `refactor`, `perf` | main |
| Tests, build, maintainer docs, chores | `test`, `build`, `docs`, `chore` | main |
| Anything new for users: behaviour, public API, route, CLI flag, config option (with its user docs) | `feat` | next |
| Breaking change | `feat!` / `fix!` | next, only after `po:decision` on the issue |
| Revert | `revert` | branch that holds the reverted commit |

- New for users ⇒ `feat`, even when it solves a bug ("fix by adding `--retry`" is a feature).
- Removing or changing behaviour users rely on ⇒ breaking.
- CI fails a non-`feat` PR into main that changes public API, routes or CLI help output. Then the classification was wrong: retarget to next as `feat`; never work around the check.
- Corrections to features already on next go to next (`fix`).
- One issue ⇒ one PR ⇒ one squash commit.
- release-please derives versions (fix → patch, feat → minor, `!` → major). Never edit versions or the changelog by hand.
