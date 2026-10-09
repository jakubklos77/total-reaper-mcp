"""Run the real lua/mcp_bridge.lua in embedded Lua 5.4 (lupa) against a small mocked REAPER."""
import itertools, json, pathlib
import pytest

lupa = pytest.importorskip("lupa")
from lupa import lua54

BRIDGE = pathlib.Path(__file__).resolve().parents[2] / "lua" / "mcp_bridge.lua"
_ids = itertools.count(1)


class Ptr:
    """Stands in for a REAPER pointer (Lua sees it as userdata)."""
    def __init__(self, kind, name=""):
        self.kind, self.name, self.id, self.alive = kind, name, next(_ids), True
    def __str__(self):
        return f"{self.kind}: 0x{self.id:08x}"


class MockReaper:
    def __init__(self, resource_dir):
        self.resource_dir = resource_dir
        self.tracks = [Ptr("MediaTrack*", "Piano"), Ptr("MediaTrack*", "Bass")]
        self.master = Ptr("MediaTrack*", "MASTER")
        self.chunks = {}
        self.console = []

    def build(self, lua):
        R = self
        b = lambda s: s.encode() if isinstance(s, str) else s
        api = {
            "GetResourcePath": lambda: R.resource_dir.encode(),
            "RecursiveCreateDirectory": lambda p, x: pathlib.Path(p.decode()).mkdir(parents=True, exist_ok=True),
            "ShowConsoleMsg": lambda m: R.console.append(m),
            "defer": lambda f: setattr(R, "deferred", f),
            "GetExtState": lambda s, k: b"",
            "GetAppVersion": lambda: b"7.80/win64",
            "time_precise": lambda: 0.0,
            "ValidatePtr2": lambda proj, p, ty: isinstance(p, Ptr) and p.alive and p.kind == ty.decode(),
            "ValidatePtr": lambda p, ty: isinstance(p, Ptr) and p.alive and p.kind == ty.decode(),
            "CountTracks": lambda proj: len(R.tracks),
            "GetTrack": lambda proj, i: R.tracks[i] if 0 <= i < len(R.tracks) else None,
            "GetMasterTrack": lambda proj: R.master,
            "SetTrackStateChunk": lambda tr, c, undo: R.chunks.__setitem__(tr.id, c.decode()) or True,
            "_chunk": lambda tr: R.chunks.get(tr.id, f"<TRACK\nNAME {tr.name}\n>").encode(),
            "Undo_BeginBlock2": lambda p: None, "Undo_EndBlock2": lambda p, d, f: None,
            "PreventUIRefresh": lambda x: None, "UpdateArrange": lambda: None,
            "_multi": lambda: lua.table(True, b"a", None, 7),
        }
        def enum_files(path, idx):
            names = sorted(f.name for f in pathlib.Path(path.decode()).iterdir() if f.is_file())
            return names[idx].encode() if idx < len(names) else None
        api["EnumerateFiles"] = enum_files
        lua.globals().reaper = lua.table_from({k.encode(): v for k, v in api.items()})
        lua.execute(b'''
            reaper.GetTrackStateChunk = function(tr, s, undo)
                if type(tr) ~= "userdata" then error("bad argument #1 (MediaTrack expected)") end
                return true, reaper._chunk(tr)
            end
            reaper.GetTrackName = function(tr) return true, "x" end
            reaper.Multi = function() local t = reaper._multi(); return t[1], t[2], t[3], t[4] end
        ''')


@pytest.fixture
def bridge(tmp_path):
    lua = lua54.LuaRuntime(unpack_returned_tuples=True, encoding=None)
    R = MockReaper(str(tmp_path))
    R.build(lua)
    lua.execute(BRIDGE.read_bytes())
    data = tmp_path / "Scripts" / "mcp_bridge_data"

    def call(func, *args, raw=None):
        rid = 987654321000 + next(_ids)
        body = raw if raw is not None else json.dumps({"id": rid, "func": func, "args": list(args)})
        (data / f"request_{rid}.json").write_text(body)
        R.deferred()
        resp = data / f"response_{rid}.json"
        assert resp.exists(), b"".join(R.console[-3:]).decode(errors="replace")
        out = json.loads(resp.read_bytes().decode("utf-8"))
        resp.unlink()
        return out
    call.R = R
    return call
