---
name: current-decisions
description: Maintain the "Current decisions" section of ARCHITECTURE.md. Use when making, changing or reverting an architecture decision.
---
- One entry per topic, 2–3 lines: `- **Topic**: decision. Reason. (YYYY-MM-DD)`
- Change of direction: overwrite the entry. No history in the file; `git log -p ARCHITECTURE.md` has it.
- Only what the code cannot tell: external constraints, tempting alternatives that were rejected, non-obvious trade-offs.
- Limit ~60 lines (CI fails above 60). When near the limit, merge related entries and drop what the code now makes obvious.
- Decisions with cost impact (paid service or dependency, new recurring job, higher frequency, larger model, monitoring): do not decide. Open an issue labeled `po:decision`.
