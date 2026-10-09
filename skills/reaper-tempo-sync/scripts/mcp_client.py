"""Minimal stdio MCP client for the Reaper MCP server (for scripts that move a lot of data)."""
import json, os, subprocess


# Command that starts the Reaper MCP server over stdio (same one Claude Code uses).
LAUNCHER = os.environ.get("REAPER_MCP_LAUNCHER", "/home/jakub/Music/AI/reaper-mcp.sh")


class MCPClient:
    def __init__(self, cmd=LAUNCHER):
        self.p = subprocess.Popen([cmd], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                  stderr=subprocess.DEVNULL, text=True, bufsize=1)
        self.i = 0
        self._rpc("initialize", {"protocolVersion": "2024-11-05", "capabilities": {},
                                 "clientInfo": {"name": "tempo-sync", "version": "1"}})
        self._send({"jsonrpc": "2.0", "method": "notifications/initialized"})

    def _send(self, m):
        self.p.stdin.write(json.dumps(m) + "\n"); self.p.stdin.flush()

    def _rpc(self, method, params=None):
        self.i += 1
        self._send({"jsonrpc": "2.0", "id": self.i, "method": method, "params": params or {}})
        while True:
            line = self.p.stdout.readline()
            if not line: raise RuntimeError("MCP server closed the connection")
            try: m = json.loads(line)
            except ValueError: continue
            if m.get("id") == self.i: return m

    def call(self, name, **args):
        r = self._rpc("tools/call", {"name": name, "arguments": args})
        if "error" in r: raise RuntimeError(f"{name}: {r['error']}")
        res = r["result"]
        txt = "".join(c.get("text", "") for c in res.get("content", []))
        if res.get("isError"): raise RuntimeError(f"{name}: {txt}")
        try: return json.loads(txt)
        except ValueError: return txt

    def close(self):
        try: self.p.stdin.close(); self.p.wait(5)
        except Exception: self.p.kill()
