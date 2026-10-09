-- Project, tabs, undo

local function proj_path()
    local _, path = reaper.EnumProjects(-1)
    return path or ""
end

local function current_tab_index()
    local cur = reaper.EnumProjects(-1)
    local i = 0
    while true do
        local proj = reaper.EnumProjects(i)
        if not proj then return -1 end
        if proj == cur then return i end
        i = i + 1
    end
end

H.project_info = function(p)
    local _, num, den = 0, 4, 4
    num, den = reaper.TimeMap_GetTimeSigAtTime(0, 0)
    local ts_start, ts_end = reaper.GetSet_LoopTimeRange(false, false, 0, 0, false)
    local n_mark, n_markers, n_regions = reaper.CountProjectMarkers(0)
    local srate_use = reaper.GetSetProjectInfo(0, "PROJECT_SRATE_USE", 0, false) == 1
    return {
        name = reaper.GetProjectName(0, ""),
        path = proj_path(),
        dirty = reaper.IsProjectDirty(0) ~= 0,
        tab_index = current_tab_index(),
        length = reaper.GetProjectLength(0),
        bpm = reaper.Master_GetTempo(),
        time_signature = string.format("%d/%d", num, den),
        tempo_markers = reaper.CountTempoTimeSigMarkers(0),
        sample_rate = srate_use and reaper.GetSetProjectInfo(0, "PROJECT_SRATE", 0, false) or NULL,
        tracks = reaper.CountTracks(0),
        items = reaper.CountMediaItems(0),
        markers = n_markers, regions = n_regions,
        cursor = reaper.GetCursorPosition(),
        time_selection = {start = ts_start, ["end"] = ts_end},
        reaper_version = reaper.GetAppVersion(),
    }
end

H.project_save = function(p)
    if p.path then
        if not p.path:lower():match("%.rpp$") then fail("path must end with .rpp") end
        reaper.Main_SaveProjectEx(0, p.path, 0)
    else
        if proj_path() == "" then fail("project has never been saved - pass a path (avoids a Save As dialog)") end
        reaper.Main_SaveProject(0, false)
    end
    return {path = proj_path(), dirty = reaper.IsProjectDirty(0) ~= 0}
end

H.project_notes = function(p)
    if p.text ~= nil then
        reaper.GetSetProjectNotes(0, true, p.text)
        reaper.MarkProjectDirty(0)
    end
    return {text = reaper.GetSetProjectNotes(0, false, "")}
end

local function undo_step(redo)
    local can = redo and reaper.Undo_CanRedo2(0) or reaper.Undo_CanUndo2(0)
    if not can then fail("nothing to %s", redo and "redo" or "undo") end
    local ok = redo and reaper.Undo_DoRedo2(0) or reaper.Undo_DoUndo2(0)
    if ok == 0 then fail("%s failed", redo and "redo" or "undo") end
    return {[redo and "redone" or "undone"] = can,
            next_undo = reaper.Undo_CanUndo2(0), next_redo = reaper.Undo_CanRedo2(0)}
end
H.project_undo = function(p) return undo_step(false) end
H.project_redo = function(p) return undo_step(true) end

H.project_tabs = function(p)
    local tabs, cur, i = {}, reaper.EnumProjects(-1), 0
    while true do
        local proj, path = reaper.EnumProjects(i)
        if not proj then break end
        tabs[#tabs + 1] = {index = i, name = reaper.GetProjectName(proj, ""), path = path,
                           current = proj == cur, dirty = reaper.IsProjectDirty(proj) ~= 0}
        i = i + 1
    end
    return {tabs = list(tabs)}
end

H.project_new_tab = function(p)
    reaper.Main_OnCommand(40859, 0)     -- File: New project tab
    return {tab_index = current_tab_index()}
end

H.project_select_tab = function(p)
    local proj = reaper.EnumProjects(p.index or -2)
    if not proj then fail("no project tab %s", tostring(p.index)) end
    reaper.SelectProjectInstance(proj)
    return {tab_index = current_tab_index(), name = reaper.GetProjectName(proj, "")}
end

-- Close the current tab. Never risks REAPER's modal "save changes?" dialog (which would block
-- the bridge): with save_path the project is saved there first; an unsaved, modified project
-- is refused.
H.project_close_tab = function(p)
    if p.save_path then
        H.project_save({path = p.save_path})
        -- Main_SaveProjectEx writes the file but leaves the tab "modified"; re-open the saved file
        -- in this tab without prompting so it is clean and closes without a dialog.
        reaper.Main_openProject("noprompt:" .. p.save_path)
    end
    if reaper.IsProjectDirty(0) ~= 0 then
        fail("project has unsaved changes - pass save_path, or save it first")
    end
    local i = current_tab_index()
    reaper.Main_OnCommand(40860, 0)     -- File: Close current project tab
    return {closed_tab = i, tab_index = current_tab_index()}
end
