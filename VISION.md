# Vision: what steward is, and what it refuses to become

steward exists so that one person's second brain does not decay unnoticed. A vault of compiled knowledge and a research repo both rot: load-bearing pages go stale, decisions sit unanswered in handovers, connections get noted and never actioned. The steward makes that decay visible on a cadence and brings its owner the next thing: five items or fewer, each with why now, the cheapest action and its cost, refuted by a read-only critic before it is shown, and gated by the owner's verdict. Its second verb runs a question as group work with a dissenter the group cannot persuade. It serves exactly one person, the owner of the vault. It owns exactly one thing: the standing question "what needs you". It does not own the vault, the research, the owner's calendar or the owner's decisions.

This page is the test a proposed change is read against. The verdicts below were settled by the owner on 6 October 2026.

## It proposes; the owner decides

Nothing enters the wiki without a verdict, and nothing is acted on without one. The gate is keep, act or drop, recorded append-only. An act is carried out only when it is inside the vault or the research repo and reversible by git. A change that lets the steward write to the wiki, send a message, or change a file outside its two repos without a verdict is refused, whatever the model's confidence. A change that makes a verdict cheaper to give, or an act easier to reverse, belongs. An act verdict on a decision sitting in a research handover may write the recorded cheapest action into that handover, as a git commit the owner can revert, and nothing wider. Running every act after the verdicts is allowed when acts run one at a time, each a separate commit, each inside the two repos, and the run stops at the first act that would touch anything else. Delivery of the brief (email, chat) is not the steward's: a separate, owner-configured channel reads the saved brief; the steward sends nothing. The steward does not read the owner's email or calendar: the moment it does it becomes an assistant, and the shield has no meaning there.

Test: name the verdict that makes the change take effect. If there is none, it is refused.

## One strong model, not a swarm

The steward is one strong model with memory. Deliberation, when a question deserves it, is three to five framings of the same model on one shared workspace with a dissenter, consolidated with the disagreement trail kept. The verifier is the scarce part, so the critic and the dissenter are never a cheaper model than the drafter. A change that blends models for consensus, or downgrades the critic to save tokens, is refused. A change that gives the one model better memory or better facts belongs. Convening with two different models for diversity is refused for the same reason blending is: the measured gain was nothing and the error amplification was real.

Test: is the judge at least the drafter's tier, and is there still exactly one voice that reaches the owner?

## The doer is not the judge

The agent that drafts the brief never grades it. A read-only critic tries to break every item (no citation, a misread file, an item already actioned or already dropped, a shielded quote, a cheapest action that is not the cheapest, a bound exceeded) before the owner sees it. A change that lets the drafter skip the critic, or lets the critic write, is refused. The critic rejects; the drafter amends. Two writers on one item is how disagreement disappears.

Test: after the change, can the critic still refuse an item, and can it still write nothing?

## Facts are deterministic, bounded and printed

Stale pages, orphans, broken links, open connection pages, waiting candidates, open decisions, git activity and the ordinary-stream sample come from a script with tests, not from the model's reading. The bounds (five items, twelve files, one pass) are printed with the facts and are not negotiable in the moment. A change that lets the model invent a fact, read beyond the bound, or hide the bound is refused. A change that adds a deterministic fact with a test belongs.

Test: is the new signal computed by `rails/`, with a test, and shown in the facts block?

## Shielded text never leaves

A `do-not-syndicate` marker shields a page or everything after it, in code. Shielded text never enters a brief, a wake bundle, a workspace or a convening. A change that weakens the shield, adds an exception, or lets a model quote around it is refused. The shield is the owner's trust in the tool; without it the tool is not run on real notes.

Test: does `shield-audit` still show every shielded span, and does every output path pass through it?

## The owner stays in the ordinary stream

Every brief carries at least one routine page to re-read with one question about whether it still holds. This is not filler: if the steward brings only hard items, the owner's judgement about their own knowledge decays into rubber-stamping. A change that drops the ordinary-stream item to make room for more alerts is refused. The cadence is the owner's to set in config (weekly by default), and five items stays five at any cadence. Items the owner always drops are suppressed by their recorded disposition, never by a guess about what the owner would drop.

## State is append-only and lives in the vault

Briefs, facts, dispositions and the log live in `surfaces/steward/` in the vault, so git gives them to every machine and the history is never rewritten. The plugin repo holds no personal state: paths, skip lists and labels live in the owner's git-ignored config. A change that moves state out of the vault, rewrites a disposition, or puts a personal path in a tracked file is refused. One steward serves one vault: a work vault and a personal vault are two homes, because vaults are separated by sensitivity and one steward over both would carry the shield across the boundary.

Test: after the change, is every tracked file generic, and is every record in the vault append-only?

## The 100-day rule

If a brief has not changed a decision or surfaced a miss by day 100, the steward should be stopped. Features are judged the same way: a change belongs if it makes a brief more likely to change a decision or catch a miss, and is refused if it only makes the steward busier.

## A change belongs when it

- makes a verdict cheaper to give or an act easier to reverse;
- adds a deterministic fact with a test, inside the bounds;
- gives the one model better memory of past verdicts;
- makes the critic or the dissenter harder to persuade;
- keeps the shield exact and makes it more visible;
- keeps the owner in the ordinary stream;
- keeps every tracked file generic and every record in the vault.

## A change is refused when it

- writes to the wiki, sends anything, or touches a file outside the two repos without a verdict;
- blends models, downgrades the critic, or adds a second voice that reaches the owner;
- lets the drafter skip the critic, or the critic write;
- lets the model invent a fact, read past the bound, or hide the bound;
- weakens the shield or adds an exception to it;
- drops the ordinary-stream item;
- moves state out of the vault, rewrites history, or tracks a personal path;
- grows the steward into a task manager, a chat agent, an inbox, or a general assistant.
