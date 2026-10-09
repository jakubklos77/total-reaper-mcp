---
name: reaper-tempo-sync
description: Build a dynamic tempo map in REAPER for MIDI played freely without a metronome (rubato, own tempo), so the DAW's bars and beats line up with the played notes while playback stays exactly as performed. Moves every event (notes, sustain pedal/CC, sysex) with it. Use when the user wants to "sync the tempo to my playing", "make the grid match the notes", "fit bars/beats to a free performance", "tempo map from MIDI", or similar for a MIDI take in a running REAPER connected through the reaper-daw MCP server.
---

# Reaper tempo sync

Turns a freely played MIDI take into one that sits on REAPER's grid **without changing how
it sounds**: a tempo marker goes on every played beat (square shape), and all events are
written back at their original absolute times. Afterwards beats/bars match the notes, so
quantising, editing, notation and adding other parts work against the real pulse.

## Requirements

- REAPER running with the MCP bridge script and the `reaper-daw` MCP server (this repo); the
  scripts use its `midi_get`, `midi_set`, `tempo_map_get` and `tempo_map_set` tools.
- The take must follow project tempo (default for MIDI items).
- The scripts start their own MCP server instance via `$REAPER_MCP_LAUNCHER`
  (default `/home/jakub/Music/AI/reaper-mcp.sh`), because a whole take is too much data to
  pass through tool calls by hand. Run them from this skill's `scripts/` directory.

## Workflow

1. **Find the item.** `item_list` (index, track, position, length, midi) and
   `midi_get(item=…, notes=false, ccs=false)` (counts) identify it. Item indices are
   project-wide, 0-based. If unsure which item, ask.

2. **Ask only what can't be detected.** The defaults are 4/4 played in eighth notes
   (`--beats-per-bar 4 --slots-per-beat 2`). Use 3 for 3/4, `--slots-per-beat 3` for
   triplet/compound feel (e.g. 6/8 = `--beats-per-bar 2 --slots-per-beat 3`),
   `--slots-per-beat 4` for sixteenths (tested on 4/4 eighths & sixteenths, 3/4, 6/8). If the
   user didn't say and the meter isn't obvious,
   ask before applying. Compound meters are written with quarter-note beats (6/8 shows as 2/4,
   tempo in dotted quarters) - the grid is right, only the signature label differs; tell the user.

3. **Dry run** (changes nothing):
   ```bash
   cd .claude/skills/reaper-tempo-sync/scripts && python3 tempo_sync.py --item 0
   ```
   The last line is `RESULT {json}`. Show the user: bars, BPM range/median, per-bar BPM,
   irregular bars (`[bar_number, beats]`, e.g. a 2/4 bar before a final chord), pickup and
   lead-in, and `onset_grid_dev_ms_median` (≈0 means beats sit on the notes). Sanity-check:
   per-bar BPM should move smoothly; one bar far off its neighbours (e.g. 2× or ½) usually
   means the wrong subdivision or meter - try another `--slots-per-beat`/`--beats-per-bar`.

4. **Apply** after the user agrees:
   ```bash
   python3 tempo_sync.py --item 0 --apply
   ```
   It saves a backup, writes the tempo map, rewrites all events at their original times,
   re-reads and verifies. Require `"ok": true`, `events_same_payload: true`,
   `max_time_shift_ms` < 2 (tick rounding), `max_downbeat_offset_qn` ≈ 0. Report these and the
   backup path. The project is not saved - the user saves when happy.

5. **Undo / restore.** In REAPER: undo twice (tempo map + MIDI). From a backup at any time:
   `python3 tempo_sync.py --restore ~/.cache/reaper-tempo-sync/<file>.json`.

## Options and behaviour

- `--per-bar`: one marker per bar - smoother tempo lane, but beats inside a bar can be off
  by tens of ms. Default per-beat is exact; offer per-bar only if the user wants a cleaner
  tempo lane.
- `--force`: replace an existing tempo map (otherwise the script refuses).
- **How bars are found:** every onset is assigned to a subdivision slot by a global optimizer
  (tempo smoothness + local tempo), with downbeat evidence from long/sustained notes and
  sustain-pedal re-presses. Short bars (e.g. 2/4) are inserted only where the evidence
  demands it, and become time-signature changes in REAPER.
- **Pickup:** if the music starts before the first downbeat, the first bar becomes a short
  bar (e.g. 1/4). **Late start:** silence before the first note becomes whole lead-in beats
  at the opening tempo. If a pickup would start before 0 s, the script stops and says how
  far to move the item right.
- Simultaneous chord notes (within 35 ms) count as one onset; muted notes are ignored for
  analysis but are still moved.

## Errors

`RESULT` with `"mode": "error"` explains the problem (existing tempo markers, take ignores
project tempo, pickup before project start, too few notes). Exit code 1 after `--apply`
means verification failed: report the numbers and offer `--restore` with the printed backup.

## Files

- `scripts/tempo_sync.py` - CLI: dry run / apply / restore against live REAPER.
- `scripts/tempo_analysis.py` - DAW-independent detection: `analyze(notes, pedal, ...)`.
- `scripts/mcp_client.py` - minimal stdio MCP client.
