# Manual steps for the owner

Everything the governance cannot do by itself: creating credentials, installing apps, plan decisions and registry settings.
Order matters for steps 1–4. Nothing here was created automatically.

## 1. Governance GitHub App (bot identity without `workflows`)

Autonomous jobs must act under a bot identity whose token cannot change `.github/workflows/`.
The official Claude GitHub App requests **Workflows: read and write**, so it is not used for automation; jobs pass their own app token to `claude-code-action`.

- [x] Create a GitHub App (owner: your account) named **`nullthrone-governance`**. If the slug differs, update `bot_app_slug` and `bots` in `config/governance.json`.
  - Webhook: off. Installable: "Any account" (needed for several organizations).
  - Repository permissions: Contents **write**, Pull requests **write**, Issues **write**, Checks read, Actions read, Administration read (audit reads rulesets), Discussions read (Ideas digest), Metadata read.
  - **Workflows: no access.** Organization and account permissions: none.
- [x] Generate a private key.
- [x] Install the app on all orgs and your personal account (all repositories, or at least every governed repo plus each organization's `.github` repo).
- [x] Per organization: variable `GOVERNANCE_APP_ID` and secret `GOVERNANCE_APP_PRIVATE_KEY` (organization level, visible to all repositories). Personal-account repositories need them as repository variable/secret.
- [x] In `nullthrone/governance` itself: the same variable and secret (used by `self-sync-org-dotgithub`).

## 2. Claude token (cost decision)

- [x] `claude setup-token` and store the result as organization secret `CLAUDE_CODE_OAUTH_TOKEN` (and per personal repo).
  Background jobs share your personal plan's limits with interactive use; there is no priority mechanism. Frequencies and model tiers are in `config/governance.json` and `scripts/housekeeping.py`.

## 3. Organization settings

- [x] Each organization has a public `.github` repository (create it if missing), then run the workflow **self-sync-org-dotgithub** once (Actions → Run workflow).
- [x] If an organization restricts Actions: allow `nullthrone/governance/*` and the actions used in `.github/workflows/` (actions/*, github/codeql-action, googleapis/release-please-action, pypa/gh-action-pypi-publish, rust-lang/crates-io-auth-action, anthropics/claude-code-action, ossf/scorecard-action).
- [x] Optional: enable organization Discussions with the `.github` repository as source, so the Ideas link in the organization-wide issue forms works for repositories that are not onboarded yet.
- [x] Private repositories need GitHub Team (organization) or Pro (personal) for rulesets. Move personal private repositories into an organization if needed.

## 4. PO inbox (GitHub Project)

- [x] Create a Project on your user account, views: open `po:decision` · candidate PRs `next → main` · fork PRs with `po:review`.
- [x] Set `po_inbox.project_number` in `config/governance.json`.
- [x] Create a classic personal access token with `project` scope (plus `repo` for private repositories) and store it as organization secret `PROJECT_TOKEN`. Without it auto-add is skipped.
- [x] Check how many built-in auto-add workflows your plan allows; the Actions-based auto-add makes them unnecessary.

## 5. Per repository after onboarding

- [ ] **Trusted publishing** on the registry for every published package. Register the *calling* workflow `governance-push.yml` and environment `release` (PyPI, npm, crates.io), plus a TestPyPI publisher with the same workflow and no environment for candidate previews. Verify the first release: registries differ in how they treat reusable workflows. Then delete old publish tokens (the onboarding lists them).
- [ ] Deployments: put deploy secrets into the `production` environment and fill `commands.deploy`, `commands.smoke` and, for web previews, `commands.deploy_preview` in `.governance/profile.yml`.

## 6. Routines (Claude Code scheduled tasks)

- [ ] **Digest**: create a scheduled task from `prompts/digest.md`, daily 18:00 Europe/Berlin, small model, GitHub connector, push notifications on.
- [ ] Optional **immediate push on rollback**: create a routine with an API trigger and store its URL and token as secrets `ALERT_WEBHOOK_URL` / `ALERT_WEBHOOK_TOKEN`. `deploy.yml` posts `{"text": ...}` with a bearer token; verify the request format against the routine's trigger.

## 7. Hardening of this repository

- [ ] Ruleset on `main` of `nullthrone/governance`: PR required, status check `test` (self-ci), no force push, no deletion.
- [ ] Never approve the workflow run of a fork PR that changes `.github/`: its own workflow copy could report fake check results.
- [ ] Pin third-party actions to commit SHAs (for example with `pinact run` locally) for the OpenSSF Scorecard "Pinned-Dependencies" check; Dependabot keeps them current afterwards. `callers/scorecard.yml` uses `ossf/scorecard-action@v2.5.0`: up to v2.4.x the action image lived on gcr.io, which no longer serves it.

## 8. First end-to-end run on GitHub

The self-verification in this session ran against a local repository only (no GitHub login, repository creation outside `nullthrone/governance` blocked). Before rolling out:

- [ ] Create a throwaway repository, e.g. `nullthrone/governance-sandbox` (public), from `scripts/new_project.py` or with some legacy content.
- [ ] Run `prompts/onboard.md` there locally with your `gh` login; the audit must pass in full mode (`python3 scripts/governance_audit.py --repo-dir . --repo nullthrone/governance-sandbox`).
- [ ] Exercise the flow once: issue → `po:ready` (by you) → `governance-schedule` with task `roadmap` → PR into next → candidate PR → approve → release. Watch especially: required check names, `job.workflow_sha` checkout, app-token identity of `claude-code-action`, release-please PR auto-merge and the release gate, and that `governance-guard` can read the repository activity API with `GITHUB_TOKEN` (it fails closed for protected-path PRs otherwise; if needed, disable the ruleset briefly to land the fix).
- [ ] Delete the sandbox afterwards.

## Verified in this session

- Claude Code 2.1.330: `claude plugin validate` passes for marketplace and plugin; the PreToolUse guard blocks a write to `.github/workflows/` in a real headless session.
- Settings format: `extraKnownMarketplaces.<name>.source.ref` with a full commit SHA (Claude Code ≥ 2.1.324) and `"attribution": false` (≥ 2.1.281).
- `job.workflow_sha` / `job.workflow_repository` exist since September 2026 (not on GitHub Enterprise Server).
- `pull_request_target` is blocked by default in public repositories from 2026-12-02; the governance does not use it.
