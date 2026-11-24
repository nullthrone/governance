# Onboarding prompt

Run locally in the target repository, in a Claude Code session started by the owner with their `gh` login (admin rights).
If the repository already enables the governance plugin, start the session with `GOVERNANCE_OWNER_SESSION=1 claude` so the guard hook lets the owner's session edit protected paths.

```markdown
Onboard this repository to the governance defined in nullthrone/governance (read its README.md and ARCHITECTURE.md first). This session is run by the owner with admin rights. The result must be: the repo works exclusively through the governance repo, no legacy remains, and governance-audit passes completely.

Assume parts may already exist in any state. Always work from audit results, never from assumptions.

0. Setup: clone nullthrone/governance outside this repo and pin its current main:
   `git clone https://github.com/nullthrone/governance "$TMPDIR/governance" && GOV="$TMPDIR/governance" && SHA=$(git -C "$GOV" rev-parse HEAD)`.
   REPO = this repository as OWNER/NAME; VIS = public or private (`gh repo view --json visibility`).
1. Inventory: `python3 "$GOV/scripts/governance_audit.py" --repo-dir . --repo "$REPO" --json "$TMPDIR/audit-before.json"`. Save the JSON; do not commit it.
2. Profile: `python3 "$GOV/scripts/detect_profile.py" --repo-dir .` (and read an existing .governance/profile.yml). Show the owner only the fields listed under `uncertain` with your proposal and ask for confirmation in one message. Write the confirmed profile to .governance/profile.yml with `uncertain: []`.
3. Plan: for every audit finding decide keep / replace / remove. Typical legacy: old release or CI workflows, a develop branch, custom hooks or settings in .claude/, CLAUDE.md rules contradicting the governance, PyPI tokens after switching to trusted publishing, home-grown labels.
4. Rebuild without asking: replace or delete files (git history preserves them).
   - `python3 "$GOV/scripts/install.py" --repo-dir . --sha "$SHA" --visibility "$VIS" --repo "$REPO" --prune-workflows --prune-claude`
     writes the thin workflow callers pinned by SHA (.github/workflows/governance-*.yml, scorecard.yml for public repos), .claude/settings.json (plugin pinned, attribution disabled), .governance/release-please-config.json, .release-please-manifest.json, .github/dependabot.yml, issue and discussion forms (public), and CLAUDE.md / ARCHITECTURE.md from the templates.
   - Last release tagged `<name>-v<version>` (released with governance before 2026-11-24): before the new config reaches main, create the tag `v<version>` on the same commit (`git tag v<version> <name>-v<version>^{commit} && git push origin refs/tags/v<version>`). release-please finds the last release by that tag; without it, the next release PR spans the whole history. Release tags cannot be deleted once pushed.
   - Migrate still-valid project facts from the old CLAUDE.md and docs into "Current decisions" in ARCHITECTURE.md (max 60 lines); keep CLAUDE.md "Project notes" empty unless something cannot live elsewhere.
   - Remove foreign release mechanisms (semantic-release, bumpversion, goreleaser, release-drafter, old publish workflows). Make sure the version smoke test works: `commands.version` must print the version from .release-please-manifest.json.
   - Public repos: add the OpenSSF Scorecard badge to the README.
   - Commit as the owner with Conventional Commits, no attribution. Before rulesets exist, push to main directly; once they exist, open a PR and let the required checks pass.
   - Create next from main if missing: `gh api -X POST "repos/$REPO/git/refs" -f ref=refs/heads/next -f sha="$(git rev-parse origin/main)"`.
   - Apply settings, rulesets and labels via gh api: `python3 "$GOV/scripts/repo_settings.py" --repo "$REPO" --repo-dir .` (rulesets, merge settings, Actions permissions, Discussions/CodeQL/secret scanning/push protection/private vulnerability reporting for public repos, Pages, environments) and `python3 "$GOV/scripts/sync_labels.py" --repo "$REPO"`.
   - Trusted publishing where the repo publishes packages: tell the owner the exact publisher settings to enter on the registry (repository, workflow `governance-push.yml`, environment `release`); never create or store publish tokens.
   - Check that the prerequisites from $GOV/docs/MANUAL-STEPS.md exist for this repo (variable GOVERNANCE_APP_ID, secrets GOVERNANCE_APP_PRIVATE_KEY and CLAUDE_CODE_OAUTH_TOKEN, governance app installed). Do not create secrets or tokens; list what is missing.
5. One confirmation: collect everything irreversible (secrets to delete, branches with unmerged commits, repo settings, Pages config, labels to prune with `sync_labels.py --prune`) in one list, ask the owner once, then remove all approved items in one pass.
6. Verify: run governance-audit again. Fix every failure and repeat until it passes. A second run of this prompt on a finished repo must change nothing (`install.py` then prints `unchanged`).
7. Anything the governance cannot express: do not work around it. Open an issue labeled po:decision in nullthrone/governance describing what is missing.

No Claude attribution in commits or PRs. Final report in German: what changed, what was removed, audit result, open po:decision items, missing manual prerequisites.
```
