The owner approved external pull request #{pr} in {repo} by @{author} (roadmap decision). Port it:
classify the change, branch `claude/fork-{pr}` from the right base, apply the changes (re-implement where needed to meet project standards), add tests and docs, and add the trailer `Co-authored-by: {author} <{author_email}>` to the commit.
Open the PR, enable auto-merge, then comment on #{pr} with the link, thank the author, and close #{pr}.
