---
name: simplify
description: Holistically review a feature branch for simplifications that don't break requested features — code reuse, dead code, complexity reduction, readability, sharing with existing code outside the branch. Prioritizes reducing net LOC added and improving readability/reliability. Surfaces top suggestions with est. LOC savings and asks before implementing.
---

# simplify

Review the current feature branch as a whole and propose simplifications. The goal is to reduce net LOC added and make the change simpler, more readable, and more reliable — without removing any explicitly requested feature or behavior.

It is OK to find nothing. If the branch is already lean, say so plainly and stop. Do not invent low-value suggestions to fill space.

## Scope

Assume the branch is a feature branch targeting a GitHub PR against the repo's trunk.

1. Determine the trunk: `$GIT_TRUNK` if set, else `git symbolic-ref refs/remotes/origin/HEAD`, else `origin/main`.
2. Determine the merge base: `git merge-base HEAD <trunk>`.
3. Review the full branch diff against that merge base, plus the surrounding code it touches — not just the diff hunks. You need to see what already exists in the repo to spot reuse opportunities.

## What to look for

Consider all of these, but only surface what genuinely applies:

- **Reuse** — new code that duplicates an existing helper/util/component in the repo (inside or outside the branch). Even small dupes count if they add up.
- **Dead or legacy code** — code paths, flags, branches, params, imports, or files that this change makes unreachable or obsolete. Safe-to-remove only.
- **Over-abstraction** — new wrappers/classes/factories/indirections used in one place. Inline them.
- **Over-generality** — params, options, config knobs added "just in case" with no current caller exercising them.
- **Defensive cruft** — try/except, null guards, fallbacks for cases that can't happen given internal invariants.
- **Comment/docstring bloat** — multi-paragraph docstrings or what-comments restating the code.
- **Splittable/mergeable functions** — long functions that would read better split, or tiny helpers used once that should be inlined.
- **Tests** — redundant tests covering the same path, brittle change-detector tests, or large fixtures that could be shared.
- **Readability refactors** — renames, early returns, flattening nesting, removing intermediate vars that obscure intent.
- **Cross-branch sharing** — code that should live in a shared module so other in-flight work can reuse it.

Do NOT propose:
- Style nits already handled by the formatter/linter.
- Speculative future-proofing.
- Rewrites that change behavior the branch was explicitly asked to add.
- Wholesale architecture changes outside the branch's scope.

## Process

1. Confirm current branch and trunk; show the user what you're comparing.
2. Read the full diff. Then read the surrounding files (not just hunks) for the largest/most-suspicious changes.
3. Grep the broader repo for potential reuse targets when new utilities/helpers/components appear in the diff.
4. Draft a ranked list of candidate simplifications. Rank by (LOC saved + clarity gained) vs. (risk + churn).
5. Present the **top 3–5** (fewer is fine) to the user. For each include:
   - One-line description
   - Files affected
   - Estimated net LOC delta (e.g. "~-40 LOC")
   - Why it's safe (what behavior is preserved)
   - Any risk/caveat
6. Ask the user which ones to implement. Use `AskUserQuestion` with `multiSelect: true` so they can pick a subset. Include a "none — skip all" option.
7. Implement only the chosen items. After implementing, run available type-checks/tests for the affected areas if quick. Report final net LOC delta vs. the original branch.

## Output format for the suggestion list

```
Branch: <name> vs <trunk>   (<N> files changed, +<X>/-<Y>)

Candidate simplifications:

1. <short title>  (est. ~-NN LOC)
   <1–2 sentence description>
   Files: path/a.ts, path/b.ts
   Safe because: <invariant / preserved behavior>
   Risk: <none | low | …>

2. …
```

Keep descriptions tight. The user is reading to make a yes/no call per item, not to read an essay.

## If nothing meaningful turns up

Say so directly:

> Reviewed <N> files / +<X>/-<Y> LOC against <trunk>. Nothing worth changing — the branch is already lean.

Then stop. Do not pad with marginal suggestions.
