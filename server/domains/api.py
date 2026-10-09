"""Generic ReaScript passthrough for anything the domain tools don't cover."""
from typing import Annotated, Any, List, Optional

from pydantic import Field

from ..core import destructive, rcall, read


@destructive
async def reaper_api(
    func: Annotated[str, Field(description="ReaScript function name without 'reaper.', e.g. 'CountTracks', 'GetMediaTrackInfo_Value'")],
    args: Annotated[Optional[List[Any]], Field(description="Positional arguments. Use 0 for the current project. Pointers returned by earlier calls ({\"__ptr\": ...}) can be passed back.")] = None,
) -> dict:
    """Call any ReaScript API function directly (the long tail not covered by the domain tools).

    Returns {"ret": [all return values]}. Objects (tracks, items, takes, envelopes...) come back as
    handles {"__ptr": "..."} that stay valid while the object exists. Prefer domain tools when one
    fits: they validate input, resolve objects by index/name and make one undo step.
    """
    return await rcall("reaper_api", func=func, args=args or [])


@read
async def ping() -> dict:
    """Check the connection to REAPER; returns the REAPER version and bridge protocol version."""
    return await rcall("ping")
