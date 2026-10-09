# REAPER MCP

An MCP server that lets AI assistants (Claude Code, Claude Desktop, any MCP client) work in a
running [REAPER](https://www.reaper.fm/). It offers about 95 curated tools across 14 domains, every one
tested against a real REAPER, plus a `reaper_api` passthrough to the whole ReaScript API.

```
MCP client ──stdio──► server (Python) ──JSON files──► lua/mcp_bridge.lua (inside REAPER)
```

## Tools

| Domain | Tools |
|---|---|
| project | `project_info` `project_save` `project_notes` `project_undo` `project_redo` `project_tabs` `project_new_tab` `project_select_tab` `project_close_tab` |
| transport | `transport_state` `transport_play` `transport_stop` `transport_pause` `transport_record` `transport_set_cursor` `transport_set_repeat` |
| time | `time_selection_get` `time_selection_set` `time_convert` `grid_get` `grid_set` |
| tempo | `tempo_map_get` `tempo_map_set` `tempo_marker_add` `tempo_marker_set` `tempo_marker_delete` `tempo_set` |
| track | `track_list` `track_get` `track_create` `track_set` `track_delete` `track_move` `track_duplicate` `track_select` `track_chunk_get` `track_chunk_set` |
| item | `item_list` `item_get` `item_create_midi` `item_insert_media` `item_set` `item_delete` `item_split` `item_duplicate` `item_glue` `item_select` `item_chunk_get` `item_chunk_set` `take_set` `take_add` `take_delete` |
| midi | `midi_get` `midi_set` `midi_insert_notes` `midi_edit_notes` `midi_delete_notes` `midi_insert_ccs` `midi_delete_ccs` `midi_quantize` `midi_transpose` |
| fx | `fx_list` `fx_installed` `fx_add` `fx_delete` `fx_move` `fx_set` `fx_params` `fx_param_set` `fx_presets` `fx_preset_set` `fx_show` |
| envelope | `envelope_list` `envelope_get` `envelope_points_set` `envelope_points_delete` `envelope_set` |
| marker | `marker_list` `marker_add` `marker_set` `marker_delete` |
| routing | `send_list` `send_create` `send_set` `send_delete` |
| render | `render_project` `track_freeze` `track_unfreeze` |
| action | `action_find` `action_run` `action_state` |
| api | `reaper_api` `ping` |

Conventions:

- **Addressing:** tracks are addressed by 0-based index (`-1` = master), GUID or exact name. Items are addressed by project-wide index or GUID. Takes are addressed by index on the item (`-1` = active take).
- **Units:** times are in seconds. MIDI positions also accept `qn`, which follows the tempo map, or `ppq`. Volumes are in dB.
- **Writes:** every write tool is a single undo step. Setters change only the fields you pass.
- **Annotations:** every tool is marked read-only or destructive, so clients can tell what is safe to run.
- **No dialogs:** the tools never open a modal dialog, which would block REAPER and the connection.
  - Closing a modified tab is refused instead of prompting.
  - Rendering refuses to overwrite an existing file unless you pass `overwrite`.
  - Saving never opens a Save As dialog.

See [docs/REDESIGN.md](docs/REDESIGN.md) for the design.

## Setup

1. **Bridge in REAPER.** Copy or symlink `lua/mcp_bridge.lua` into REAPER's `Scripts` folder. Load it with
   *Actions → Show action list → New action → Load ReaScript*, then run it. You can add it to
   `__startup.lua` so it runs at every start. It creates `Scripts/mcp_bridge_data/`.
2. **Server.** Run `uv venv && uv pip install -e .`, then point your MCP client at
   `python -m server.app`. Set `REAPER_MCP_BRIDGE_DIR` to the bridge folder from step 1.
   ```json
   {"mcpServers": {"reaper": {"command": "/path/to/.venv/bin/python", "args": ["-m", "server.app"],
     "cwd": "/path/to/repo", "env": {"REAPER_MCP_BRIDGE_DIR": "/path/to/REAPER/Scripts/mcp_bridge_data"}}}}
   ```
   If REAPER runs on another machine, start the server there over SSH; see
   [run_reaper_mcp.md](run_reaper_mcp.md).

Environment variables:

- `REAPER_MCP_DOMAINS` restricts the server to some domains, e.g. `track,midi,tempo`.
- `REAPER_MCP_TIMEOUT` sets the seconds to wait for each call. The default is 15.

## Development

- **Lua sources** live in `lua/src/`: `00_core.lua` (JSON, handles, object lookup), one file per domain, and
  `99_main.lua` (the request loop). Run `python3 scripts/build_bridge.py` to bundle them into
  `lua/mcp_bridge.lua`, the file REAPER runs. Commit the bundle, and don't edit it by hand.
- **Hot reload:** with ExtState `MCP_BRIDGE/autoreload = 1`, the bridge reloads itself when its file changes.
  Turn it on with `reaper_api(func="SetExtState", args=["MCP_BRIDGE","autoreload","1",true])`.
- **Debug log:** ExtState `MCP_BRIDGE/debug = 1` logs every request to the REAPER console.
- **Adding a tool:** add a Lua handler `H.<name> = function(p) ... end` and a typed Python wrapper in
  `server/domains/<domain>.py` decorated with `@read`, `@write` or `@destructive`. Then add a live test.

### Tests

```bash
pip install -e '.[test]'
pytest tests/core                 # offline: bridge core in embedded Lua (lupa) with a mocked REAPER
REAPER_MCP_LAUNCHER=./my-launcher.sh pytest tests/live --live
```

The live tests run in a fresh **scratch project tab**. At the end the tab is saved to
`<REAPER resource path>/mcp_live_test.rpp` and closed. Your own projects are never touched.

## Skills

`skills/reaper-tempo-sync` builds a tempo map that follows a freely played (rubato) MIDI
performance. DAW bars and beats then line up with the notes, while playback stays exactly as performed.

## Origin

This is a fork of [shiehn/total-reaper-mcp](https://github.com/shiehn/total-reaper-mcp), rebuilt from scratch on top of
its file-bridge idea. The old tools are gone: about 740 wrappers, many of them duplicates, placeholders or calls to
API functions that don't exist. So are the DSL layer, the tool profiles and the relay. Fixes from the rebuild:

- Pointer handles work across calls.
- Multi-value returns are kept.
- The JSON parser is a proper one.
- Several server processes can share one REAPER.
- Nothing in REAPER can block the bridge with a modal dialog.
