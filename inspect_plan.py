#!/usr/bin/env python3
"""
inspect_plan.py — peek at the living plan. This is the accountability test.

The whole architecture only works if the loop writes things you did NOT type
into config: a bottleneck it found, a leaf task it spawned. Run this after a
few days of real use. If the plans look identical to your config, the log
isn't feeding back and something is only pretending to.

Usage:
  python inspect_plan.py            # one-line summary of every goal
  python inspect_plan.py art        # full detail for one goal

(named inspect_plan, not inspect, so it doesn't shadow Python's stdlib.)
"""
import sys, json
import planner as p


def summary(gid, entry):
    plan = entry.get("plan") or {}
    na = plan.get("next_action") or "(not planned yet)"
    print(f"  {gid:<15} [{entry.get('type'):<11}] "
          f"logs:{len(entry.get('log', [])):<3} errors:{len(entry.get('error_log', [])):<3} "
          f"→ {na}")


def detail(gid, entry):
    plan = entry.get("plan") or {}
    print(f"\n=== {gid}   [{entry.get('type')}] ===")
    print("  next action :", plan.get("next_action") or "(not planned yet)")
    print("  updated     :", entry.get("updated") or "never")
    if plan:
        print("  plan        :", json.dumps(plan, indent=2).replace("\n", "\n                "))
    el = entry.get("error_log", [])
    if el:
        print("  error log (what keeps breaking):")
        for e in el[-12:]:
            print(f"    - {e.get('divergence')}   ({e.get('ts')})")
    lg = entry.get("log", [])
    if lg:
        print("  recent taps:")
        for e in lg[-12:]:
            print(f"    - {e.get('kind')}: {e.get('payload')}   ({e.get('ts')})")


def main():
    cfg = p.load_config()
    plans = p.load_plans()
    if not plans:
        print("No living plans yet. Start the bot and send /start (or /plan) to seed them.")
        return

    target = sys.argv[1] if len(sys.argv) > 1 else None
    if target:
        entry = plans.get(target)
        if not entry:
            print(f"no goal '{target}'. known goals: {', '.join(plans)}")
            return
        detail(target, entry)
    else:
        print("living plan — one line per goal:\n")
        for g in p.goals(cfg):
            entry = plans.get(g["id"])
            if entry:
                summary(g["id"], entry)
        print("\nrun  python inspect_plan.py <goal_id>  for full detail.")


if __name__ == "__main__":
    main()
