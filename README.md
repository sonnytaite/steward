# steward

> One strong model with memory over a second brain. It watches the vault for decay and brings its owner the next thing. It proposes; the owner decides.

```
        Where this sits (★ = this plugin)
  ──────────────────────────────────────────────
  second brain (vault, git)
  ├─ surface plugin      ✔ capture · weave · share · scan
  ├─ ★ steward           ○ brief  (what needs you, weekly)
  │                      ✔ convene (deliberation as group work)
  │                      ✔ concierge (registry of agents + console)
  │     rails/steward.py ✔ facts · wake · dispose · log · shield
  │     agents           ✔ critic (read-only) · dissenter (read-only)
  │     state            → surfaces/steward/ in the vault
  └─ kete-aronui         ◐ session memory (TARS/CASE only today)
  ──────────────────────────────────────────────
  Gate: keep / act / drop, append-only. Test: 100 days.
```

## What it is

The vault is compiled knowledge with a Surface loop around it. Both the vault and the research repo decay: load-bearing pages go stale, decisions sit unanswered in handovers, connection pages get noted and never actioned. The steward makes that decay visible on a cadence and hands over the cheapest next action for each item, five items or fewer, refuted by a read-only critic before it is shown, and gated by a person. Its second verb, convene, runs a question as group work: three to five framings of the same model on a shared workspace, a dissenter the group cannot persuade, a consolidation that keeps the disagreement trail.

Design notes: `~/Projects/research/multi-model-synthesis/` (why one model, why the verifier is the scarce part, why convene not swarm) and the vault's `wiki/themes/personal-agent-stack.md`.

## Guarantees in code (rails/steward.py, 18 tests)

- **Shield.** A `do-not-syndicate` marker in frontmatter shields the whole page; a marker line in the body shields everything after it; a marker inside inline code or a link does not shield. Shielded text never enters a brief, a wake bundle or a workspace.
- **Facts are deterministic.** Stale load-bearing pages, orphans, broken links, open connection pages, waiting candidates, open decisions in the research repo (settled-decision headings skipped), git activity, an ordinary-stream sample seeded by date, prior dispositions.
- **State is append-only** and lives in the vault (`surfaces/steward/`), so git gives it to every machine.
- **Bounds are printed** with the facts: five items, twelve files, one pass.

## Use

```
/steward:brief                 # weekly: what needs you, then keep / act / drop
/steward:convene <question>    # deliberation as group work, then gate
/steward:concierge [agent]     # where did I get to; registry + console (~/Desktop/Concierge.html)
python3 rails/steward.py brief --save      # facts only
python3 rails/steward.py wake              # bounded wake bundle
python3 rails/steward.py shield-audit      # what the shield covers, and how
python3 -m unittest discover -s tests -v
```

Install (already done on this machine, user scope):

```
claude plugin marketplace add ~/Projects/steward
claude plugin install steward@steward-plugin
```

Weekly run: `bin/steward-weekly.sh` saves the facts, attempts a headless brief with `claude -p`, and commits `surfaces/steward/`. `bin/com.ogworks.steward.plist` schedules it for Monday 07:00 (`launchctl load ~/Library/LaunchAgents/com.ogworks.steward.plist`; `unload` to stop).

## Concierge

The agent that keeps track of the agents (the Dell debrief's concierge, at personal scale). `rails/concierge.py crawl` derives a registry of every repo and agent under the configured roots from git, READMEs, handovers and wiki mentions; `note` records Sonny's own account (stage, where he was going, next step, how to run) in an overlay the crawler never touches; `console` renders a standalone local HTML console (a Dashboards section at the top with every local dashboard's URL, start command, last touched and live up/down status, from the overlay's `_dashboards` list; then agents by stage, what moved, research streams, themes, insights, drift); `where <agent>` answers "where did I get to"; `drift` feeds the weekly brief. State: `<vault>/surfaces/steward/concierge/`.

## The three layers

- `steward/identity.md`: who it is, ten lines, changes rarely.
- `steward/handbook.md`: the rules and the shape of a brief; changes when verdicts teach something (changelog at the foot).
- workbook: `surfaces/steward/` in the vault (briefs, facts, dispositions, log), changes every run.

## Doctrine it inherits

Three-layer agent structure; harness pattern (deterministic code around the model); doer is not judge; loop bounds; keep the human in the ordinary stream; interfaces outlast implementation (the model is a parameter); the 100-day rule.

MIT.
