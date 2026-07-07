"""
planner.py — the brain. Zero Telegram in here so it can be tested alone.

The architecture (see ARCHITECTURE.md):
  - config.yaml is the STATIC SPINE (identity, rarely changes).
  - data/plans.json is the LIVING PLAN, written by the loop as you execute.
  - A goal's `type` (habit | skill | achievement | influence) routes what
    each of the three LLM moments does with it.

Design rules that keep it cheap:
  - STATE CAPTURE is free — check-in taps just append to a log, and taps
    tied to a goal also land in that goal's living-plan log.
  - REASONING is rare — the LLM runs only inside the three existing moments
    (/plan, /today, /evening). No fourth moment, no mid-day calls.
  - The plan is DISCOVERED by doing. We don't demand a full spec up front;
    the loop generates the missing knowledge from the execution trace.

Every LLM-calling function takes a `mock=` argument so the whole module is
testable offline with no API key.
"""

import os, json, re, datetime as dt, pathlib
import yaml
from dotenv import load_dotenv

# Load secrets from a local .env (gitignored) on import, so both planner.py
# and bot.py (which imports this module) see them. Won't overwrite real env.
load_dotenv()

ROOT = pathlib.Path(__file__).parent
DATA = ROOT / "data"
DATA.mkdir(exist_ok=True)
EVENTS_LOG = DATA / "events.jsonl"      # every check-in tap, append-only
PLANS_FILE = DATA / "plans.json"        # the living plan, keyed by goal id


# ------------------------------------------------------------------ config
def load_config(path=ROOT / "config.yaml"):
    with open(path) as f:
        return yaml.safe_load(f)


def goals(cfg):
    return cfg.get("goals", [])


def goal_by_id(cfg, gid):
    return next((g for g in goals(cfg) if g["id"] == gid), None)


# ============================================================ LIVING PLAN
# data/plans.json = { goal_id: {id, type, plan, log[], error_log[], updated} }
# `plan` is the generated, type-specific decomposition. It starts empty and
# is filled in by the loop, never typed into config by hand.

def load_plans():
    if PLANS_FILE.exists():
        return json.loads(PLANS_FILE.read_text())
    return {}


def save_plans(plans):
    PLANS_FILE.write_text(json.dumps(plans, indent=2))


def seed_plans(cfg):
    """Ensure every goal in config has a living-plan entry. Idempotent."""
    plans = load_plans()
    for g in goals(cfg):
        if g["id"] not in plans:
            plans[g["id"]] = {
                "id": g["id"],
                "type": g["type"],
                "plan": None,          # generated on the first /plan
                "log": [],             # per-goal execution trace
                "error_log": [],       # divergences (skill) / stuck notes
                "updated": None,
            }
    save_plans(plans)
    return plans


# ------------------------------------------------------- state capture (free)
def log_event(kind, payload=None, goal=None):
    """A check-in tap. No LLM. Appends to the global log, and — if the tap is
    tied to a goal — also to that goal's living-plan log. This is the free,
    frequent layer that fuels everything else."""
    rec = {"ts": dt.datetime.now().isoformat(timespec="seconds"),
           "kind": kind, "goal": goal, "payload": payload or {}}
    with open(EVENTS_LOG, "a") as f:
        f.write(json.dumps(rec) + "\n")
    if goal:
        plans = load_plans()
        entry = plans.get(goal)
        if entry is not None:
            entry["log"].append({"ts": rec["ts"], "kind": kind,
                                  "payload": rec["payload"]})
            save_plans(plans)
    return rec


def events_today():
    today = dt.date.today().isoformat()
    if not EVENTS_LOG.exists():
        return []
    out = []
    for line in EVENTS_LOG.read_text().splitlines():
        r = json.loads(line)
        if r["ts"].startswith(today):
            out.append(r)
    return out


# ------------------------------------------ routine template selection (no LLM)
def _weekday_name(d=None):
    return (d or dt.date.today()).strftime("%A").lower()


