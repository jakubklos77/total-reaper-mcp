"""Shared plumbing for domain tools: one bridge call per tool, errors become tool errors."""
from typing import Any, Callable, Dict, List, Union

from mcp.server.fastmcp.exceptions import ToolError
from mcp.types import ToolAnnotations

from .bridge import bridge

TrackRef = Union[int, str]   # 0-based index, -1 = master, GUID "{...}" or exact name
ItemRef = Union[int, str]    # project-wide 0-based index or GUID


async def rcall(func: str, /, **params: Any) -> Dict[str, Any]:
    """Call Lua handler H.<func>(params) in REAPER; None-valued params are omitted."""
    result = await bridge.call_lua(func, [{k: v for k, v in params.items() if v is not None}])
    if not result.get("ok"):
        raise ToolError(result.get("error", "Unknown error"))
    result.pop("ok", None)
    return result


# Tool registry: domain modules decorate their functions with @read / @write / @destructive;
# server.app registers everything collected here.
TOOLS: List[tuple] = []


def _register(annotations: ToolAnnotations) -> Callable:
    def deco(func: Callable) -> Callable:
        TOOLS.append((func, annotations))
        return func
    return deco


read = _register(ToolAnnotations(readOnlyHint=True, destructiveHint=False, openWorldHint=False))
write = _register(ToolAnnotations(readOnlyHint=False, destructiveHint=False, openWorldHint=False))
destructive = _register(ToolAnnotations(readOnlyHint=False, destructiveHint=True, openWorldHint=False))
