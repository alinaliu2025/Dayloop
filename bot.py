"""
bot.py — the phone layer. Telegram, so you answer from a notification with a
tap. No app to open.

Two kinds of interaction:
  - CHECK-INS  -> scheduled button messages. One tap logs state (and, if the
                  block is tied to a goal, lands in that goal's living plan).
                  No LLM.
  - THE THREE MOMENTS (the only times the LLM runs):
      /plan     (weekly) -> ask the generated reflection questions, then
                            re-derive every goal's plan from the log + answers.
      /today    (morning)-> pack each goal's current next-action into blocks.
      /evening  (nightly)-> the reveal: one line about the day -> write back
                            to each touched goal's living plan.

Env (kept in .env, gitignored): TELEGRAM_TOKEN, TELEGRAM_USER_ID, OPENAI_API_KEY.
Run:  python bot.py
"""

import os, json, datetime as dt
from zoneinfo import ZoneInfo
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (Application, CommandHandler, CallbackQueryHandler,
                          MessageHandler, ContextTypes, filters)
import planner as p

CFG = p.load_config()
TZ = ZoneInfo(CFG.get("timezone", "America/New_York"))
ALLOWED = os.environ.get("TELEGRAM_USER_ID")     # lock the bot to just you
EVENING_TIME = "22:45"                            # nightly reveal nudge

CHAT_FILE = p.DATA / "chat.json"
def _save_chat(cid): CHAT_FILE.write_text(json.dumps({"chat_id": cid}))
def _load_chat():
    return json.loads(CHAT_FILE.read_text())["chat_id"] if CHAT_FILE.exists() else None

def _ok(update: Update) -> bool:
    """Privacy gate: if TELEGRAM_USER_ID is set, only you can drive the bot."""
    if ALLOWED is None:
        return True
    u = update.effective_user
    return u is not None and str(u.id) == str(ALLOWED)

def _kb(rows):
    return InlineKeyboardMarkup([[InlineKeyboardButton(l, callback_data=c)] for l, c in rows])


# ----------------------------------------------------------- check-in nudges
def all_checkin_times(cfg):
    times = set()
    for tmpl in cfg["routines"]["templates"].values():
        for b in tmpl:
            if b.get("checkin"):
                times.add(b["start"])
    return sorted(times)

async def send_checkin(context: ContextTypes.DEFAULT_TYPE):
    """Fires at a fixed clock time; only sends if TODAY's template has a
    check-in block at that time."""
    hhmm = context.job.data
    cid = _load_chat()
    if cid is None:
        return
    _, blocks = p.pick_template(CFG)          # today's template
    block = next((b for b in blocks if b["start"] == hhmm and b.get("checkin")), None)
    if not block:
        return
    goal = block.get("goal", "none")
    rows = [("Done ✅", f"ci:1:{goal}"), ("Not yet", f"ci:0:{goal}")]
    await context.bot.send_message(cid, f"⏱ {block['name']}?", reply_markup=_kb(rows))

