#!/usr/bin/env python3
"""
cleanup.py - map a freely played MIDI take in the OPEN REAPER project and fix its accidents
(ghost presses, slips, double strikes, split chords) via the Reaper MCP server.

  dry run (default)        piece map + every finding, change nothing
  --apply                  apply the auto findings (+ --include, - --exclude, --raise)
  --restore BACKUP.json    put the take back exactly as it was

Output: human-readable lines plus a final line "RESULT {json}".
"""
import argparse, bisect, json, os, sys, time
from mcp_client import MCPClient
from piece import parse, piece_map, find_fixes, apply_fixes, NAMES

BACKUP_DIR = os.path.expanduser("~/.cache/reaper-performance-cleanup")
KINDS = ("ghost", "slip", "double", "split", "wrong")

ap = argparse.ArgumentParser()
ap.add_argument("--item", type=int, default=0, help="project-wide media item index")
mode = ap.add_mutually_exclusive_group()
mode.add_argument("--apply", action="store_true", help="apply the selected findings (default: dry run)")
mode.add_argument("--restore", metavar="BACKUP", help="restore the take from a backup file")
ap.add_argument("--include", default="", help="also apply these review findings, e.g. N35,N66")
ap.add_argument("--exclude", default="", help="skip findings by id or kind, e.g. N8,split")
ap.add_argument("--raise", dest="raise_", default="", help="ghosts to make audible instead of deleting, e.g. N4,N48")
ap.add_argument("--ghost-vel", type=int, default=8, help="velocity at or below which a press is inaudible")
ap.add_argument("--free-gap", type=float, default=0.8,
                help="median onset gap (s) from which a passage counts as free/rubato (no pulse)")
a = ap.parse_args()


def ids(s):
    return {x.strip() for x in s.split(",") if x.strip()}


def result(**kw):
    print("RESULT " + json.dumps(kw))


def public(f):
    return {k: v for k, v in f.items() if k not in ("note", "into")}


def to_ppq(t, sec, ppq):
    """Seconds -> ticks by interpolating the take's own (sec, ppq) pairs (exact at an event's own
    time and between tempo changes)."""
    i = min(max(bisect.bisect_left(sec, t), 1), len(sec) - 1)
    if sec[i] == t: return ppq[i]
    j = i - 1
    while j > 0 and sec[i] - sec[j] < 1e-6: j -= 1
    while i < len(sec) - 1 and sec[i] - sec[j] < 1e-6: i += 1
    return round(ppq[j] + (t - sec[j]) * (ppq[i] - ppq[j]) / ((sec[i] - sec[j]) or 1))


m = MCPClient()
try:
    if a.restore:
        b = json.load(open(a.restore))
        m.call("midi_set", item=b["item"], unit="ppq", events=[[e[0], e[1], e[2]] for e in b["events"]])
        after = m.call("midi_get", item=b["item"], notes=False, ccs=False, events=True)["events"]
        same = [e[:3] for e in after] == [e[:3] for e in b["events"]]
        print(f"restored {len(after)} events from {a.restore}; identical={same}")
        result(mode="restore", ok=same, events=len(after))
        sys.exit(0 if same else 1)

    take = m.call("midi_get", item=a.item, notes=False, ccs=False, events=True)
    events = take["events"]                  # [ppq, flags, hex, sec, qn]
    sec = [e[3] for e in events]
    notes, pedal = parse(events, sec)
    pm = piece_map(notes, ghost_vel=a.ghost_vel, free_ioi=a.free_gap)

    # ---------- piece map ----------
    k = pm["key"]
    print(f"key: {k['name']} (fit {k['confidence']}); in key: {' '.join(NAMES[p] for p in k['scale'])}")
    if pm["pulse_sec"]:
        p = pm["pulse_sec"]
        print(f"main pulse: one onset every {p:.3f} s -> if eighths: quarter = {60 / p / 2:.0f} BPM "
              f"(if sixteenths: {60 / p / 4:.0f}, if quarters: {60 / p:.0f})")
    print("sections:")
    for s in pm["sections"]:
        tempo = f", pulse {s['pulse_sec']:.3f} s (quarter {60 / s['pulse_sec'] / 2:.0f} BPM as eighths)" if s["pulse_sec"] else ""
        print(f"  {s['start']:7.2f} - {s['end']:7.2f} s  {s['kind']:6}  {s['onsets']:4} onsets, "
              f"median gap {s['median_gap_sec']} s{tempo}")

    # ---------- findings ----------
    inc, exc, rai = ids(a.include), ids(a.exclude), ids(a.raise_)
    bad = {x for x in exc if not x.startswith("N") and x not in KINDS}
    if bad:
        result(mode="error", error=f"unknown kind(s) {sorted(bad)} in --exclude; kinds are {','.join(KINDS)}"); sys.exit(2)
    fixes = find_fixes(notes, pm, ghost_vel=a.ghost_vel)
    chosen = [f for f in fixes if (f["auto"] or f["id"] in inc or f["id"] in rai)
              and f["id"] not in exc and f["kind"] not in exc]
    print(f"{len(fixes)} findings, {len(chosen)} selected ([x]):")
    for f in fixes:
        if f["kind"] == "ghost" and f["id"] in rai: what = f"velocity -> {f['raise_to']}"
        else: what = {"delete": "delete", "merge": "merge", "transpose": f"-> {f.get('to')}",
                      "move": f"move {f.get('shift_ms', 0):+d} ms"}[f["action"]]
        hint = f"  [--raise {f['id']}: velocity {f['raise_to']}]" if f.get("raise_to") and f["id"] not in rai else ""
        print(f"  [{'x' if f in chosen else ' '}] {f['id']:4} {f['time']:8.3f}s {f['pitch']:4} vel {f['vel']:3} "
              f"{f['dur_ms']:5} ms  {f['kind']:6} {what:14} {'auto' if f['auto'] else 'REVIEW'}  - {f['why']}{hint}")
    report = {"item": a.item, "events": len(events), "key": k["name"], "pulse_sec": pm["pulse_sec"],
              "sections": pm["sections"], "findings": [public(f) for f in fixes],
              "selected": [f["id"] for f in chosen]}
    if not a.apply:
        result(mode="dry-run", **report); sys.exit(0)

    # ---------- apply ----------
    os.makedirs(BACKUP_DIR, exist_ok=True)
    backup = os.path.join(BACKUP_DIR, time.strftime("%Y%m%d-%H%M%S") + f"-item{a.item}.json")
    json.dump({"item": a.item, "events": events, "applied": [public(f) for f in chosen]}, open(backup, "w"))
    ppq = [e[0] for e in events]
    out = [[to_ppq(t, sec, ppq), fl, h] for t, fl, h in apply_fixes(events, sec, chosen, raise_ids=rai)]
    m.call("midi_set", item=a.item, unit="ppq", events=out)

    # ---------- verify ----------
    after = m.call("midi_get", item=a.item, notes=False, ccs=False, events=True)["events"]
    same = sorted((e[0], e[1], e[2]) for e in out) == sorted((e[0], e[1], e[2]) for e in after)
    n_after = len(parse(after, [e[3] for e in after])[0])
    ok = same and len(after) == len(out)
    report.update(applied=[f["id"] for f in chosen], backup=backup, events_after=len(after),
                  notes_before=len(notes), notes_after=n_after, events_as_planned=same)
    print(f"verify: {len(after)} events (was {len(events)}), notes {len(notes)} -> {n_after}, as planned={same}")
    result(mode="apply", ok=ok, **report)
    sys.exit(0 if ok else 1)
finally:
    m.close()
