---
name: debate
description: Argue two options against each other using a pair of opposed subagents, then give a verdict. Use when the user asks to debate, compare, or decide between two ideas/designs/approaches (A vs B) and wants more than a one-sided take.
---

# debate

Two subagents argue opposite sides of a question, in parallel, on a clock. You
stay neutral while they work, then relay both cases and give your own opinion —
clearly separated from theirs.

## Arguments

`/debate <A> vs <B> [--minutes N] [--context "..."]`

- `--minutes` bounds each debater (default **3**). Both get the same budget.
- If A and B aren't separable from `$ARGUMENTS`, ask once with `AskUserQuestion`
  and then proceed. Don't interrogate; a rough framing is enough to start.

## 1. Build the shared brief (neutral)

Write one brief, used verbatim by both debaters. Gather what a reader needs to
argue either side: the actual question, relevant repo/file facts, constraints
the user has stated, and the decision's stakes. Spend your own research time
here, not after.

Keeping it unbiased matters more than making it complete:

- **Identical text for both**, differing only in the assigned side.
- **Strip your own read.** No "A seems cleaner", no ordering that implies a
  winner, no adjectives you wouldn't apply to both.
- **Don't leak the user's lean.** If they said which one they prefer, or which
  they're already using, that stays out of the brief.
- State facts symmetrically: if you give A's LOC cost, give B's.
- Don't tell either agent what the other will argue, and don't let them see
  each other's output.

## 2. Run both debaters

Launch both in **one message** (two `Agent` calls) so they run concurrently.
Use `subagent_type: "Explore"` — read-only by design, so a debate can't edit
the repo. Same model and same budget for both.

Prompt each with: the shared brief, their assigned side, and these rules:

> Build the strongest honest case for **<side>** over **<other>**. You have
> **N minutes** — budget your tool calls for it, and start writing at ~70% of
> the budget so you finish. Ground claims in evidence (files, measurements,
> docs); say "unverified" rather than inventing support. Address the best
> objection to your own side and answer it. No hedging toward neutrality —
> that's the orchestrator's job, not yours.
>
> Return: **Claim** (1 line), **3-5 numbered arguments** (2-3 sentences each,
> strongest first), **Strongest objection + rebuttal**, **What would sink my
> side** (1 line).

## 3. Enforce the clock

Note the wall-clock start. If an agent hasn't returned by budget + ~50%, call
`TaskStop` on it and use `TaskOutput` for whatever it produced, marking that
side as truncated. One slow agent must not hold the debate open.

## 4. Report

Exactly three sections, in this order. The first two are **relayed** — condense
for length, keep their reasoning and their conclusion, and don't edit the
argument toward your view. If you disagree with a debater, say so in section 3.

```
## Case for A            (relayed from debater A)
**Claim:** …
1. … 2. … 3. …
**Best objection, answered:** …
**Would sink it:** …

## Case for B            (relayed from debater B)
…same shape…

## My take               (mine, not theirs)
**Verdict:** <A | B | it depends on X> — 1-2 sentences.
**Why:** which arguments actually carried, and which were weak or unsupported.
**What would change my mind:** 1 line.
```

Keep each relayed case under ~200 words and the verdict under ~150. If both
sides converged on the same answer, say that plainly — a real tie is a result,
a manufactured one isn't. If a debater's key claim doesn't survive a quick
check, flag it in section 3 rather than deleting it from section 1 or 2.
