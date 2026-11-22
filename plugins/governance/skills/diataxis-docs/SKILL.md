---
name: diataxis-docs
description: Structure and write user documentation with Diátaxis. Use when a feat PR needs docs, when fixing docs drift, or when setting up a docs site.
---
Where
- Small project: README with the sections Tutorial, How-to guides, Reference, Explanation.
- Library, or more than a handful of features (`docs.site: true` in `.governance/profile.yml`): `docs/tutorials/`, `docs/how-to/`, `docs/reference/`, `docs/explanation/`.
- API reference is generated (mkdocstrings, TypeDoc, rustdoc, pkgsite): document in docstrings, not by hand.

Kinds
- Tutorial: learning by doing, one path that always works.
- How-to: steps to a goal for a competent user.
- Reference: complete, factual, structured like the code.
- Explanation: background and reasons.

Rules
- English. If the software has locale files, translations are generated at release; write English only.
- Docs ship with the feature on next; main never documents unreleased behaviour.
- Screenshots come from Playwright runs (web) or vhs tapes (CLI). Reference generated files; no hand-made images.
- No user-facing change: label `docs:none` and give the reason in the PR body.
- A new docs site needs a design-system decision: open `po:decision`; only the site waits, the feature does not.
