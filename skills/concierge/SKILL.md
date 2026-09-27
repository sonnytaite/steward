---
name: concierge
description: The agent that keeps track of the agents. "/steward:concierge" rebuilds the registry of every agent, harness and repo from git, READMEs, handovers and the vault and regenerates the local console; "/steward:concierge <agent>" answers "where did I get to with this and what is next" from the derived record plus Sonny's own overlay, and offers to update the overlay through the gate. Use it when you have lost track of a build, before resuming one, or weekly with the brief.
argument-hint: "[<agent-or-repo-name>] [--no-crawl]"
---

# /steward:concierge — where did I get to

Read `${CLAUDE_PLUGIN_ROOT}/steward/handbook.md` § Concierge first.

## 1. Refresh the registry (skip with --no-crawl)

```
python3 "${CLAUDE_PLUGIN_ROOT}/rails/concierge.py" crawl
python3 "${CLAUDE_PLUGIN_ROOT}/rails/concierge.py" console
```

The registry (`<vault>/surfaces/steward/concierge/registry.json`) is derived: never edit it. The overlay (`overlay.json`) is Sonny's words: only edit it through `note`, after his verdict. The overlay's `_dashboards` list is the curated inventory of local dashboards, dev servers and services (url, start_cwd, start_cmd, setup, what, why, repo, next, scope); the console renders it as the Dashboards section at the top, derives last touched from git at generation time, and checks each URL live from the page. Add or change an entry there when a build gains a UI. The crawl also lists every rendered page Sonny can open (HTML, with any PDF beside it) as the registry's `artefacts`, over the known set (registered repos, overlay agents, dashboard repos) plus the whole research repo and the vault's share folder, with the `concierge_skip` rules kept; the console shows them as Visualisations, Articles, Research and a folded Unfiled list, each with a count and a filter box. The rules (research path, then surface share or pack path or brief/article front matter, then visualisation words, `<svg>`, `<canvas>` or a chart library) and the exclusion list (ART_PRUNE_DIRS, ART_EXCLUDE) live in `rails/concierge.py`; every exclusion is listed on the page with its reason. The overlay's `_artefacts` (keyed by `~/` path) overrides category, title, blurb, why and data; write it only through `rails/concierge.py art --path <file> --category … --why … --by sonny`, after his verdict. The console is written to `<vault>/surfaces/steward/concierge/console.html`; `~/Desktop/Concierge.html` links to it.

## 2. No argument: the state of the estate

Print, in prose, under 200 words: how many agents, how many with a record, the drift list (`rails/concierge.py drift`), and the three agents most worth Sonny's attention this week (moved but unrecorded; idle with an open next step). Offer to write records for the unrecorded ones he names.

## 3. With an agent name: where did I get to

```
python3 "${CLAUDE_PLUGIN_ROOT}/rails/concierge.py" where <agent>
```

Then read, at most: the agent's README or CLAUDE.md, its latest handover (the `where` output names it), and the research project README it belongs to. Answer in this shape, under 250 words, leading with the stage:

- **Where you got to.** Stage on the ladder (idea, spec, prototype, harness, sandbox, pilot, production, parked), what works, what is stubbed, cite the file that says so.
- **Where you were going.** From the handover and README, in one or two sentences.
- **Logical next steps.** Two or three, smallest first, each with what it unblocks.
- **How to run it.** The command, if the repo says.
- **What has moved around it since.** Research projects, wiki pages or other agents touched more recently that bear on it.

Then propose an overlay record (stage, going, next, run) and ask (AskUserQuestion) whether to save it as written, save with his edits, or skip. On save:

```
python3 "${CLAUDE_PLUGIN_ROOT}/rails/concierge.py" note --agent <id> --stage "…" --going "…" --next "…" --run "…" --by sonny
python3 "${CLAUDE_PLUGIN_ROOT}/rails/concierge.py" console
```

Log it: `rails/steward.py log --event concierge --detail "<agent>: record updated"`. Commit `surfaces/steward/concierge/` in the vault.

## Guardrails

- The overlay is Sonny's account of his own work. Draft it from evidence, never invent stage or intent; where the evidence is silent, say "not recorded".
- Never write to wiki/. Never edit a repo's own files from here.
- Shielded text never enters the registry or the console (the crawler reads READMEs and git only).
