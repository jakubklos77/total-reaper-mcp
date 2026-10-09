"""Live: items and takes."""
import pytest
from conftest import ToolError


def _setup(r):
    r("track_create", name="T1"); r("track_create", name="T2")
    return r("item_create_midi", track=0, start=1.0, length=2.0, name="clip")


def test_item_create_list_get(r):
    it = _setup(r)
    assert it["position"] == pytest.approx(1) and it["length"] == pytest.approx(2) and it["midi"]
    assert it["name"] == "clip" and it["track"] == 0
    r("item_create_midi", track="T2", start=0, end=0.5)
    assert len(r("item_list")["items"]) == 2
    assert [i["track"] for i in r("item_list", track="T2")["items"]] == [1]
    assert len(r("item_list", start=2.5)["items"]) == 1          # only the first ends after 2.5
    g = r("item_get", item=it["guid"])
    assert g["take_list"][0]["midi"] and g["take_list"][0]["notes"] == 0 and g["fade_in"] >= 0


def test_item_set_move_and_validation(r):
    it = _setup(r)
    s = r("item_set", item=it["index"], position=4, length=1.5, mute=True, color="#00ff00",
          volume_db=-3, fade_in=0.1, name="renamed", notes="n1", track="T2")
    assert s["position"] == pytest.approx(4) and s["length"] == pytest.approx(1.5) and s["mute"]
    assert s["track"] == 1 and s["name"] == "renamed" and s["color"] == "#00ff00"
    g = r("item_get", item=s["guid"])
    assert g["volume_db"] == pytest.approx(-3) and g["fade_in"] == pytest.approx(0.1) and g["notes"] == "n1"
    with pytest.raises(ToolError, match="length must be"):
        r("item_set", item=s["guid"], length=0)
    with pytest.raises(ToolError, match="master"):
        r("item_set", item=s["guid"], track=-1)
    with pytest.raises(ToolError, match="no item at index"):
        r("item_get", item=99)


def test_split_duplicate_glue_select_delete(r):
    it = _setup(r)
    sp = r("item_split", item=it["guid"], position=2.0)
    assert sp["left"]["end"] == pytest.approx(2) and sp["right"]["position"] == pytest.approx(2)
    with pytest.raises(ToolError, match="inside the item"):
        r("item_split", item=sp["left"]["guid"], position=5)
    d = r("item_duplicate", item=sp["right"]["guid"], position=6, track="T2")
    assert d["position"] == pytest.approx(6) and d["track"] == 1
    assert len(r("item_list")["items"]) == 3
    g = r("item_glue", items=[sp["left"]["guid"], sp["right"]["guid"]])
    assert len(g["items"]) == 1 and g["items"][0]["position"] == pytest.approx(1) \
        and g["items"][0]["length"] == pytest.approx(2)
    sel = r("item_select", items=[0, 1])["selected"]
    assert sel == [0, 1]
    assert r("item_select", items=[])["selected"] == []
    n = len(r("item_list")["items"])
    r("item_delete", item=d["guid"])
    assert len(r("item_list")["items"]) == n - 1


def test_takes(r):
    it = _setup(r)
    t2 = r("take_add", item=it["guid"], name="second")
    assert t2["index"] == 1 and t2["name"] == "second"
    assert r("item_get", item=it["guid"])["active_take"] == 1
    ts = r("take_set", item=it["guid"], take=0, volume_db=-6, pan=0.25, pitch=2, playrate=1.5,
           preserve_pitch=True, active=True, name="first")
    assert ts["volume_db"] == pytest.approx(-6) and ts["pitch"] == 2 and ts["playrate"] == 1.5
    g = r("item_get", item=it["guid"])
    assert g["active_take"] == 0 and [t["name"] for t in g["take_list"]] == ["first", "second"]
    after = r("take_delete", item=it["guid"], take=1)
    assert after["takes"] == 1 and after["name"] == "first"
    with pytest.raises(ToolError, match="only one take"):
        r("take_delete", item=it["guid"], take=0)


def test_item_chunk_and_media_errors(r):
    it = _setup(r)
    ch = r("item_chunk_get", item=it["guid"])["chunk"]
    assert ch.startswith("<ITEM") and "<SOURCE MIDI" in ch
    out = r("item_chunk_set", item=it["guid"], chunk=ch.replace("MUTE 0", "MUTE 1", 1))
    assert out["mute"] is True
    with pytest.raises(ToolError, match="file not found"):
        r("item_insert_media", track=0, path="C:/definitely/missing.wav")