def pick_template(cfg, d=None, rain=False):
    """Which routine template runs on date `d`. `rain` swaps a volleyball day
    for its rain_day fallback. Pure lookup — no LLM."""
    templates = cfg["routines"]["templates"]
    name = cfg["routines"]["week"].get(_weekday_name(d), "weekend")
    if rain and name == "volleyball_day" and "rain_day" in templates:
        name = "rain_day"
    return name, [dict(b) for b in templates[name]]


def _minutes(b):
    fmt = lambda t: dt.datetime.strptime(t, "%H:%M")
    start = fmt(b["start"])
    end = fmt(b["end"]) if b["end"] != "00:00" else fmt("23:59")
    return int((end - start).total_seconds() // 60)


def instantiate_day(cfg, day_events=None, d=None, rain=False):
    """Bend today's template around real external events. Returns
    (template_name, timeline, focus_minutes). The timeline is plain
    arithmetic; only what goes INSIDE the focus blocks needs the LLM."""
    day_events = day_events or []
    name, blocks = pick_template(cfg, d, rain)

    for ev in day_events:
        blocks.append({"start": ev["start"], "end": ev["end"], "kind": "fixed",
                       "name": ev["name"], "external": True})
    blocks.sort(key=lambda b: b["start"])

    occupied = [(b["start"], b["end"]) for b in blocks if b.get("external")]
    cleaned = []
    for b in blocks:
        if b.get("external"):
            cleaned.append(b); continue
        clash = any(not (b["end"] <= s or b["start"] >= e) for s, e in occupied)
        if clash and b["kind"] in ("focus", "flex"):
            continue  # external event ate this slot
        cleaned.append(b)
    cleaned.sort(key=lambda b: b["start"])

    focus_min = sum(_minutes(b) for b in cleaned if b["kind"] == "focus")
    return name, cleaned, focus_min


# --------------------------------------------------------------- the LLM call
def call_llm(system, user, cfg, mock=None):
    """One thin wrapper around OpenAI Chat Completions. Auth = OPENAI_API_KEY.
    Asks for a JSON object so replies parse cleanly."""
    if mock is not None:                 # offline testing path
        return mock
    from openai import OpenAI
    client = OpenAI(api_key=os.environ["OPENAI_API_KEY"])
    resp = client.chat.completions.create(
        model=cfg["llm"]["model"],
        messages=[{"role": "system", "content": system},
                  {"role": "user", "content": user}],
        temperature=0.4,
        response_format={"type": "json_object"},
    )
    return resp.choices[0].message.content


def _parse_json(text):
    """Pull JSON out of a reply, tolerant of stray fences or prose."""
    text = (text or "").strip()
    text = re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL).strip()
    if text.startswith("```"):
        text = text.split("```")[1]
        if text.lstrip().startswith("json"):
            text = text.lstrip()[4:]
        text = text.strip()
    if not text.startswith("{"):
        m = re.search(r"\{.*\}", text, flags=re.DOTALL)
        if m:
            text = m.group(0)
    return json.loads(text)


def _recent(entry, n=12):
    """Compact recent history for a goal, for prompt context."""
    return {"log": entry.get("log", [])[-n:],
            "error_log": entry.get("error_log", [])[-n:],
            "plan": entry.get("plan")}


# ============================================ WEEKLY JOURNALING (part of /plan)
# Questions are generated from each goal's CURRENT state — pointed, not a
# fixed form. Answering them is the measurement (esp. for skill goals the
# model can't see). Depth scales with how blind the model is to the goal.

QUESTION_SYS = """You generate a short weekly reflection for ONE person, one
goal at a time. Use the goal's type, its current plan, and its recent log to
ask POINTED, niche questions — never generic ("how did it go?").
Rules:
- skill: you cannot see their work, so ask them to name concrete divergences
  ("where did X break?"), tied to the current bottleneck if one exists.
- achievement: ask status + where it stalled (knowledge gap? scope? tooling?).
- influence: ask which controllable levers actually moved this week.
- habit: usually no question (depth 0).
- Observational and forward-looking, not evaluative. If the recent log shows
  a rough/drained week, ask FEWER and gentler questions. Be kind.
Return ONLY JSON: {"questions": {"goal_id": ["q1", "q2"], ...}}"""

