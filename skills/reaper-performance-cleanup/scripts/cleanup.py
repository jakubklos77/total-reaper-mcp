#!/usr/bin/env python3
"""
cleanup.py - clean up a freely played MIDI take in the OPEN REAPER project via the Reaper MCP
server: wrong notes / slips, thinking pauses, small timing errors.

  dry run (default)        report everything found, change nothing
  --apply notes,pauses     before tempo sync: fix notes, cut thinking pauses
  --apply timing           after tempo sync: pull onsets towards the synced grid
  --restore BACKUP.json    put the take back exactly as it was

Output: human-readable lines plus a final line "RESULT {json}".
"""
import argparse, json, os, sys, time
from mcp_client import MCPClient
from cleanup_analysis import (parse_notes, find_note_fixes, apply_note_fixes, find_pauses, pause_cuts,
                              cut_warp, timing_plan, anchor_warp, onset_deviation)

BACKUP_DIR = os.path.expanduser("~/.cache/reaper-performance-cleanup")
STEPS = ("notes", "pauses", "timing")

ap = argparse.ArgumentParser()
ap.add_argument("--item", type=int, default=0, help="project-wide media item index")
mode = ap.add_mutually_exclusive_group()
mode.add_argument("--apply", metavar="STEPS", help="comma list of notes,pauses,timing (default: dry run)")
mode.add_argument("--restore", metavar="BACKUP", help="restore the take from a backup file")
ap.add_argument("--include", default="", help="also apply these review findings, e.g. N1,N4")
ap.add_argument("--exclude", default="", help="skip these findings, e.g. N3")
ap.add_argument("--ghost-vel", type=int, default=8, help="velocity at or below which a note counts as a ghost")
ap.add_argument("--slots-per-beat", type=int, default=2, help="played subdivision per beat (2=eighths, 3=triplets, 4=16ths)")
ap.add_argument("--min-pause", type=float, default=1.5, help="shortest pause in seconds")
ap.add_argument("--pause-beats", type=float, default=3.0, help="shortest pause in local beats")
ap.add_argument("--keep-beats", type=float, default=1.0, help="beats left of each pause after the cut")
ap.add_argument("--keep", default="", help="per pause, e.g. P1=2,P3=0.5 (beats)")
ap.add_argument("--grid", type=float, help="timing grid in quarter notes (default 1/slots-per-beat)")
ap.add_argument("--strength", type=float, default=0.5, help="timing: 0..1 of the distance to the grid")
ap.add_argument("--window", type=float, default=0.35, help="timing: only onsets within this fraction of a grid step")
a = ap.parse_args()


def ids(s):
    return {x.strip().upper() for x in s.split(",") if x.strip()}


def result(**kw):
    print("RESULT " + json.dumps(kw))


def public(f):
    return {k: v for k, v in f.items() if k not in ("note", "into") and not k.startswith("_")}


