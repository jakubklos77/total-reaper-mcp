"""Live: envelopes, markers, routing, render/freeze, actions."""
import pytest
from conftest import ToolError


def test_envelopes_volume_pan_fx(r):
    r("track_create", name="Env")
    s = r("envelope_points_set", track=0, name="Volume", points=[
        {"time": 0, "value_db": 0}, {"time": 1, "value_db": -6}, {"time": 2, "value_db": -12, "shape": 2}])
    assert s["points"] == 3
    g = r("envelope_get", track=0, name="Volume")
    assert [round(p["value_db"], 3) for p in g["point_list"]] == [0, -6, -12] and g["point_list"][2]["shape"] == 2
    r("envelope_points_set", track=0, name="Pan", points=[{"time": 0, "value": -1}, {"time": 1, "value": 1}])
    names = [e["name"] for e in r("envelope_list", track=0)["envelopes"]]
    assert "Volume" in names and "Pan" in names
    assert r("envelope_points_delete", track=0, name="Volume", start=0.5, end=1.5)["deleted"] == 1
    st = r("envelope_set", track=0, name="Volume", active=False, visible=False)
    assert st["active"] is False and st["visible"] is False
    r("envelope_set", track=0, name="Volume", active=True, visible=True)
    r("fx_add", track=0, name="ReaEQ")
    fxe = r("envelope_points_set", track=0, fx=0, param=0, points=[{"time": 0, "value": 0.2}, {"time": 1, "value": 0.8}])
    assert fxe["points"] == 2
    assert any(e.get("fx") == 0 for e in r("envelope_list", track=0)["envelopes"])
    with pytest.raises(ToolError, match="value_db only"):
        r("envelope_points_set", track=0, name="Pan", points=[{"time": 3, "value_db": -3}])
    with pytest.raises(ToolError, match="no 'Nonexistent'|can't be created"):
        r("envelope_points_set", track=0, name="Nonexistent", points=[{"time": 0, "value": 1}])


def test_markers_regions(r):
    m = r("marker_add", position=1.5, name="Verse", color="#ff0000")
    rg = r("marker_add", position=2, end=6, name="Chorus")
    assert m["region"] is False and rg["region"] is True and rg["end"] == 6
    lst = r("marker_list")
    assert [x["name"] for x in lst["markers"]] == ["Verse"] and [x["name"] for x in lst["regions"]] == ["Chorus"]
    e = r("marker_set", number=m["number"], position=1.75, name="Intro")
    assert e["position"] == 1.75 and e["name"] == "Intro" and e["color"] == "#ff0000"
    e = r("marker_set", number=rg["number"], region=True, end=8, name="")
    assert e["end"] == 8 and e["name"] == ""
    r("marker_delete", number=m["number"])
    assert r("marker_list")["markers"] == []
    with pytest.raises(ToolError, match="no marker number"):
        r("marker_delete", number=m["number"])
    r("marker_delete", number=rg["number"], region=True)


def test_routing(r):
    r("track_create", name="Src"); r("track_create", name="Verb")
    s = r("send_create", track="Src", dest_track="Verb", volume_db=-12, mode="pre_fx")
    assert s["dest_track"] == 1 and s["volume_db"] == pytest.approx(-12) and s["mode"] == "pre_fx"
    lst = r("send_list", track="Src")
    assert len(lst["sends"]) == 1 and lst["receives"] == []
    assert r("send_list", track="Verb")["receives"][0]["source_track"] == 0
    s2 = r("send_set", track="Src", index=0, mute=True, pan=-0.5, mode="post_fader")
    assert s2["mute"] and s2["pan"] == pytest.approx(-0.5) and s2["mode"] == "post_fader"
    with pytest.raises(ToolError, match="itself"):
        r("send_create", track="Src", dest_track="Src")
    assert r("send_delete", track="Src", index=0)["remaining"] == 0
    with pytest.raises(ToolError, match="no send 0"):
        r("send_set", track="Src", index=0, mute=False)


def test_render_and_insert_media_and_freeze(r, scratch):
    r("track_create", name="Synth")
    r("fx_add", track=0, name="ReaSynth")
    it = r("item_create_midi", track=0, start=0, length=1)["guid"]
    r("midi_insert_notes", item=it, notes=[{"pitch": 60, "start": 0, "length": 1.5}])
    folder = scratch["save_path"].rsplit("/", 1)[0] + "/mcp_live_render"
    out = r("render_project", directory=folder, file_name="bounce", bounds="custom", start=0, end=1, wav_bits=24,
            overwrite=True)
    with pytest.raises(ToolError, match="output file exists"):
        r("render_project", directory=folder, file_name="bounce", bounds="custom", start=0, end=1)
    assert len(out["files"]) == 1 and out["files"][0]["exists"] and out["files"][0]["path"].lower().endswith(".wav")
    wav = out["files"][0]["path"]
    r("track_create", name="Audio")
    ins = r("item_insert_media", track="Audio", path=wav, position=2)
    assert ins["position"] == 2 and ins["length"] == pytest.approx(1, abs=0.01) and not ins["midi"]
    g = r("item_get", item=ins["guid"])["take_list"][0]
    assert g["source_type"] == "WAVE"
    fr = r("track_freeze", tracks=["Synth"])
    assert fr["frozen"][0]["fx"] == 0
    un = r("track_unfreeze", tracks=["Synth"])
    assert un["unfrozen"][0]["fx"] == 1


def test_actions(r):
    found = r("action_find", query="toggle metronome")["actions"]
    assert found and all("metronome" in a["name"].lower() for a in found)
    act = next(a for a in found if a["id"] == 40364)
    before = r("action_state", command=40364)["state"]
    r("action_run", command=40364)
    assert r("action_state", command=40364)["state"] == 1 - before
    r("action_run", command="40364")
    assert r("action_state", command=40364)["state"] == before
    with pytest.raises(ToolError, match="unknown named command"):
        r("action_run", command="_NO_SUCH_COMMAND_XYZ")
