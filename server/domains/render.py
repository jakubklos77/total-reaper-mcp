"""Rendering and track freezing."""
from typing import Annotated, List, Literal, Optional

from pydantic import Field

from ..core import TrackRef, rcall, write


@write
async def render_project(
    directory: Annotated[Optional[str], Field(description="Output directory on the REAPER machine (default: project render setting)")] = None,
    file_name: Annotated[Optional[str], Field(description="File name or REAPER pattern without extension, e.g. 'mix' or '$project-$date'")] = None,
    bounds: Annotated[Optional[Literal["project", "time_selection", "custom", "all_regions", "selected_items"]], Field(description="What to render")] = None,
    start: Annotated[Optional[float], Field(description="Start (s) for bounds='custom'")] = None,
    end: Annotated[Optional[float], Field(description="End (s) for bounds='custom'")] = None,
    wav_bits: Annotated[Optional[Literal[16, 24, 32]], Field(description="Render as WAV with this bit depth (default: project format)")] = None,
    sample_rate: Annotated[Optional[int], Field(description="Sample rate (default: project setting)")] = None,
    channels: Annotated[Optional[int], Field(description="Channel count (default: project setting)")] = None,
    tail_ms: Annotated[Optional[int], Field(description="Render this many ms past the end (reverb tails)")] = None,
    overwrite: Annotated[bool, Field(description="Replace existing output files (otherwise the render is refused)")] = False,
) -> dict:
    """Render (bounce) the project to audio files, blocking until done; returns the output files.
    Unspecified options use the project's render settings; given ones apply only to this render."""
    return await rcall("render_project", directory=directory, file_name=file_name, bounds=bounds, start=start,
                       end=end, wav_bits=wav_bits, sample_rate=sample_rate, channels=channels, tail_ms=tail_ms,
                       overwrite=overwrite)


@write
async def track_freeze(
    tracks: Annotated[List[TrackRef], Field(description="Tracks to freeze")],
    mode: Annotated[Literal["stereo", "mono", "multichannel"], Field(description="Freeze format")] = "stereo",
) -> dict:
    """Freeze tracks: render items+FX to audio and unload the FX (saves CPU; reversible with track_unfreeze)."""
    return await rcall("track_freeze", tracks=tracks, mode=mode)


@write
async def track_unfreeze(
    tracks: Annotated[List[TrackRef], Field(description="Tracks to unfreeze")],
) -> dict:
    """Unfreeze tracks (restore their original items and FX)."""
    return await rcall("track_unfreeze", tracks=tracks)
