---
name: brief
description: The steward's weekly "what needs you" for the second brain — five items or fewer, each with why now, the cheapest action and its cost, refuted by a read-only critic before it is shown, then keep / act / drop verdicts recorded append-only. Run "/steward:brief" at the start of a week, after a burst of work, or whenever the vault feels stale. Never writes to wiki/ without a verdict.
argument-hint: "[--headless] [--date YYYY-MM-DD]"
---

# /steward:brief — what needs you

Read `${CLAUDE_PLUGIN_ROOT}/steward/identity.md` and `${CLAUDE_PLUGIN_ROOT}/steward/handbook.md` first. They are short and they are the rules.

## 1. Wake and facts

```
python3 "${CLAUDE_PLUGIN_ROOT}/rails/steward.py" wake
python3 "${CLAUDE_PLUGIN_ROOT}/rails/steward.py" brief --save
```

The second command prints the facts and saves `surfaces/steward/briefs/<date>-facts.{md,json}` in the vault. If either fails, report the error and stop. Do not build a brief without the facts.

If `--date` is given, pass it through to `brief`. If the wake shows verdicts still pending from the last brief, put them first in the conversation and collect them before composing a new one (headless: skip, note them in the header).

## 2. Judgement (one pass, twelve files)

From the facts, choose at most five items following the handbook's shape: up to three needs-a-decision, at least one ordinary-stream re-read, one what-moved line, optionally one read-this. Open only the files you need to write a true "why now" (twelve at most). Cite paths. Prefer items whose cheapest action is small and reversible. Respect the disposition tally: kinds that keep being dropped get raised less.

Draft the brief in this exact skeleton (the rails parse the `### N.` headings):

```
# What needs you — <date>

> steward brief · <n> items · status: draft | awaiting-disposition | disposed

First: <one sentence, the single thing to do first>

### 1. <item title>
**What.** …
**Why now.** … (cite path)
**Cheapest action.** …
**Cost.** …

### 2. …

**What moved.** <one sentence on commits in both repos>
```

## 3. Critic (doer is not judge)

Spawn the `steward-critic` agent with the draft and the facts path. It is read-only and adversarial. Amend or drop what it breaks; where you disagree, add a one-line note under the item. Do not skip this step.

## 4. Write, show, gate

Write the brief to `<vault>/surfaces/steward/briefs/<date>-brief.md`. Present it in conversation, leading with "First".

Interactive: ask for verdicts with AskUserQuestion, batched (one multiSelect question for **act**, one for **drop**; everything else is **keep**). Record each with:

```
python3 "${CLAUDE_PLUGIN_ROOT}/rails/steward.py" dispose --brief <date> --item <n> --verdict keep|act|drop --note "…"
```

Carry out each **act** only if it is inside the vault or the research repo and reversible in git (a link, a status line, a re-band of a number with the source cited, a commit). Anything else becomes a note. Update the brief's status line to `disposed`.

Headless (`--headless`, or no person present): set status `awaiting-disposition`, act on nothing, and stop after writing.

## 5. Log and commit

```
python3 "${CLAUDE_PLUGIN_ROOT}/rails/steward.py" log --event brief --detail "<date>: <n> items, <k> acted, <d> dropped"
```

Commit `surfaces/steward/` (and any acted changes) in the vault with message `steward: brief <date>` and push. If the handbook should learn something from the verdicts, append one line to its changelog in the plugin repo and commit there too.

## Guardrails

- Never quote shielded text. The rails strip it; do not go around them.
- No writes to `wiki/` without a verdict. No writes outside the vault and the research repo at all.
- Five items. Twelve files. One pass. Say when you hit a bound.
