---
name: reaper-piano-to-strings
description: Arrange a piano MIDI take in REAPER (a composed sketch or a free improvisation) for a five-part string section - Violins 1, Violins 2, Violas, Cellos, Basses - by reading the voices already in the piano part - melody, bass, inner harmony, arpeggios/figures - and assigning them to instruments with smooth voice leading, open low-end spacing, legato overlap, CC1/CC11 swells and pedal points. Creates a 'Strings' folder of five MIDI tracks (no instruments loaded) and mutes the piano. Use when the user wants to "orchestrate / arrange for strings", "turn my piano sketch into strings", "split the piano into string parts", "piano to string section" or similar for a MIDI take in a running REAPER connected through the reaper-daw MCP server. Run it after reaper-performance-cleanup and reaper-tempo-sync.
---

# Reaper piano to strings

Separate composing from orchestrating: the piano take already holds the music, the skill only
decides **who plays what**. Nothing is invented - every string note comes from the piano part,
moved by whole octaves at most. It is a starting point the user then edits, not a finished
orchestration: every judgement call is listed for review.

## How a voice becomes a part (why it works this way)

| piano | strings | rule |
|---|---|---|
| melody | **Violins 1** (Cellos / Violas when the tune lies below the violin) | top line by default; a louder, non-repeating lower line wins (left-hand theme under right-hand chords) - always flagged |
| bass note of each chord | **Basses** | inversions kept (A/C# -> C#); rests while the bass lies above E3 for 2+ bars, so their entry has impact |
| moving lines: arpeggios, Alberti bass, inner runs | kept **as played** on one instrument | the bass-carrying figure -> Cellos, an inner one -> Violas, else Violins 2; same instrument as long as the figure stays in that register; at most 2 per bar |
| everything else that sounds (sustain pedal included) | **Cellos, Violas, Violins 2** (+ Violins 1 when there is no melody) | per beat, chord tones as played, smallest movement, no crossing, below the melody, Cellos-Basses >= a 5th apart (or unison/octave); too few notes -> doubling; leftover chord tones -> divisi in Violins 2 / Violas |

Polish (all on by default): **legato** (moving lines overlap by 1/16 beat for sample-library
legato), **CC1** dynamics from the played velocities and **CC11** swells per phrase, **pedal
points** (the melody note held as divisi over a stepwise bass, as in the classic "descending
bass under a held G").

MIDI notes are sounding pitches (as sample libraries expect; written double bass is an octave higher).

## Requirements

- REAPER running with the MCP bridge. The script starts its own server through
  `$REAPER_MCP_LAUNCHER` (default `/home/jakub/Music/AI/reaper-mcp.sh`); it uses `item_get`,
  `midi_get`, `midi_set`, `track_*`, `item_create_midi`.
- Analysis bars are taken from the project grid (`--bar 4` quarter notes). On a freely played
  take, run **reaper-tempo-sync first** so beats mean something; without it the arrangement
  still works but harmony is sampled on an arbitrary grid.
- Run from this skill's `scripts/` directory. Item index = project-wide, 0-based (`item_list`).

## Workflow

1. **Dry run** (changes nothing):
   ```bash
   cd .claude/skills/reaper-piano-to-strings/scripts && python3 strings.py --item 0
   ```
   Prints key, lines found, per instrument the note count, range and roles
   (melody / figure / harmony / divisi / pedal), then every flag, then `RESULT {json}`.

2. **Show the user** the plan per instrument and the flags, grouped by kind:
   - `melody` - the tune was taken from a lower line, or handed to Cellos / Violas: confirm.
   - `figure` - more moving lines than `--max-figures`; the rest became sustained harmony.
   - `octave` - a melody / figure moved by octaves to fit an instrument.
   - `bass-rest` - Basses rest while the bass lies high (`--bass-rest-from` MIDI pitch).
   - `pedal` - pedal point added (`--no-pedal` to skip).
   - `spacing` - Cellos closer than a 5th above the Basses (caused by a figure / melody).
   Bar numbers assume 4/4 from the project start.

3. **Apply** what the user agreed to:
   ```bash
   python3 strings.py --item 0 --apply [--no-pedal] [--no-legato] [--no-cc] [--max-figures 1] [--keep-piano]
   ```
   Creates a `Strings` folder right under the piano track with five coloured MIDI tracks
   (Violins 1, Violins 2, Violas, Cellos, Basses), one item each spanning the piano item, and
   mutes the piano track. **No instruments are loaded** - the user loads their own library.
   Require `"ok": true` (note counts verified in REAPER). Report the `backup` path. The project is
   not saved.
   A second run refuses while the folder exists; `--replace` deletes it and builds it again
   (e.g. with other options).

4. **Undo.** `python3 strings.py --restore ~/.cache/reaper-piano-to-strings/<file>.json` deletes
   the created tracks and restores the piano track's mute state.

## Limits (tell the user when they apply)

- Dense textures with more than 2 independent moving lines lose the extras to sustained harmony.
- Repeated chords (one note struck again and again) become sustained notes - strings may want
  repeated bowing there; the user can split notes or switch articulation.
- No articulation keyswitches, no dynamics markings beyond CC1/CC11, no tremolo/pizzicato.
- Time signature is not read: `--bar` is the analysis window (melody / figure decisions).

## Files

- `scripts/strings.py`: CLI for dry run, apply and restore against live REAPER.
- `scripts/arrange.py`: DAW-independent arrangement (`load`, `streams`, `melody`, `arrange`,
  `to_events`); reuses `piece.py` from reaper-performance-cleanup for parsing and key finding.
  Offline tests in the repo's `tests/skills/test_piano_to_strings.py`.
- `scripts/mcp_client.py`: a minimal stdio MCP client.
