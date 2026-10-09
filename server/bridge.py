"""
File bridge to the Lua script running inside REAPER (lua/mcp_bridge.lua).

A call writes   request_<id>.json   {"id", "func", "args"}   into the bridge directory;
the Lua bridge (polling every defer cycle) answers with  response_<id>.json  {"ok", ...}.
Both sides write to a temp name and rename, so nobody ever reads a half-written file.
Ids start at a random per-process base, so several server processes can share one REAPER.
"""
import asyncio
import json
import logging
import os
import random
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

BRIDGE_DIR = Path(os.environ.get(
    "REAPER_MCP_BRIDGE_DIR",
    os.path.expanduser("~/Library/Application Support/REAPER/Scripts/mcp_bridge_data")))


class ReaperFileBridge:
    def __init__(self, bridge_dir: Path = BRIDGE_DIR):
        self.bridge_dir = bridge_dir
        self.bridge_dir.mkdir(parents=True, exist_ok=True)
        self.request_id = random.randrange(1, 2**40) * 1000
        self._purge_stale_files()

    def _purge_stale_files(self, max_age_s: float = 120.0) -> None:
        """Remove leftovers of dead processes / timed-out calls. Newer files may belong to another
        live server process sharing this directory, so they are left alone."""
        now = time.time()
        for pattern in ("request_*.json*", "response_*.json*"):
            for f in self.bridge_dir.glob(pattern):
                try:
                    if now - f.stat().st_mtime > max_age_s:
                        f.unlink()
                except OSError:
                    pass

    async def call_lua(self, func: str, args: Optional[List[Any]] = None) -> Dict[str, Any]:
        self.request_id += 1
        rid = self.request_id
        request = self.bridge_dir / f"request_{rid}.json"
        response = self.bridge_dir / f"response_{rid}.json"
        tmp = request.with_suffix(".json.tmp")
        tmp.write_text(json.dumps({"id": rid, "func": func, "args": args or []}), encoding="utf-8")
        os.replace(tmp, request)

        timeout = float(os.environ.get("REAPER_MCP_TIMEOUT", "15"))
        deadline = time.monotonic() + timeout
        delay = 0.005
        while time.monotonic() < deadline:
            if response.exists():
                try:
                    data = json.loads(response.read_text(encoding="utf-8"))
                except (json.JSONDecodeError, OSError):
                    await asyncio.sleep(0.01)          # still being renamed into place
                    continue
                response.unlink(missing_ok=True)
                return data
            await asyncio.sleep(delay)
            delay = min(delay * 1.5, 0.05)
        request.unlink(missing_ok=True)
        response.unlink(missing_ok=True)
        logger.error("timeout waiting for REAPER (%s)", func)
        return {"ok": False, "error": f"Timed out after {timeout:.0f}s waiting for REAPER - is the MCP bridge "
                                       f"script running (Actions > mcp_bridge.lua)? A modal dialog in REAPER also blocks it."}


bridge = ReaperFileBridge()
