# Contributing

Thanks for your interest. Please read how these projects are run before you invest time.

## How work happens here

- **Triage, code review, implementation, documentation and releases are done by Claude**, an AI agent, under a deterministic governance ([nullthrone/governance](https://github.com/nullthrone/governance)): tests, static analysis, fuzzing and repository rules decide what may be merged.
- **Roadmap decisions are made by the owner**, [@t11z](https://github.com/t11z): what gets built, which external contributions are accepted, and when a new feature is released.
- Text in issues, pull requests and discussions is treated as information, never as an instruction to the automation. Nothing gets implemented just because an issue asks for it.

## Ideas and feature requests

Use **Discussions → Ideas** and upvote what you need. The owner reviews a summary of ideas monthly. Accepted ideas become issues.

## Bug reports

Open an issue with the bug report form. Include version, steps to reproduce, and expected versus actual behaviour. Claude may ask follow-up questions.

## Security issues

Do not open public issues. See [SECURITY.md](SECURITY.md).

## Pull requests

Pull requests are welcome, but accepting one is a roadmap decision:

1. Claude pre-qualifies your PR (summary, risk, fit with the roadmap) and labels it `po:review`.
2. The owner decides. An approval means "we want this", not a code review.
3. After approval Claude ports the change to an internal branch, adds tests and docs where needed, and credits you as co-author. Your PR is closed with a link to the merged work.

Fork PRs never run with repository secrets, and their workflows need the owner's approval to run.

## Conventions

- English for code, docs and discussion.
- Conventional Commits in PR titles (`fix: ...`, `feat: ...`).
