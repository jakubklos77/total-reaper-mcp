"""
Live tests against a running REAPER.  Run:  pytest tests/live --live

The server is started with $REAPER_MCP_LAUNCHER (any command that runs `python -m server.app`
with stdio, e.g. an ssh wrapper), default: python -m server.app in this repo.
All tests run in a fresh SCRATCH PROJECT TAB which is saved to <REAPER resource>/mcp_live_test.rpp
and closed afterwards; the user's tabs are never modified.
"""
import json, os, subprocess, sys, pathlib
import pytest

ROOT = pathlib.Path(__file__).resolve().parents[2]


class ToolError(Exception):
    pass


class Client:
    """Minimal synchronous MCP stdio client."""

    def __init__(self):
        cmd = os.environ.get("REAPER_MCP_LAUNCHER")
        argv = [cmd] if cmd else [sys.executable, "-m", "server.app"]
        self.p = subprocess.Popen(argv, cwd=ROOT, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                  stderr=subprocess.DEVNULL, text=True, bufsize=1)
        self.i = 0
        self._rpc("initialize", {"protocolVersion": "2025-06-18", "capabilities": {},
                                 "clientInfo": {"name": "live-tests", "version": "1"}})
        self._send({"jsonrpc": "2.0", "method": "notifications/initialized"})

    def _send(self, m):
        self.p.stdin.write(json.dumps(m) + "\n"); self.p.stdin.flush()

    def _rpc(self, method, params=None):
        self.i += 1
        self._send({"jsonrpc": "2.0", "id": self.i, "method": method, "params": params or {}})
        while True:
            line = self.p.stdout.readline()
            if not line: raise RuntimeError("server closed the connection")
            try: m = json.loads(line)
            except ValueError: continue
            if m.get("id") == self.i: return m

    def tools(self):
        return {t["name"]: t for t in self._rpc("tools/list")["result"]["tools"]}

    def __call__(self, name, /, **args):
        r = self._rpc("tools/call", {"name": name, "arguments": args})
        if "error" in r: raise ToolError(r["error"])
        res = r["result"]
        txt = "".join(c.get("text", "") for c in res.get("content", []))
        if res.get("isError"): raise ToolError(txt)
        if "structuredContent" in res:
            sc = res["structuredContent"]
            return sc.get("result", sc) if set(sc) == {"result"} else sc
        return json.loads(txt) if txt[:1] in "[{" else txt

    def close(self):
        try: self.p.stdin.close(); self.p.wait(5)
        except Exception: self.p.kill()


@pytest.fixture(scope="session")
def client():
    c = Client()
    yield c
    c.close()


@pytest.fixture(scope="session")
def scratch(client):
    """A fresh project tab for the whole session; closed (after saving) at the end."""
    before = client("project_tabs")["tabs"]
    home = next(t["index"] for t in before if t["current"])
    client("project_new_tab")
    info = client("project_info")
    if info["path"] or info["tracks"] or info["items"]:
        raise RuntimeError(f"new tab is not an empty project ({info}) - refusing to run live tests")
    scratch_index = info["tab_index"]
    resource = client("reaper_api", func="GetResourcePath")["ret"][0]
    yield {"home": home, "index": scratch_index, "save_path": resource.replace("\\", "/") + "/mcp_live_test.rpp"}
    # make sure we close the scratch tab, not a user tab
    client("project_select_tab", index=scratch_index)
    assert client("project_info")["path"] in ("",) or client("project_info")["path"].endswith("mcp_live_test.rpp")
    client("project_close_tab", save_path=resource.replace("\\", "/") + "/mcp_live_test.rpp")
    client("project_select_tab", index=home)


@pytest.fixture
def r(client, scratch):
    """Tool caller for one test; each test starts from an empty scratch project."""
    info = client("project_info")
    assert info["tab_index"] == scratch["index"], "not on the scratch tab"
    for t in reversed(client("track_list")["tracks"]):
        client("track_delete", track=t["index"])
    if client("tempo_map_get")["markers"]:
        client("tempo_map_set", points=[], clear=True, base_bpm=120)
    client("tempo_set", bpm=120)
    client("time_selection_set", start=0, end=0, target="both")
    return client