async def on_checkin_tap(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _ok(update):
        return
    q = update.callback_query
    await q.answer()
    _, ok, goal = q.data.split(":")
    goal = None if goal == "none" else goal
    p.log_event(kind=goal or "checkin", payload={"ok": ok == "1"}, goal=goal)
    await q.edit_message_text(f"logged ✓ ({goal or 'checkin'}: {'yes' if ok=='1' else 'no'})")


# --------------------------------------------- MOMENT 1: /plan (weekly reflect)
async def cmd_plan(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _ok(update):
        return
    await update.message.reply_text("thinking up this week's reflection…")
    questions = p.generate_questions(CFG)     # <-- LLM call
    if not questions:
        await _finish_plan(update, context, {})
        return
    lines, n = [], 0
    for gid, qs in questions.items():
        lines.append(f"*{gid}*")
        for qtext in qs:
            n += 1
            lines.append(f"{n}. {qtext}")
    context.chat_data["awaiting"] = "journal"
    await update.message.reply_text(
        "\U0001f4d3 Weekly check-in. Answer what you can in one free-form "
        "message (number them or just write) — I'll re-plan from it:\n\n"
        + "\n".join(lines), parse_mode="Markdown")

async def _finish_plan(update, context, journal_answers):
    await update.message.reply_text("re-deriving the week…")
    plans = p.plan_week(CFG, journal_answers)  # <-- LLM call
    out = []
    for g in p.goals(CFG):
        plan = (plans.get(g["id"]) or {}).get("plan") or {}
        na = plan.get("next_action")
        if na:
            out.append(f"*{g['id']}* ({g['type']})\n• {na}")
    await update.message.reply_text(
        "\n\n".join(out) or "nothing to plan.", parse_mode="Markdown")


# --------------------------------------------------- MOMENT 2: /today shape day
async def cmd_today(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _ok(update):
        return
    shaped, _ = p.shape_today(CFG)             # <-- LLM call
    out = []
    for s in shaped.get("schedule", []):
        out.append(f"*{s['block']}*\n" + "\n".join(f"• {t}" for t in s["tasks"]))
    if shaped.get("spillover"):
        out.append("_spillover:_ " + ", ".join(shaped["spillover"]))
    await update.message.reply_text("\n\n".join(out) or "nothing scheduled",
                                    parse_mode="Markdown")


# ------------------------------------------------ MOMENT 3: /evening reveal
async def cmd_evening(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _ok(update):
        return
    await _ask_evening(update.effective_chat.id, context)

async def _ask_evening(cid, context):
    context.chat_data["awaiting"] = "evenote"
    context.chat_data["drained"] = False
    await context.bot.send_message(
        cid, "\U0001f303 How was today? One line — what moved, what broke? "
             "(or tap below)",
        reply_markup=_kb([("Good day ✅", "eve:good"), ("Rough day", "eve:rough")]))

async def evening_nudge(context: ContextTypes.DEFAULT_TYPE):
    cid = _load_chat()
    if cid is not None:
        await _ask_evening(cid, context)

async def on_evening_tap(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _ok(update):
        return
    q = update.callback_query
    await q.answer()
    drained = q.data.endswith("rough")
    await q.edit_message_text("noted ✓")
    note = "rough day" if drained else "good day"
    await _run_reveal(update.effective_chat.id, context, note, drained)

async def _run_reveal(cid, context, note, drained):
    context.chat_data["awaiting"] = None
    out = p.reveal(CFG, daily_note=note, drained=drained)   # <-- LLM call
    await context.bot.send_message(
        cid, f"\U0001f4cb {out}\n\nTomorrow's plan is updated. /today in the morning.")


# ------------------------------------------------------------- free-text router
async def on_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _ok(update):
        return
    awaiting = context.chat_data.get("awaiting")
    if awaiting == "journal":
        context.chat_data["awaiting"] = None
        await _finish_plan(update, context, {"answers": update.message.text})
    elif awaiting == "evenote":
        drained = context.chat_data.get("drained", False)
        await _run_reveal(update.effective_chat.id, context, update.message.text, drained)


# ----------------------------------------------------------------- scheduling
def schedule_jobs(app):
    jq = app.job_queue
    for j in jq.jobs():
        j.schedule_removal()
    for hhmm in all_checkin_times(CFG):
        hh, mm = map(int, hhmm.split(":"))
        jq.run_daily(send_checkin, time=dt.time(hh, mm, tzinfo=TZ), data=hhmm, name=f"ci-{hhmm}")
    eh, em = map(int, EVENING_TIME.split(":"))
    jq.run_daily(evening_nudge, time=dt.time(eh, em, tzinfo=TZ), name="evening")

async def on_startup(app):
    p.seed_plans(CFG)                         # ensure living-plan store exists
    if _load_chat() is not None:
        schedule_jobs(app)

async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _ok(update):
        return
    _save_chat(update.effective_chat.id)
    p.seed_plans(CFG)
    schedule_jobs(context.application)
    await update.message.reply_text(
        f"✅ Wired up. Check-ins + nightly reveal scheduled ({CFG.get('timezone')}).\n"
        f"Your user id is `{update.effective_user.id}` — set TELEGRAM_USER_ID "
        f"to this to lock the bot to you.\n\n"
        f"/plan (weekly) · /today (morning) · /evening (nightly)",
        parse_mode="Markdown")


def main():
    app = (Application.builder()
           .token(os.environ["TELEGRAM_TOKEN"])
           .post_init(on_startup).build())
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("plan", cmd_plan))
    app.add_handler(CommandHandler("today", cmd_today))
    app.add_handler(CommandHandler("evening", cmd_evening))
    app.add_handler(CallbackQueryHandler(on_checkin_tap, pattern=r"^ci:"))
    app.add_handler(CallbackQueryHandler(on_evening_tap, pattern=r"^eve:"))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, on_text))
    app.run_polling()


if __name__ == "__main__":
    main()
