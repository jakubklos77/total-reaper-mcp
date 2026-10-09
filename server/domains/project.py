"""Project-level tools: info, save, notes, undo/redo, project tabs."""
from typing import Annotated, Optional

from pydantic import Field

from ..core import destructive, rcall, read, write


@read
async def project_info() -> dict:
    """Overview of the current project: name, path, unsaved changes, length, tempo, time signature,
    tempo marker/track/item/marker counts, edit cursor, time selection and REAPER version."""
    return await rcall("project_info")


@write
async def project_save(
    path: Annotated[Optional[str], Field(description="Save to this .rpp path (on the REAPER machine) instead of the project's own file")] = None,
) -> dict:
    """Save the project. Without a path the project must already have a file (never opens a dialog)."""
    return await rcall("project_save", path=path)


@write
async def project_notes(
    text: Annotated[Optional[str], Field(description="New notes text; omit to just read")] = None,
) -> dict:
    """Read or replace the project notes."""
    return await rcall("project_notes", text=text)


@write
async def project_undo() -> dict:
    """Undo the last action (any action, not only MCP ones). Returns what was undone."""
    return await rcall("project_undo")


@write
async def project_redo() -> dict:
    """Redo the last undone action."""
    return await rcall("project_redo")


@read
async def project_tabs() -> dict:
    """List open project tabs (index, name, path, current, unsaved changes)."""
    return await rcall("project_tabs")


@write
async def project_new_tab() -> dict:
    """Open a new empty project tab and make it current."""
    return await rcall("project_new_tab")


@write
async def project_select_tab(
    index: Annotated[int, Field(description="Tab index from project_tabs")],
) -> dict:
    """Switch to another project tab. All tools act on the current tab."""
    return await rcall("project_select_tab", index=index)


@destructive
async def project_close_tab(
    save_path: Annotated[Optional[str], Field(description="Save the project to this .rpp path before closing")] = None,
) -> dict:
    """Close the current project tab. Refuses if there are unsaved changes and no save_path
    (REAPER's 'save changes?' dialog would otherwise block the connection)."""
    return await rcall("project_close_tab", save_path=save_path)
