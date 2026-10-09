"""Live: api, project, transport, time, tempo, track domains."""
import pytest
from conftest import ToolError


def test_tool_list_is_curated(client):
    names = set(client.tools())
    assert {"track_list", "tempo_map_set", "reaper_api", "project_info"} <= names
    assert not any(n.startswith("dsl_") for n in names)


def test_ping_and_api_passthrough(r):
    assert r("ping")["bridge"] == 2
    assert r("reaper_api", func="CountTracks", args=[0])["ret"] == [0]
    with pytest.raises(ToolError, match="unknown ReaScript function"):
        r("reaper_api", func="NoSuchFunction")


def test_project_info_notes_undo(r):
    info = r("project_info")
    assert info["tracks"] == 0 and info["bpm"] == 120 and info["time_signature"] == "4/4"
    assert r("project_notes", text="hello\nworld")["text"] == "hello\nworld"
    r("track_create", name="U")
    assert r("project_info")["tracks"] == 1
    undone = r("project_undo")
    assert "create track" in undone["undone"]
    assert r("project_info")["tracks"] == 0
    r("project_redo")
    assert r("project_info")["tracks"] == 1


def test_transport_cursor_repeat(r):
    s = r("transport_set_cursor", position=3.5)
    assert s["cursor"] == pytest.approx(3.5) and not s["playing"]
    assert r("transport_set_repeat", enabled=True)["repeat_enabled"] is True
    assert r("transport_set_repeat", enabled=False)["repeat_enabled"] is False
    assert r("transport_state")["cursor"] == pytest.approx(3.5)


def test_time_selection_and_convert(r):
    out = r("time_selection_set", start=2, end=4, target="both")
    assert out["time_selection"] == {"start": 2, "end": 4} and out["loop"] == {"start": 2, "end": 4}
    out = r("time_selection_set", start=1, end=1.5, target="loop")
    assert out["loop"] == {"start": 1, "end": 1.5}
    expected_ts = {"start": 1, "end": 1.5} if out["linked"] else {"start": 2, "end": 4}
    assert out["time_selection"] == expected_ts
    c = r("time_convert", seconds=2.5)                   # 120 BPM 4/4: 5 beats -> measure 2 beat 2
    assert c["qn"] == pytest.approx(5) and c["measure"] == 2 and c["beat"] == pytest.approx(2)
    assert r("time_convert", measure=3, beat=1)["seconds"] == pytest.approx(4.0)
    assert r("time_convert", qn=2)["seconds"] == pytest.approx(1.0)
    assert r("time_convert", text="3.1.00")["seconds"] == pytest.approx(4.0)


def test_grid(r):
    g0 = r("grid_get")
    g = r("grid_set", division=0.125, swing=True, swing_amount=0.3)
    assert g["division"] == pytest.approx(0.125) and g["swing"] and g["swing_amount"] == pytest.approx(0.3)
    r("grid_set", division=g0["division"], swing=g0["swing"], swing_amount=g0["swing_amount"])


def test_tempo_map_roundtrip(r):
    r("tempo_map_set", points=[[0, 100, 4, 4, False], [2.4, 140, 3, 4, False], {"time": 4.0, "bpm": 90}])
    tm = r("tempo_map_get")
    assert [m["bpm"] for m in tm["markers"]] == [100, 140, 90]
    assert tm["markers"][1]["time_signature"] == "3/4" and tm["markers"][1]["measure"] == 2
    m = r("tempo_marker_set", index=2, bpm=95, linear=True)
    assert m["bpm"] == 95 and m["linear"] is True
    added = r("tempo_marker_add", time=6.0, bpm=120)
    assert added["bpm"] == 120 and added["index"] == 3
    r("tempo_marker_delete", index=3)
    assert len(r("tempo_map_get")["markers"]) == 3
    with pytest.raises(ToolError, match="tempo markers"):
        r("tempo_set", bpm=100)
    r("tempo_map_set", points=[], base_bpm=87)
    tm = r("tempo_map_get")
    assert tm["markers"] == [] and tm["project_bpm"] == 87


def test_track_crud(r):
    a = r("track_create", name="Piano", color="#ff8000", volume_db=-6, pan=-0.5)
    assert a["name"] == "Piano" and a["color"] == "#ff8000" and a["volume_db"] == pytest.approx(-6)
    b = r("track_create", name="Bass")
    c = r("track_create", name="Drums", index=0)
    names = [t["name"] for t in r("track_list")["tracks"]]
    assert names == ["Drums", "Piano", "Bass"]
    s = r("track_set", track="Bass", mute=True, solo=True, auto_arm=False, arm=True, width=0.5, input=6112, monitor=1)
    assert s["mute"] and s["solo"] and s["arm"] and not s["auto_arm"]
    r("track_set", track="Bass", arm=False, auto_arm=True)
    with pytest.raises(ToolError, match="automatic record-arm"):
        r("track_set", track="Bass", arm=True)
    g = r("track_get", track="Bass")
    assert g["input"] == 6112 and g["monitor"] == 1 and g["width"] == pytest.approx(0.5)
    assert r("track_get", track=g["guid"])["name"] == "Bass"
    r("track_set", track=1, clear_color=True)
    assert r("track_get", track=1)["color"] is None
    moved = r("track_move", track="Drums", to_index=2)
    assert moved["index"] == 2
    assert [t["name"] for t in r("track_list")["tracks"]] == ["Piano", "Bass", "Drums"]
    r("track_move", track="Drums", to_index=0)
    assert [t["name"] for t in r("track_list")["tracks"]] == ["Drums", "Piano", "Bass"]
    d = r("track_duplicate", track="Piano")
    assert d["index"] == 2 and d["name"] == "Piano"
    assert r("track_select", tracks=[0, "Bass"])["selected"] == [0, 3]
    assert r("track_select", tracks=[])["selected"] == []
    with pytest.raises(ToolError, match="more than one track"):
        r("track_get", track="Piano")
    r("track_delete", track=2)
    with pytest.raises(ToolError, match="no track named"):
        r("track_get", track="Nope")
    with pytest.raises(ToolError, match="pan must be"):
        r("track_set", track=0, pan=3)
    master = r("track_set", track=-1, volume_db=-1.5)
    assert r("track_list")["master"]["volume_db"] == pytest.approx(-1.5)
    r("track_set", track=-1, volume_db=0)


def test_track_chunk_roundtrip(r):
    r("track_create", name="Chunky")
    ch = r("track_chunk_get", track=0)["chunk"]
    assert ch.startswith("<TRACK")
    r("track_chunk_set", track=0, chunk=ch.replace('NAME Chunky', 'NAME "Renamed, [x]"'))
    assert r("track_get", track=0)["name"] == "Renamed, [x]"
