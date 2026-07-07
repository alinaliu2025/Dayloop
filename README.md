# dayloop

A personal day-loop bot. Talks to you on Telegram, runs the LLM only ~3× a
day. Built for one user (you). Full design in [`ARCHITECTURE.md`](ARCHITECTURE.md).

## The shape of it
Every goal is two things: a **static spine** (identity you can write on day
one → `config.yaml`) and a **living plan** (the bottleneck / decomposition /
error log that only *doing* reveals → `data/plans.json`, written by the loop).

A goal's `type` decides what the loop does with it:
- **habit** — fully known up front; scheduled and reminded, passes through.
- **skill** — the loop finds your current bottleneck from your error log.
- **achievement** — the loop decomposes it lazily, only when a step gets stuck.
- **influence** — the loop translates it into controllable process goals.

State capture (check-in taps) is **free** — just appends to a log, and taps
tied to a goal land in that goal's living plan. The LLM runs only at three
moments: `/plan` (weekly reflect + re-derive), `/today` (shape the day),
`/evening` (reveal what happened, write back).

## Setup (~15 min)

1. **Make a bot.** Open Telegram, message **@BotFather**, send `/newbot`,
   follow prompts, copy the token it gives you.

2. **Set up the project** (creates a virtualenv, installs deps, seeds `.env`):
   ```bash
   ./setup.sh
   # or by hand:
   #   python3 -m venv .venv && source .venv/bin/activate
   #   pip install -r requirements.txt
   #   cp .env.example .env
   ```

3. **Add your secrets.** Edit `.env` (it's gitignored — never commit it):
   ```
   TELEGRAM_TOKEN=123456:ABC...     # from BotFather
   TELEGRAM_USER_ID=                # fill after your first /start (locks bot to you)
   OPENAI_API_KEY=sk-...            # from the OpenAI account you were granted
   ```
   The model lives in `config.yaml` (`llm.model`, default `gpt-4o-mini`).

4. **Run the dashboard:**
   ```bash
   source .venv/bin/activate
   python app.py
   ```
   Open **http://localhost:8000** in your browser. To use it from your phone on
   the same wifi, find your Mac's IP (System Settings → Network) and open
   `http://<your-mac-ip>:8000` there.

> **Secrets never touch git.** `.env` and `data/` are in `.gitignore`; only
> `.env.example` (the blank template) is committed. If you ever paste a real
> key somewhere tracked, rotate it.

## Install it on your phone (PWA)
The dashboard is a Progressive Web App — it installs to your home screen with
an icon and runs full-screen, no App Store.

- **iPhone:** open the dashboard in **Safari**, tap Share → **Add to Home
  Screen**. Launch it from the new icon and it opens like an app.
- Full offline caching and (later) push notifications need **https**, which
  arrives when the app is hosted (Phase 3). Over a plain-http home-wifi address
  it still installs and runs — it just won't cache offline yet.

## Two faces, one brain
`planner.py` is the brain. It has two interchangeable front ends:
- **`app.py`** — the web dashboard (current). Buttons, your schedule, and your
  goals laid out. This is the one to use.
- **`bot.py`** — the original Telegram bot (kept for reference / phone push).

## Daily use (dashboard)
- **Shape today** → packs each goal's current next-action into today's focus blocks.
- **Check-in buttons** on each block → free taps that feed that goal's living plan.
- **Weekly check-in** → answers a few pointed, auto-generated reflection
  questions, then re-derives every goal's plan.
- **Evening reveal** → one line about the day, written back into each goal's plan.

Peek at whether it's actually learning: `python inspect_plan.py` (see
[`ARCHITECTURE.md`](ARCHITECTURE.md), the accountability test).

## Making it always-on (the "real phone experience")
The bot only nudges you while its process is running. Three phases:

1. **Today — local.** Run `python bot.py` on your laptop, `/start` in Telegram,
   watch check-ins fire. Validates everything. (Only runs while the laptop's open.)
2. **Lock it to you.** `/start` prints your numeric Telegram id. Set
   `TELEGRAM_USER_ID` to it so nobody else who finds the bot can drive it.
3. **Move it to an always-on host** so nudges fire 24/7:
   - **Cheapest reliable:** a small VPS (~$5/mo, Hetzner/DigitalOcean) or a
     Raspberry Pi you already own. Use the included `dayloop.service` (systemd)
     — it auto-restarts on crash/reboot, and `on_startup` re-arms your check-in
     schedule without you re-sending `/start`.
   - **No server admin:** a managed platform (Railway/Render/Fly). Works, but
     mount a persistent volume for `data/` or your logs reset on redeploy.
   - **Not OSC.** The supercomputer is batch HPC for SLURM jobs — a personal
     always-on daemon doesn't belong on login nodes and may breach usage policy.
     Keep your research compute and this hobby bot separate.

Polling (not webhooks) means no public URL or open ports needed anywhere.

## Where to grow it (later, not now)
- Calibration score: log your *guessed* vs *actual* task durations, learn your
  personal multiplier → this is the game (beat the model's estimate of you).
- Auto-pull fixed events from Google Calendar instead of typing them.
- The "tired" read: a single morning energy tap (1–5) the planner reads before
  shaping the day.

Start with just the loop above. Add one of these only once the base habit sticks.
