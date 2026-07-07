# dayloop — architecture

The whole system in one place. If you only read one doc, read this.

## The purpose, one sentence

dayloop runs your day, remembers what actually happened, and slowly gets
smarter about you — while doing almost no expensive "thinking."

## Two ideas everything hangs off

**Two speeds.** Capturing what happened is *free* — you tap a button and it
appends a line to a log. Thinking is *rare* — the LLM runs at just three
moments a day. Every design choice protects that split. Cheap memory, rare
thinking.

**Two kinds of knowledge.** A goal is two things wearing one label:

- **Static spine** — what you could truthfully write on day one and that
  rarely changes. Lives in `config.yaml`.
- **Living plan** — what only *doing* reveals: the current bottleneck, the
  decomposition, the practice target, the error log. Written by the loop into
  `data/plans.json`. Changes constantly even though the goal's identity doesn't.

Placement test for any fact: *could you have written it truthfully on Monday of
week one?* Yes → spine. No → living plan.

## Four goal types

The `type` tag on each goal decides what the loop does with it. Only one type
can be fully specified up front; the other three need knowledge you don't have
on day one, which the loop generates from execution.

| Type | You don't know… | Fails from | The loop's job |
|---|---|---|---|
| **habit** | *(nothing)* | friction, forgetting | schedule + remind; passes through untouched |
| **skill** | your gaps | plateauing in comfortable reps | find the current bottleneck from your error log |
| **achievement** | the depth | vagueness + planning fallacy | decompose lazily (only on failure), buffer estimates |
| **influence** | the levers | demoralization (outcome ≠ effort) | translate into controllable process goals |

Habit is the special case where the plan *is* known in advance — that's why
`config.yaml` was the right home for it and the wrong home for everything else.

## The daily loop — three moments around a log

The check-in taps fill a shared log for free. The three LLM moments read from
it and write back to it. Nothing else calls the model.

- **`/plan` (weekly).** First it generates *pointed* reflection questions from
  each goal's current state (not a fixed form). You answer in free text; it
  re-derives every goal's plan from the log + your answers, by type. Habits
  pass through.
- **`/today` (morning).** Deterministically builds today's timeline from the
  routine template, then one LLM call packs each goal's *current next-action*
  into the focus blocks (hardest into the earliest prime window).
- **`/evening` (nightly).** The reveal step: one line about the day → write
  back to each touched goal's living plan (skill: log the divergence;
  achievement: advance the leaf or fire an escalation; habit: tick).

The loop closes: `/plan` writes → `/today` surfaces → taps + `/evening` record
→ `/plan` re-derives. The plan is discovered by doing, not written before doing.

## Journaling is the input layer

For a skill the model can't see (your drawing), a button tap can't measure
anything. The reflection questions are how richer signal enters — and the key
is they're *generated from the current bottleneck*, so they're specific enough
to be answerable ("did the shoulders read in 3/4, or still collapse?" not "how
was practice?"). You journal freely; the model extracts the structured signal.

Two rules fall out:
- **Depth scales with how blind the model is.** Research (it can decompose)
  gets light status questions; art (it's blind) gets richer observation. See
  `journaling.depth` in `config.yaml`.
- **Near-free daily, rich weekly.** The heavy reflection rides on `/plan` — no
  fourth moment.

Guardrail: questions stay observational and forward-looking, never a nightly
scorecard, and ask *less* on a drained day.

## What measurement actually means

Not "how good am I" (unanswerable, and self-rating is noise). Instead: *which
concrete errors keep recurring* and *which rung you're on* — both observable.
Improvement = specific errors stop coming back and the work you can sustain
gets harder. This only works if you produce work and honestly log where it
broke; without that input a skill goal collapses back into a habit.

## Files

| File | Role |
|---|---|
| `config.yaml` | the static spine — goals (typed), routine templates, journaling depth, model |
| `planner.py` | the brain — living-plan store, per-goal log routing, the three type-aware moments, question generation. No Telegram. Every LLM call has a `mock=` for offline tests. |
| `bot.py` | the phone layer — Telegram taps, scheduling, the three commands, journaling flow |
| `data/plans.json` | the living plan, keyed by goal id (gitignored) |
| `data/events.jsonl` | append-only tap log (gitignored) |

## The discipline that keeps it cheap

No fourth moment, no mid-day call. Each of the three moments only changes what
it *reads and writes*, never how often it fires. Wanting a new call is the
"bigger form" instinct sneaking back — the three-moment budget is part of what
keeps dayloop cheap enough to actually run.

## Accountability test

After a real week, look at `data/plans.json`. If the art goal has named a
bottleneck you didn't type into config, and the REU goal has spawned a leaf
task you didn't pre-write — the architecture works. If they look identical to
what you'd have written on Monday, the log isn't feeding back and something in
the reveal/re-derive path is only pretending to.
