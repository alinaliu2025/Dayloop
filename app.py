"""
app.py — the dashboard server. A small Flask app over the planner.py brain.

Faces:
  - the 4-tab web app in static/ (Home, Calendar, Goals, Journal)
  - bot.py is the old Telegram face (kept for reference)

Reads are FREE and instant (no LLM). Only the three action endpoints spend an
LLM call: /api/plan, /api/today, /api/evening.

New data stores (all in data/, gitignored):
  goals.json      the goal tree — seeded from config, then app-owned
  events.json     calendar events (one-time + weekly-repeating)
  overrides.json  per-day schedule edits ({date: [blocks]})
  journal.json    all written journal entries + weekly answers

Run:  python app.py   ->  http://localhost:8000
"""

import datetime as dt
import json
import uuid
from flask import Flask, request, jsonify, send_from_directory
import planner as p

CFG = p.load_config()
app = Flask(__name__, static_folder="static", static_url_path="")

GOALS_F   = p.DATA / "goals.json"
EVENTS_F  = p.DATA / "events.json"
OVER_F    = p.DATA / "overrides.json"
JOURNAL_F = p.DATA / "journal.json"


# ------------------------------------------------------------ tiny json store
def _load(path, default):
    return json.loads(path.read_text()) if path.exists() else default

def _save(path, obj):
    path.write_text(json.dumps(obj, indent=2))

def _uid():
    return uuid.uuid4().hex[:8]


# ------------------------------------------------------------ goal tree store
def seed_goals():
    """Seed the app-owned goal tree from config on first run, then leave it be."""
    if GOALS_F.exists():
        return _load(GOALS_F, [])
    out = []
    for i, g in enumerate(p.goals(CFG)):
        out.append({
            "id": g["id"], "type": g["type"], "why": g.get("why", ""),
            "priority": 2,                              # 1 high · 2 med · 3 low
            "levers": g.get("skill_tree") or [],
            "subgoals": [],
            "domain": g.get("domain"), "end_state": g.get("end_state"),
            "due": g.get("due"),
        })
    _save(GOALS_F, out)
    return out


# ------------------------------------------------------------ day / calendar
def _event_on(ev, d):
    if ev.get("date"):
        return ev["date"] == d.isoformat()
    rec = ev.get("recurrence")
    if rec and rec.get("freq") == "weekly":
        days = [x[:3].lower() for x in rec.get("days", [])]
        return d.strftime("%a").lower() in days
    return False

def merged_day(date_str):
    """Blocks for a given date: the per-day override if edited, else the routine
    template, with calendar events merged in. Read-only assembly, no LLM."""
    d = dt.date.fromisoformat(date_str)
    over = _load(OVER_F, {})
    if date_str in over:
        blocks = [dict(b) for b in over[date_str]]
    else:
        _, tmpl = p.pick_template(CFG, d)
        blocks = []
        for i, b in enumerate(tmpl):
            b = dict(b); b.setdefault("id", f"t{i}")
            blocks.append(b)
    for ev in _load(EVENTS_F, []):
        if _event_on(ev, d):
            blocks.append({"id": ev["id"], "name": ev["title"],
                           "start": ev.get("start", "09:00"), "end": ev.get("end", "10:00"),
                           "kind": "event", "goal": ev.get("goal"), "event": True})
    blocks.sort(key=lambda b: b.get("start", "00:00"))
    return d, blocks