def generate_questions(cfg, mock=None):
    plans = seed_plans(cfg)
    depth = cfg.get("journaling", {}).get("depth", {})
    asks = []
    for g in goals(cfg):
        n = depth.get(g["type"], 0)
        if n <= 0:
            continue
        asks.append({"id": g["id"], "type": g["type"], "why": g.get("why"),
                     "domain": g.get("domain"), "end_state": g.get("end_state"),
                     "n_questions": n, **_recent(plans[g["id"]])})
    if not asks:
        return {}
    user = "Generate questions for these goals:\n" + json.dumps(asks, indent=2)
    return _parse_json(call_llm(QUESTION_SYS, user, cfg, mock=mock)).get("questions", {})


# ================================================= MOMENT 1: /plan re-derive
# For each non-habit goal, re-derive its living plan from the execution log +
# this week's journal answers, BY TYPE. Habits pass through untouched (proof
# the split is right: the always-fine type needs no new logic).

PLAN_SYS = """You re-derive the week's plan for ONE person, goal by goal, from
their execution log and their weekly journal answers. The plan is discovered
from evidence — do not invent generic steps.

Per type:
- skill: read the divergences/errors. Name THIS WEEK'S SINGLE bottleneck (the
  one thing limiting everything downstream). Set ONE deliberate-practice
  target aimed at it. Locate it on the given skill_tree. Add any new concrete
  divergences from the journal to new_errors.
- achievement: decompose end_state only where there is UNCERTAINTY; stay
  coarse where routine. Each leaf gets an escalation trigger that fires only
  if stuck (e.g. "if blocked 30 min -> ..."). Pick the current leaf. Apply a
  1.5-2x buffer to time guesses (planning-fallacy correction).
- influence: translate. Enumerate levers -> keep only what they CONTROL ->
  turn each into a concrete process action. Never prescribe diet/calories.
Be concrete: every next_action is one checkable line. Leave slack.
Return ONLY JSON:
{"goals": {"goal_id": {"plan": {...}, "next_action": "one line",
                        "new_errors": ["..."], "note": "one line"}, ...}}"""

def plan_week(cfg, journal_answers=None, mock=None):
    plans = seed_plans(cfg)
    active = [g for g in goals(cfg) if g["type"] != "habit"]
    ctx = []
    for g in active:
        ctx.append({"id": g["id"], "type": g["type"], "why": g.get("why"),
                    "domain": g.get("domain"), "end_state": g.get("end_state"),
                    "due": g.get("due"), "skill_tree": g.get("skill_tree"),
                    **_recent(plans[g["id"]])})
    user = ("GOALS + THEIR LOGS:\n" + json.dumps(ctx, indent=2) +
            "\n\nWEEKLY JOURNAL ANSWERS:\n" +
            json.dumps(journal_answers or {}, indent=2))
    out = _parse_json(call_llm(PLAN_SYS, user, cfg, mock=mock)).get("goals", {})

    now = dt.datetime.now().isoformat(timespec="seconds")
    for gid, upd in out.items():
        entry = plans.get(gid)
        if entry is None:
            continue
        if "plan" in upd:
            plan = dict(upd["plan"]) if isinstance(upd["plan"], dict) else {"summary": upd["plan"]}
            plan["next_action"] = upd.get("next_action")
            entry["plan"] = plan
        for e in upd.get("new_errors", []) or []:
            entry["error_log"].append({"ts": now, "divergence": e})
        entry["updated"] = now
    # habits: deterministic passthrough — their "plan" is just their schedule.
    for g in goals(cfg):
        if g["type"] == "habit":
            plans[g["id"]]["plan"] = {"next_action": g.get("schedule", "do it"),
                                      "cue": g.get("cue")}
            plans[g["id"]]["updated"] = now
    save_plans(plans)
    return plans


def next_actions(cfg):
    """Each active goal's current next-action, pulled from the living plan."""
    plans = load_plans()
    out = {}
    for g in goals(cfg):
        p = (plans.get(g["id"]) or {}).get("plan") or {}
        out[g["id"]] = p.get("next_action")
    return out


