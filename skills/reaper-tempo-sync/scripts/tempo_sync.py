#!/usr/bin/env python3
"""
tempo_sync.py - tempo-sync a freely played (rubato, no metronome) MIDI take in the OPEN
REAPER project via the Reaper MCP server.

The performance keeps its exact timing; REAPER gets a tempo marker on every played beat so
bars/beats line up with the notes. All events (notes, pedal/CC, sysex, end marker) move.

  analyze  (default --dry-run): read the take, detect pulse/bars, print the report
  apply    (--apply): backup -> tempo_map_set -> midi_set(unit=seconds) -> verify
  restore  (--restore BACKUP.json): put the original tempo map and events back

Output: human-readable lines plus a final line "RESULT {json}".
"""
import argparse, json, os, sys, time
from mcp_client import MCPClient
from tempo_analysis import analyze

BACKUP_DIR = os.path.expanduser("~/.cache/reaper-tempo-sync")

ap = argparse.ArgumentParser()
ap.add_argument("--item", type=int, default=0, help="project-wide media item index")
ap.add_argument("--slots-per-beat", type=int, default=2, help="played subdivision per beat (2=eighths, 3=triplets, 4=16ths)")
ap.add_argument("--beats-per-bar", type=int, default=4)
ap.add_argument("--per-bar", action="store_true", help="one tempo marker per bar (smoother, beats inside bars not exact)")
mode = ap.add_mutually_exclusive_group()
mode.add_argument("--apply", action="store_true", help="write tempo map + events (default is a dry run)")
mode.add_argument("--restore", metavar="BACKUP", help="restore the original state from a backup file")
ap.add_argument("--force", action="store_true", help="replace an existing tempo map")
a = ap.parse_args()


def markers_to_points(markers):
    """tempo_map_get markers -> tempo_map_set points (also reads backups from the old server format)."""
    pts = []
    for m in markers:
        if isinstance(m, dict):
            num, den = (int(x) for x in m["time_signature"].split("/")) if m.get("time_signature") else (0, 0)
            pts.append([m["time"], m["bpm"], num, den, bool(m["linear"])])
        else:   # old format: [time, measure, beat, bpm, num, den, linear, qn]
            pts.append([m[0], m[3], max(m[4], 0), max(m[5], 0), bool(m[6])])
    return pts


def project_bpm(tm):
    return tm.get("project_bpm", tm.get("master_bpm"))


def result(**kw):
    print("RESULT " + json.dumps(kw))


m = MCPClient()
try:
    if a.restore:
        b = json.load(open(a.restore))
        if b["tempo_map"]["markers"]:
            m.call("tempo_map_set", points=markers_to_points(b["tempo_map"]["markers"]), clear=True)
        else:   # project had no markers: remove ours and put the plain project tempo back
            m.call("tempo_map_set", points=[], clear=True, base_bpm=project_bpm(b["tempo_map"]))
        m.call("midi_set", item=b["item"], unit="seconds", fit_item=True,
               events=[[e[3], e[1], e[2]] for e in b["events"]])
        after = m.call("midi_get", item=b["item"], notes=False, ccs=False, events=True)["events"]
        worst = max(abs(x[3] - y[3]) for x, y in zip(sorted(b["events"], key=lambda e: (e[3], e[2])),
                                                      sorted(after, key=lambda e: (e[3], e[2]))))
        print(f"restored {len(after)} events from {a.restore}; max time difference {worst*1000:.3f} ms")
        result(mode="restore", events=len(after), max_time_shift_ms=round(worst * 1000, 3))
        sys.exit(0)

    tm = m.call("tempo_map_get")
    if tm["markers"] and not a.force:
        result(mode="error", error=f"project already has {len(tm['markers'])} tempo markers; "
                                   "re-run with --force to replace them")
        sys.exit(2)
    take = m.call("midi_get", item=a.item, ccs=False, events=True)
    if not take["follows_project_tempo"]:
        result(mode="error", error="the take ignores project tempo (item property) - not supported")
        sys.exit(2)
    events = take["events"]          # [ppq, flags, hex, sec, qn]
    nf = take["note_fields"]
    notes = [(n["start_sec"], n["end_sec"], n["pitch"], n["velocity"])
             for n in (dict(zip(nf, row)) for row in take["notes"]) if not n["muted"]]
    pedal = [(e[3], int(e[2][4:6], 16)) for e in events
             if len(e[2]) == 6 and int(e[2][0:2], 16) & 0xF0 == 0xB0 and e[2][2:4] == "40"]
    try:
        res = analyze(notes, pedal, a.slots_per_beat, a.beats_per_bar, a.per_bar)
    except ValueError as e:
        result(mode="error", error=str(e)); sys.exit(2)
    rep = res["report"]
    print(f"{rep['notes']} notes, {rep['bars']} bars, BPM {rep['bpm_min']}-{rep['bpm_max']} "
          f"(median {rep['bpm_median']}), {rep['tempo_points']} tempo markers")
    print("per-bar BPM:", rep["per_bar_bpm"])
    if not a.apply:
        result(mode="dry-run", item=a.item, **{k: v for k, v in rep.items() if k != "bar_starts_sec"})
        sys.exit(0)

    os.makedirs(BACKUP_DIR, exist_ok=True)
    backup = os.path.join(BACKUP_DIR, time.strftime("%Y%m%d-%H%M%S") + f"-item{a.item}.json")
    json.dump({"item": a.item, "tempo_map": tm, "events": events}, open(backup, "w"))

    m.call("tempo_map_set", points=res["tempo_points"], clear=True)
    m.call("midi_set", item=a.item, unit="seconds", fit_item=True,
           events=[[e[3], e[1], e[2]] for e in events])

    # ---------- verify ----------
    after = m.call("midi_get", item=a.item, notes=False, ccs=False, events=True)["events"]
    same_payload = sorted((e[1], e[2]) for e in events) == sorted((e[1], e[2]) for e in after)
    worst = max(abs(x[3] - y[3]) for x, y in zip(sorted(events, key=lambda e: (e[3], e[2])),
                                                  sorted(after, key=lambda e: (e[3], e[2]))))
    tm2 = m.call("tempo_map_get")
    offsets = []                    # note-ons at bar starts should now sit exactly on the bar line
    for q in res["bar_start_qn"]:
        near = [abs(e[4] - q) for e in after if e[2][0] == "9" and abs(e[4] - q) < 0.25]
        if near: offsets.append(min(near))
    ok = same_payload and len(after) == len(events) and worst < 0.002 and len(tm2["markers"]) == rep["tempo_points"]
    print(f"verify: {len(after)} events, payload same={same_payload}, max shift {worst*1000:.3f} ms, "
          f"{len(tm2['markers'])} markers, bars on grid {sum(o < 0.01 for o in offsets)}/{len(offsets)}")
    result(mode="apply", ok=ok, item=a.item, backup=backup, events=len(after), events_same_payload=same_payload,
           max_time_shift_ms=round(worst * 1000, 3), tempo_markers=len(tm2["markers"]),
           bars_checked=len(offsets), max_downbeat_offset_qn=round(max(offsets), 4) if offsets else None,
           **{k: v for k, v in rep.items() if k not in ("bar_starts_sec",)})
    sys.exit(0 if ok else 1)
finally:
    m.close()