m = MCPClient()
try:
    if a.restore:
        b = json.load(open(a.restore))
        m.call("midi_set", item=b["item"], unit="ppq", events=[[e[0], e[1], e[2]] for e in b["events"]])
        m.call("item_set", item=b["item"], length=b["item_length"])
        after = m.call("midi_get", item=b["item"], notes=False, ccs=False, events=True)["events"]
        same = [e[:3] for e in after] == [e[:3] for e in b["events"]]
        print(f"restored {len(after)} events from {a.restore}; identical={same}")
        result(mode="restore", ok=same, events=len(after))
        sys.exit(0 if same else 1)

    steps = ids(a.apply.lower()) if a.apply else set()
    steps = {s.lower() for s in steps}
    if steps - set(STEPS):
        result(mode="error", error=f"unknown step(s) {sorted(steps - set(STEPS))}; use {','.join(STEPS)}"); sys.exit(2)
    if {"pauses", "timing"} <= steps:
        result(mode="error", error="pauses (before tempo sync) and timing (after it) can't run together"); sys.exit(2)

    take = m.call("midi_get", item=a.item, notes=False, ccs=False, events=True)
    tm = m.call("tempo_map_get")
    synced = len(tm["markers"]) > 1
    events = take["events"]                  # [ppq, flags, hex, sec, qn]
    item_len = take["item_length"]
    item_pos = take["item_position"]
    inc, exc = ids(a.include), ids(a.exclude)
    keep = {k.strip().upper(): float(v) for k, v in (x.split("=") for x in a.keep.split(",") if "=" in x)}
    grid = a.grid or 1.0 / a.slots_per_beat
    report = {"item": a.item, "events": len(events), "tempo_synced": synced}

    # ---------- notes ----------
    fixes = find_note_fixes(parse_notes(events, [e[3] for e in events]), ghost_vel=a.ghost_vel)
    chosen = [f for f in fixes if (f["auto"] or f["id"] in inc) and f["id"] not in exc]
    report["note_findings"] = [public(f) for f in fixes]
    report["note_fixes_selected"] = [f["id"] for f in chosen]
    print(f"{len(fixes)} note findings, {len(chosen)} selected:")
    for f in fixes:
        what = {"delete": "delete", "velocity": f"velocity -> {f.get('new_vel')}",
                "transpose": f"-> {f.get('to')}", "merge": "merge"}[f["action"]]
        mark = "x" if f in chosen else " "
        print(f"  [{mark}] {f['id']:4} {f['time']:8.3f}s {f['pitch']:4} vel {f['vel']:3} {f['dur_ms']:5} ms  "
              f"{f['kind']:6} {what:16} {'auto' if f['auto'] else 'review'}  - {f['why']}")
    work = apply_note_fixes(events, chosen) if "notes" in steps else [list(e) for e in events]

    # ---------- pauses (before sync, on the note-fixed take) ----------
    pauses = find_pauses(parse_notes(work, [e[3] for e in work]), a.slots_per_beat, a.min_pause,
                         a.pause_beats, a.keep_beats, keep)
    pauses = [p for p in pauses if p["id"] not in exc]
    report["pauses"] = [public(p) for p in pauses]
    report["pause_removed_sec"] = round(sum(p["removed_sec"] for p in pauses), 3)
    print(f"{len(pauses)} thinking pauses" + (" (remove BEFORE tempo sync)" if pauses and synced else ""))
    for p in pauses:
        print(f"  {p['id']:3} after {p['time']:8.3f}s: {p['gap_sec']:.2f}s = {p['gap_beats']} beats "
              f"-> keep {p['keep_beats']:g} beat(s) = {p['new_gap_sec']:.2f}s (cut {p['removed_sec']:.2f}s)")

    # ---------- timing (after sync) ----------
    moves = []
    if synced:
        nq = parse_notes(work, [e[4] for e in work])
        moves, anchors = timing_plan(nq, grid, a.strength, a.window)
        report["timing_before"] = onset_deviation(nq, grid)
        report["timing_moves"] = len(moves)
        report["timing_max_shift_qn"] = max((abs(x["shift_qn"]) for x in moves), default=0)
        print(f"timing: grid {grid:g} qn, onsets off-grid median {report['timing_before']['median_dev_qn']} qn; "
              f"{len(moves)} onsets would move (strength {a.strength}, max {report['timing_max_shift_qn']} qn)")
    else:
        print("timing: needs the tempo-synced grid - run reaper-tempo-sync first")

    if not steps:
        result(mode="dry-run", **report); sys.exit(0)

    # ---------- apply ----------
    if "pauses" in steps and synced:
        result(mode="error", error="the project has a tempo map: remove pauses before tempo sync "
                                   "(restore the tempo-sync backup, clean up, then sync again)"); sys.exit(2)
    if "timing" in steps and not synced:
        result(mode="error", error="timing needs the tempo-synced grid - run reaper-tempo-sync first"); sys.exit(2)

    os.makedirs(BACKUP_DIR, exist_ok=True)
    backup = os.path.join(BACKUP_DIR, time.strftime("%Y%m%d-%H%M%S") + f"-item{a.item}.json")
    json.dump({"item": a.item, "item_length": item_len, "events": events, "steps": sorted(steps)}, open(backup, "w"))

    new_len = item_len
    if "pauses" in steps and pauses:
        w = cut_warp(pause_cuts(pauses))
        out = [[w(e[3]), e[1], e[2]] for e in work]
        new_len = w(item_pos + item_len) - item_pos
        unit = "seconds"
    elif "timing" in steps and moves:
        w = anchor_warp(anchors)
        out = [[w(e[4]), e[1], e[2]] for e in work]
        unit = "qn"
    else:
        out = [[e[0], e[1], e[2]] for e in work]
        unit = "ppq"
    m.call("midi_set", item=a.item, unit=unit, events=out)
    if abs(new_len - item_len) > 1e-6:
        m.call("item_set", item=a.item, length=new_len)

    # ---------- verify ----------
    after = m.call("midi_get", item=a.item, notes=False, ccs=False, events=True)["events"]
    col = {"seconds": 3, "qn": 4, "ppq": 0}[unit]
    tol = {"seconds": 0.002, "qn": 0.005, "ppq": 0.5}[unit]
    same_payload = sorted((e[1], e[2]) for e in out) == sorted((e[1], e[2]) for e in after)
    worst = max((abs(x[0] - y[col]) for x, y in zip(sorted(out, key=lambda e: (e[0], e[2])),
                                                   sorted(after, key=lambda e: (e[col], e[2])))), default=0)
    ok = same_payload and len(after) == len(out) and worst < tol
    report.update(applied=sorted(steps), backup=backup, events_after=len(after), events_same_payload=same_payload,
                  max_position_error=round(worst, 6), unit=unit, item_length=round(new_len, 3))
    if "timing" in steps and moves:
        report["timing_after"] = onset_deviation(parse_notes(after, [e[4] for e in after]), grid)
    print(f"verify: {len(after)} events (was {len(events)}), payload as planned={same_payload}, "
          f"max position error {worst:.6f} {unit}")
    result(mode="apply", ok=ok, **report)
    sys.exit(0 if ok else 1)
finally:
    m.close()