# ================================================= MOMENT 2: /today shape day
# Deterministic timeline + one LLM call to pack each goal's CURRENT next-action
# into today's focus blocks (hardest into the earliest prime window).

TODAY_SYS = """You arrange ONE person's day. You get today's timeline (focus
blocks are deep-work capacity; fixed/transition are immovable, some tagged
with a goal) and each active goal's current next-action. Put the right
next-action into each focus block — prefer the block already tagged to that
goal, hardest work into the earliest prime block. Respect the available focus
minutes; don't overfill. Anything that doesn't fit -> spillover.
Return ONLY JSON:
{"schedule": [{"block": "Deep work block A", "tasks": ["..."]}, ...],
 "spillover": ["..."]}"""

def shape_today(cfg, day_events=None, rain=False, mock=None):
    name, timeline, focus_min = instantiate_day(cfg, day_events, rain=rain)
    acts = next_actions(cfg)
    tl = "\n".join(
        f"{b['start']}-{b['end']} [{b['kind']}] {b['name']}"
        + (f"  (goal: {b['goal']})" if b.get("goal") else "")
        for b in timeline)
    user = (f"TEMPLATE: {name}\nFOCUS CAPACITY: {focus_min} min\n\n"
            f"TODAY TIMELINE:\n{tl}\n\n"
            f"GOAL NEXT-ACTIONS:\n{json.dumps(acts, indent=2)}")
    shaped = _parse_json(call_llm(TODAY_SYS, user, cfg, mock=mock))
    return shaped, timeline


# ============================================ MOMENT 3: /evening reveal (write-back)
# The reveal step: read what actually happened today (taps + one-line note)
# and update each touched goal's living plan, BY TYPE. This is where the free
# execution trace becomes tomorrow's smarter plan.

REVEAL_SYS = """You update ONE person's living plans from today's execution.
You get, per goal touched today: its type, current plan, today's taps, and an
optional one-line note ("what moved / what broke"). Update by type:
- skill: pull any concrete divergence out of the note into new_errors; if the
  bottleneck clearly held or cleared, say so in note.
- achievement: if the current leaf finished -> advance:true; if it got stuck
  -> fire its escalation (spawn 1-2 sub-steps in add_steps).
- habit: just record done/skipped.
If they reported being drained, note it so tomorrow lightens. Be brief, kind,
never evaluative.
Return ONLY JSON:
{"goals": {"goal_id": {"advance": bool, "add_steps": ["..."],
                        "new_errors": ["..."], "note": "one line"}, ...},
 "note": "one gentle line to the person"}"""

def reveal(cfg, daily_note=None, drained=False, mock=None):
    plans = load_plans()
    evs = events_today()
    touched = sorted({e["goal"] for e in evs if e.get("goal")})
    ctx = []
    for gid in touched:
        entry = plans.get(gid)
        if not entry:
            continue
        taps = [e for e in evs if e.get("goal") == gid]
        ctx.append({"id": gid, "type": entry["type"], "plan": entry.get("plan"),
                    "taps": [{"kind": t["kind"], "payload": t["payload"]} for t in taps]})
    user = (f"DRAINED: {drained}\nONE-LINE NOTE: {daily_note or '(none)'}\n\n"
            f"GOALS TOUCHED TODAY:\n{json.dumps(ctx, indent=2)}")
    out = _parse_json(call_llm(REVEAL_SYS, user, cfg, mock=mock))

    now = dt.datetime.now().isoformat(timespec="seconds")
    for gid, upd in out.get("goals", {}).items():
        entry = plans.get(gid)
        if not entry:
            continue
        plan = entry.get("plan") or {}
        for e in upd.get("new_errors", []) or []:
            entry["error_log"].append({"ts": now, "divergence": e})
        if upd.get("add_steps"):
            plan.setdefault("substeps", []).extend(upd["add_steps"])
        if upd.get("advance"):
            plan["advanced_at"] = now
        if upd.get("note"):
            plan["last_note"] = upd["note"]
        entry["plan"] = plan
        entry["updated"] = now
    save_plans(plans)
    return out.get("note", "logged. tomorrow's plan updated.")
