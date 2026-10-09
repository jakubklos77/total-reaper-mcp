"""
REAPER MCP server.

Curated domain tools (see docs/REDESIGN.md) talking to lua/mcp_bridge.lua inside REAPER over
the file bridge. Run: python -m server.app   (stdio transport)

Env:
  REAPER_MCP_BRIDGE_DIR  bridge directory shared with REAPER (REAPER/Scripts/mcp_bridge_data)
  REAPER_MCP_DOMAINS     optional comma list to restrict domains, e.g. "track,midi,tempo"
  REAPER_MCP_TIMEOUT     seconds to wait for REAPER per call (default 15)
"""
import importlib
import logging
import os
import sys

from mcp.server.fastmcp import FastMCP

from . import core
from .domains import DOMAINS

logging.basicConfig(level=logging.INFO, stream=sys.stderr,
                    format="%(asctime)s %(name)s %(levelname)s %(message)s")
logger = logging.getLogger("reaper-mcp")

INSTRUCTIONS = """Controls a running REAPER DAW.
Objects: tracks by 0-based index (-1 = master), GUID or exact name; items by project-wide index or GUID;
takes by index on the item (-1 = active). Times are in seconds unless a parameter says qn (quarter notes)
or measure (1-based, as REAPER displays). Every write tool is one undo step (project_undo reverts it).
Use the *_list / *_get tools to look before changing things. reaper_api reaches any ReaScript function
not covered by a domain tool."""


def build_server() -> FastMCP:
    mcp = FastMCP("reaper", instructions=INSTRUCTIONS)
    wanted = [d.strip() for d in os.environ.get("REAPER_MCP_DOMAINS", "").split(",") if d.strip()]
    for name in DOMAINS:
        importlib.import_module(f".domains.{name}", __package__)
    for name in DOMAINS:
        if wanted and name not in wanted and name != "api":
            continue
        tools = [(f, a) for f, a in core.TOOLS if f.__module__.rsplit(".", 1)[-1] == name]
        for func, annotations in tools:
            mcp.tool(annotations=annotations)(func)
        logger.info("domain %-10s %3d tools", name, len(tools))
    return mcp


def main() -> None:
    build_server().run(transport="stdio")


if __name__ == "__main__":
    main()