# ------------------------------------------------------------ progress / buddy
def compute_progress():
    """Streak = consecutive days (up to today) with at least one logged tap.
    Stage blends consistency (streak) and real progress (goal advances)."""
    days = set()
    if p.EVENTS_LOG.exists():
        for line in p.EVENTS_LOG.read_text().splitlines():
            try:
                days.add(json.loads(line)["ts"][:10])
            except Exception:
                pass
    streak = 0
    d = dt.date.today()
    while d.isoformat() in days:
        streak += 1
        d -= dt.timedelta(days=1)
    plans = p.load_plans()
    advances = sum(1 for e in plans.values() if (e.get("plan") or {}).get("advanced_at"))
    stage = min(5, streak // 3 + advances)     # both combined
    return {"streak": streak, "stage": stage, "advances": advances,
            "logged_today": dt.date.today().isoformat() in days}


# ============================================================= static / shell
@app.get("/")
def index():
    return send_from_directory("static", "index.html")

@app.get("/manifest.webmanifest")
def manifest():
    return send_from_directory("static", "manifest.webmanifest",
                               mimetype="application/manifest+json")

@app.get("/sw.js")
def service_worker():
    return send_from_directory("static", "sw.js", mimetype="text/javascript")


# ============================================================= reads (no LLM)
@app.get("/api/state")
def state():
    p.seed_plans(CFG)
    seed_goals()
    prog = compute_progress()
    plans = p.load_plans()
    goals_out = []
    for g in seed_goals():
        e = plans.get(g["id"], {})
        plan = e.get("plan") or {}
        goals_out.append({**g, "next_action": plan.get("next_action"),
                          "focus": plan.get("bottleneck") or plan.get("current_leaf")
                                    or plan.get("weak") or plan.get("summary"),
                          "errors": len(e.get("error_log", [])),
                          "logs": len(e.get("log", []))})
    return jsonify({"today": dt.date.today().isoformat(), "progress": prog,
                    "goals": goals_out})

@app.get("/api/day")
def day():
    date_str = request.args.get("date", dt.date.today().isoformat())
    d, blocks = merged_day(date_str)
    return jsonify({"date": date_str, "weekday": d.strftime("%A"), "blocks": blocks})

@app.post("/api/day")
def save_day():
    d = request.get_json(force=True)
    over = _load(OVER_F, {})
    over[d["date"]] = d["blocks"]
    _save(OVER_F, over)
    return jsonify({"ok": True})


# ---- calendar events ----------------------------------------------------
@app.get("/api/events")
def get_events():
    return jsonify(_load(EVENTS_F, []))

@app.post("/api/events")
def add_event():
    d = request.get_json(force=True)
    events = _load(EVENTS_F, [])
    ev = {"id": _uid(), "title": d.get("title", "Untitled"),
          "start": d.get("start", "09:00"), "end": d.get("end", "10:00"),
          "goal": d.get("goal"), "note": d.get("note", "")}
    if d.get("recurrence"):
        ev["recurrence"] = d["recurrence"]        # {"freq":"weekly","days":["mon",...]}
    else:
        ev["date"] = d.get("date")                # one-time
    events.append(ev)
    _save(EVENTS_F, events)
    return jsonify(ev)

@app.post("/api/events/delete")
def del_event():
    d = request.get_json(force=True)
    _save(EVENTS_F, [e for e in _load(EVENTS_F, []) if e["id"] != d.get("id")])
    return jsonify({"ok": True})


# ---- goal tree ----------------------------------------------------------
@app.get("/api/goals")
def api_goals():
    return jsonify(seed_goals())

@app.post("/api/goals")
def save_goals():
    _save(GOALS_F, request.get_json(force=True))    # whole-tree replace
    return jsonify({"ok": True})


# ---- journal ------------------------------------------------------------
@app.get("/api/journal")
def get_journal():
    return jsonify(sorted(_load(JOURNAL_F, []), key=lambda x: x["ts"], reverse=True))

@app.post("/api/journal")
def add_journal():
    d = request.get_json(force=True)
    entries = _load(JOURNAL_F, [])
    entries.append({"id": _uid(), "ts": dt.datetime.now().isoformat(timespec="seconds"),
                    "date": dt.date.today().isoformat(), "kind": d.get("kind", "daily"),
                    "text": d.get("text", ""), "answers": d.get("answers")})
    _save(JOURNAL_F, entries)
    return jsonify({"ok": True})


# ---- free tap -----------------------------------------------------------
@app.post("/api/checkin")
def checkin():
    d = request.get_json(force=True)
    goal = d.get("goal") or None
    p.log_event(kind=goal or "checkin", payload={"ok": bool(d.get("ok"))}, goal=goal)
    return jsonify(compute_progress())


# ============================================================= the LLM moments
@app.get("/api/questions")
def questions():
    return jsonify(p.generate_questions(CFG))

@app.post("/api/plan")
def plan():
    d = request.get_json(force=True)
    answers = d.get("answers", "")
    if answers:
        entries = _load(JOURNAL_F, [])
        entries.append({"id": _uid(), "ts": dt.datetime.now().isoformat(timespec="seconds"),
                        "date": dt.date.today().isoformat(), "kind": "weekly", "text": answers})
        _save(JOURNAL_F, entries)
    p.plan_week(CFG, {"answers": answers})
    return jsonify(p.next_actions(CFG))

@app.post("/api/today")
def today():
    shaped, _ = p.shape_today(CFG)
    return jsonify(shaped)

@app.post("/api/evening")
def evening():
    d = request.get_json(force=True)
    note = p.reveal(CFG, daily_note=d.get("note"), drained=bool(d.get("drained")))
    if d.get("note"):
        entries = _load(JOURNAL_F, [])
        entries.append({"id": _uid(), "ts": dt.datetime.now().isoformat(timespec="seconds"),
                        "date": dt.date.today().isoformat(), "kind": "daily", "text": d["note"]})
        _save(JOURNAL_F, entries)
    return jsonify({"note": note})


if __name__ == "__main__":
    p.seed_plans(CFG)
    seed_goals()
    print("dayloop → http://localhost:8000  (Ctrl-C to stop)")
    app.run(host="0.0.0.0", port=8000, debug=False)
