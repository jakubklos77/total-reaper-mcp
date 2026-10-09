"""REAPER actions (main section)."""
from typing import Annotated, Union

from pydantic import Field

from ..core import destructive, rcall, read

COMMAND = Field(description="Command id (e.g. 40044) or named command (e.g. '_SWS_ABOUT', '_RS...')")


@read
async def action_find(
    query: Annotated[str, Field(description="Words that must all appear in the action name, e.g. 'toggle metronome'")],
    limit: Annotated[int, Field(description="Maximum results")] = 50,
) -> dict:
    """Search REAPER's action list (incl. SWS/ReaPack/custom actions): id, name, named command, toggle state."""
    return await rcall("action_find", query=query, limit=limit)


@destructive
async def action_run(command: Annotated[Union[int, str], COMMAND]) -> dict:
    """Run a REAPER action, exactly as if chosen from the action list. Prefer a domain tool when one fits.
    Actions that open dialogs block REAPER (and this connection) until the dialog is closed."""
    return await rcall("action_run", command=command)


@read
async def action_state(command: Annotated[Union[int, str], COMMAND]) -> dict:
    """Toggle state of an action: 1 on, 0 off, -1 not a toggle."""
    return await rcall("action_state", command=command)
