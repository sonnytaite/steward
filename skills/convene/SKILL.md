---
name: convene
description: Group work instead of a pipeline — for a question that deserves deliberation, run three to five framings of the same strong model concurrently on one shared workspace, let them read and answer each other, add a dissenter the group cannot persuade, consolidate with the disagreement trail kept, then gate. Run "/steward:convene <question>" for assessments, reviews, triage calls and research questions; never for execution loops.
argument-hint: "<question> [--lenses a,b,c] [--rounds 1|2] [--context path,path]"
---

# /steward:convene — deliberation as group work

Read `${CLAUDE_PLUGIN_ROOT}/steward/handbook.md` § Convene. This is the Navier-Stokes lesson at small scale: keep roles as permission boundaries, drop the sequencing, work on a shared object, keep one critic the group cannot persuade, verify outside the group, gate with a person.

## 0. Bounds

Five framings at most, two rounds at most, eight file reads per framing, one dissenter, one consolidation. If the question is really an execution task (write code, draft the document, run the pipeline), say so and decline: convene is for deliberation points.

## 1. Workspace

Create `<scratchpad>/convene-<slug>/` with:

- `question.md`: the question verbatim, what a good answer looks like, and the bounds.
- `context.md`: the relevant pages. Find them with Grep/Glob over the vault wiki and the research repo (respect the shield: skip pages whose frontmatter carries `do-not-syndicate`, and truncate any page at a body marker line). Eight pages at most, paths cited.
- `framings.md`: the lenses. Default to three chosen for the question (for example: evidence, cost, risk; or clinician, engineer, union; or for, against, what-would-change-my-mind). `--lenses` overrides.

## 2. Round one (independent, parallel)

Spawn one `general-purpose` agent per framing **in a single message** so they run concurrently. Each gets: the workspace path, its lens, the instruction to read `question.md` and `context.md` only (plus at most eight files it chooses), and to write `round1-<lens>.md`: its answer, its three strongest claims each with a citation, and the one thing that would change its mind. It must not read other framings' files in round one.

## 3. Round two (they read each other)

If `--rounds 2` (default): spawn the same framings again, each told to read all `round1-*.md`, then write `round2-<lens>.md`: what it now concedes, what it still disputes and why, and a revised answer. This is the messaging step; keep it to one round.

## 4. Dissenter (the critic the group cannot persuade)

Spawn the `steward-dissenter` agent (read-only) with the workspace. Its only job is to argue that the emerging consensus is wrong: the strongest counter-case, the claim with the weakest citation, the assumption everyone shared. It writes nothing; it returns text you save as `dissent.md`.

## 5. Consolidate

You (the doer) write `consolidated.md`: the answer, the disagreement trail (who conceded what, what stays disputed), the dissenter's strongest point and whether it survives, every claim with its citation, and what would change the answer. No claim without a path. Keep it under a page.

## 6. Gate

Present `consolidated.md` in conversation, leading with the answer. Ask (AskUserQuestion): **keep as a candidate** (copy to the vault's `surfaces/_inbox/` with provenance `convene://<slug>` so /weave can triage it), **act** (only if the action is inside the vault or research repo and reversible), or **drop**. Log with `rails/steward.py log --event convene --detail "<slug>: <verdict>"`.

## Guardrails

- Same model for every framing; diversity is in the lens, not the weights.
- The dissenter is read-only and is never one of the framings.
- Nothing shielded enters the workspace.
- Say the token cost at the end: N framings × rounds is N× a single answer, and that is the price of the disagreement trail.
