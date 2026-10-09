-- Media items and takes

local function IV(it, k) return reaper.GetMediaItemInfo_Value(it, k) end
local function TV(tk, k) return reaper.GetMediaItemTakeInfo_Value(tk, k) end

local function item_summary(it)
    local take = reaper.GetActiveTake(it)
    local pos, len = IV(it, "D_POSITION"), IV(it, "D_LENGTH")
    return {
        index = item_index(it),
        guid = guid_of_item(it),
        track = track_index(reaper.GetMediaItem_Track(it)),
        position = pos, length = len, ["end"] = pos + len,
        name = take and reaper.GetTakeName(take) or "",
        midi = take ~= nil and reaper.TakeIsMIDI(take),
        mute = IV(it, "B_MUTE") == 1,
        locked = IV(it, "C_LOCK") & 1 == 1,
        selected = IV(it, "B_UISEL") == 1,
        color = color_from_native(math.tointeger(IV(it, "I_CUSTOMCOLOR"))),
        takes = reaper.CountTakes(it),
        active_take = take and math.tointeger(TV(take, "IP_TAKENUMBER")) or NULL,
    }
end

local function take_info(tk)
    local src = reaper.GetMediaItemTake_Source(tk)
    local file = src and reaper.GetMediaSourceFileName(src, "") or ""
    local t = {
        index = math.tointeger(TV(tk, "IP_TAKENUMBER")),
        name = reaper.GetTakeName(tk),
        guid = select(2, reaper.GetSetMediaItemTakeInfo_String(tk, "GUID", "", false)),
        midi = reaper.TakeIsMIDI(tk),
        source = file ~= "" and file or NULL,
        source_type = src and reaper.GetMediaSourceType(src, "") or NULL,
        volume_db = db_out(math.abs(TV(tk, "D_VOL"))),
        polarity_inverted = TV(tk, "D_VOL") < 0,
        pan = TV(tk, "D_PAN"),
        pitch = TV(tk, "D_PITCH"),
        playrate = TV(tk, "D_PLAYRATE"),
        preserve_pitch = TV(tk, "B_PPITCH") == 1,
        start_offset = TV(tk, "D_STARTOFFS"),
        color = color_from_native(math.tointeger(TV(tk, "I_CUSTOMCOLOR"))),
    }
    if t.midi then
        local _, notes, ccs, sysex = reaper.MIDI_CountEvts(tk)
        t.notes, t.ccs, t.sysex = notes, ccs, sysex
    end
    return t
end

H.item_list = function(p)
    local tr = p.track ~= nil and get_track(p.track) or nil
    local out = {}
    for i = 0, reaper.CountMediaItems(0) - 1 do
        local it = reaper.GetMediaItem(0, i)
        local pos = IV(it, "D_POSITION")
        local ok = (not tr or reaper.GetMediaItem_Track(it) == tr)
            and (p.start == nil or pos + IV(it, "D_LENGTH") > p.start)
            and (p["end"] == nil or pos < p["end"])
            and (not p.selected_only or IV(it, "B_UISEL") == 1)
        if ok then out[#out + 1] = item_summary(it) end
    end
    return {items = list(out)}
end

H.item_get = function(p)
    local it = get_item(p.item)
    local t = item_summary(it)
    t.volume_db = db_out(IV(it, "D_VOL"))
    t.fade_in, t.fade_out = IV(it, "D_FADEINLEN"), IV(it, "D_FADEOUTLEN")
    t.fade_in_shape, t.fade_out_shape = math.tointeger(IV(it, "C_FADEINSHAPE")), math.tointeger(IV(it, "C_FADEOUTSHAPE"))
    t.snap_offset = IV(it, "D_SNAPOFFSET")
    t.loop_source = IV(it, "B_LOOPSRC") == 1
    local _, notes = reaper.GetSetMediaItemInfo_String(it, "P_NOTES", "", false)
    t.notes = notes
    local takes = {}
    for i = 0, reaper.CountTakes(it) - 1 do
        local tk = reaper.GetTake(it, i)
        if tk then takes[#takes + 1] = take_info(tk) end
    end
    t.take_list = list(takes)
    return t
end

local function apply_item_props(it, p)
    if p.track ~= nil then
        local tr = get_track(p.track)
        if tr == reaper.GetMasterTrack(0) then fail("items can't be on the master track") end
        if reaper.GetMediaItem_Track(it) ~= tr and not reaper.MoveMediaItemToTrack(it, tr) then
            fail("could not move the item to that track")
        end
    end
    if p.position ~= nil then reaper.SetMediaItemInfo_Value(it, "D_POSITION", p.position) end
    if p.length ~= nil then
        if p.length <= 0 then fail("length must be > 0") end
        reaper.SetMediaItemInfo_Value(it, "D_LENGTH", p.length)
    end
    if p.mute ~= nil then reaper.SetMediaItemInfo_Value(it, "B_MUTE", p.mute and 1 or 0) end
    if p.locked ~= nil then reaper.SetMediaItemInfo_Value(it, "C_LOCK", p.locked and 1 or 0) end
    if p.selected ~= nil then reaper.SetMediaItemInfo_Value(it, "B_UISEL", p.selected and 1 or 0) end
    if p.color ~= nil then reaper.SetMediaItemInfo_Value(it, "I_CUSTOMCOLOR", color_to_native(p.color)) end
    if p.clear_color then reaper.SetMediaItemInfo_Value(it, "I_CUSTOMCOLOR", 0) end
    if p.volume_db ~= nil then reaper.SetMediaItemInfo_Value(it, "D_VOL", db_to_gain(p.volume_db)) end
    if p.fade_in ~= nil then reaper.SetMediaItemInfo_Value(it, "D_FADEINLEN", p.fade_in) end
    if p.fade_out ~= nil then reaper.SetMediaItemInfo_Value(it, "D_FADEOUTLEN", p.fade_out) end
    if p.fade_in_shape ~= nil then reaper.SetMediaItemInfo_Value(it, "C_FADEINSHAPE", p.fade_in_shape) end
    if p.fade_out_shape ~= nil then reaper.SetMediaItemInfo_Value(it, "C_FADEOUTSHAPE", p.fade_out_shape) end
    if p.snap_offset ~= nil then reaper.SetMediaItemInfo_Value(it, "D_SNAPOFFSET", p.snap_offset) end
    if p.loop_source ~= nil then reaper.SetMediaItemInfo_Value(it, "B_LOOPSRC", p.loop_source and 1 or 0) end
    if p.notes ~= nil then reaper.GetSetMediaItemInfo_String(it, "P_NOTES", p.notes, true) end
    if p.active_take ~= nil then
        local tk = reaper.GetTake(it, p.active_take)
        if not tk then fail("item has no take %d", p.active_take) end
        reaper.SetActiveTake(tk)
    end
    if p.name ~= nil then
        local tk = reaper.GetActiveTake(it)
        if not tk then fail("item has no take to name") end
        reaper.GetSetMediaItemTakeInfo_String(tk, "P_NAME", p.name, true)
    end
    reaper.UpdateItemInProject(it)
end

H.item_set = function(p)
    local it = get_item(p.item)
    return undoable("set item", function() apply_item_props(it, p); return item_summary(it) end)
end

local function item_track(ref)
    local tr = get_track(ref)
    if tr == reaper.GetMasterTrack(0) then fail("items can't be on the master track") end
    return tr
end

H.item_create_midi = function(p)
    local tr = item_track(p.track)
    local s = check_time(p.start, "start")
    local e = p["end"] or (p.length and s + p.length)
    if not e or e <= s then fail("give end (> start) or length (> 0)") end
    return undoable("create MIDI item", function()
        local it = reaper.CreateNewMIDIItemInProj(tr, s, e, false)
        if not it then fail("REAPER could not create the MIDI item") end
        if p.name then reaper.GetSetMediaItemTakeInfo_String(reaper.GetActiveTake(it), "P_NAME", p.name, true) end
        return item_summary(it)
    end)
end

H.item_insert_media = function(p)
    local tr = item_track(p.track)
    local pos = check_time(opt(p.position, 0), "position")
    if type(p.path) ~= "string" or p.path == "" then fail("path is required") end
    if not reaper.file_exists(p.path) then fail("file not found on the REAPER machine: %s", p.path) end
    return undoable("insert media", function()
        local src = reaper.PCM_Source_CreateFromFile(p.path)
        if not src then fail("REAPER can't read %s", p.path) end
        local len, is_qn = reaper.GetMediaSourceLength(src)
        if is_qn then len = reaper.TimeMap_QNToTime(len) end
        local it = reaper.AddMediaItemToTrack(tr)
        local tk = reaper.AddTakeToMediaItem(it)
        reaper.SetMediaItemTake_Source(tk, src)
        reaper.GetSetMediaItemTakeInfo_String(tk, "P_NAME", p.path:match("([^/\\]+)$"), true)
        reaper.SetMediaItemInfo_Value(it, "D_POSITION", pos)
        reaper.SetMediaItemInfo_Value(it, "D_LENGTH", p.length or len)
        reaper.UpdateItemInProject(it)
        reaper.Main_OnCommand(40047, 0)     -- Peaks: Build any missing peaks
        return item_summary(it)
    end)
end

H.item_delete = function(p)
    local it = get_item(p.item)
    undoable("delete item", function() reaper.DeleteTrackMediaItem(reaper.GetMediaItem_Track(it), it) end)
    return {item_count = reaper.CountMediaItems(0)}
end

H.item_split = function(p)
    local it = get_item(p.item)
    local t = check_time(p.position, "position")
    local pos, len = IV(it, "D_POSITION"), IV(it, "D_LENGTH")
    if t <= pos or t >= pos + len then fail("position must be inside the item (%.3f-%.3f)", pos, pos + len) end
    return undoable("split item", function()
        local right = reaper.SplitMediaItem(it, t)
        if not right then fail("REAPER could not split the item") end
        return {left = item_summary(it), right = item_summary(right)}
    end)
end

-- selection helpers for the few operations that only exist as actions
local function save_item_selection()
    local sel = {}
    for i = 0, reaper.CountSelectedMediaItems(0) - 1 do sel[#sel + 1] = reaper.GetSelectedMediaItem(0, i) end
    return sel
end
local function select_only_items(items)
    reaper.SelectAllMediaItems(0, false)
    for _, it in ipairs(items) do reaper.SetMediaItemSelected(it, true) end
end
local function restore_item_selection(sel)
    reaper.SelectAllMediaItems(0, false)
    for _, it in ipairs(sel) do
        if reaper.ValidatePtr2(0, it, "MediaItem*") then reaper.SetMediaItemSelected(it, true) end
    end
end

H.item_duplicate = function(p)
    local it = get_item(p.item)
    return undoable("duplicate item", function()
        local sel = save_item_selection()
        select_only_items({it})
        reaper.Main_OnCommand(41295, 0)    -- Item: Duplicate items (copy placed right after)
        local copy = reaper.GetSelectedMediaItem(0, 0)
        if not copy or copy == it then restore_item_selection(sel); fail("REAPER did not duplicate the item") end
        apply_item_props(copy, {position = p.position, track = p.track})
        restore_item_selection(sel)
        return item_summary(copy)
    end)
end

H.item_glue = function(p)
    local items = {}
    for i = 1, array_len(p.items or json_array({}, 0)) do items[#items + 1] = get_item(p.items[i]) end
    if #items == 0 then fail("items is required") end
    return undoable("glue items", function()
        local sel = save_item_selection()
        select_only_items(items)
        reaper.Main_OnCommand(41588, 0)    -- Item: Glue items
        local out = {}
        for i = 0, reaper.CountSelectedMediaItems(0) - 1 do out[#out + 1] = item_summary(reaper.GetSelectedMediaItem(0, i)) end
        restore_item_selection(sel)
        return {items = list(out)}
    end)
end

H.item_select = function(p)
    if not p.add then reaper.SelectAllMediaItems(0, false) end
    for i = 1, array_len(p.items or json_array({}, 0)) do reaper.SetMediaItemSelected(get_item(p.items[i]), true) end
    reaper.UpdateArrange()
    local sel = {}
    for i = 0, reaper.CountSelectedMediaItems(0) - 1 do sel[#sel + 1] = item_index(reaper.GetSelectedMediaItem(0, i)) end
    return {selected = list(sel)}
end

H.item_chunk_get = function(p)
    local _, chunk = reaper.GetItemStateChunk(get_item(p.item), "", false)
    return {chunk = chunk}
end

H.item_chunk_set = function(p)
    local it = get_item(p.item)
    if type(p.chunk) ~= "string" or not p.chunk:match("^<ITEM") then fail("chunk must start with <ITEM") end
    local ok = undoable("set item chunk", function() return reaper.SetItemStateChunk(it, p.chunk, false) end)
    if not ok then fail("REAPER rejected the chunk") end
    return item_summary(it)
end

-- takes

H.take_set = function(p)
    local it = get_item(p.item)
    local tk = get_take(it, p.take)
    return undoable("set take", function()
        if p.name ~= nil then reaper.GetSetMediaItemTakeInfo_String(tk, "P_NAME", p.name, true) end
        if p.volume_db ~= nil then
            local sign = TV(tk, "D_VOL") < 0 and -1 or 1
            reaper.SetMediaItemTakeInfo_Value(tk, "D_VOL", sign * db_to_gain(p.volume_db))
        end
        if p.pan ~= nil then reaper.SetMediaItemTakeInfo_Value(tk, "D_PAN", p.pan) end
        if p.pitch ~= nil then reaper.SetMediaItemTakeInfo_Value(tk, "D_PITCH", p.pitch) end
        if p.playrate ~= nil then
            if p.playrate <= 0 then fail("playrate must be > 0") end
            reaper.SetMediaItemTakeInfo_Value(tk, "D_PLAYRATE", p.playrate)
        end
        if p.preserve_pitch ~= nil then reaper.SetMediaItemTakeInfo_Value(tk, "B_PPITCH", p.preserve_pitch and 1 or 0) end
        if p.start_offset ~= nil then reaper.SetMediaItemTakeInfo_Value(tk, "D_STARTOFFS", p.start_offset) end
        if p.color ~= nil then reaper.SetMediaItemTakeInfo_Value(tk, "I_CUSTOMCOLOR", color_to_native(p.color)) end
        if p.active then reaper.SetActiveTake(tk) end
        reaper.UpdateItemInProject(it)
        return take_info(tk)
    end)
end

H.take_add = function(p)
    local it = get_item(p.item)
    if p.path and not reaper.file_exists(p.path) then fail("file not found on the REAPER machine: %s", p.path) end
    return undoable("add take", function()
        local tk = reaper.AddTakeToMediaItem(it)
        if p.path then
            local src = reaper.PCM_Source_CreateFromFile(p.path)
            if not src then fail("REAPER can't read %s", p.path) end
            reaper.SetMediaItemTake_Source(tk, src)
            reaper.GetSetMediaItemTakeInfo_String(tk, "P_NAME", p.path:match("([^/\\]+)$"), true)
        end
        if p.name then reaper.GetSetMediaItemTakeInfo_String(tk, "P_NAME", p.name, true) end
        if opt(p.active, true) then reaper.SetActiveTake(tk) end
        reaper.UpdateItemInProject(it)
        return take_info(tk)
    end)
end

H.take_delete = function(p)
    local it = get_item(p.item)
    local tk = get_take(it, p.take)
    if reaper.CountTakes(it) < 2 then fail("item has only one take - delete the item instead") end
    return undoable("delete take", function()
        local sel = save_item_selection()
        local prev_active = reaper.GetActiveTake(it)
        select_only_items({it})
        reaper.SetActiveTake(tk)
        reaper.Main_OnCommand(40129, 0)    -- Take: Delete active take from items
        if prev_active ~= tk and reaper.ValidatePtr2(0, prev_active, "MediaItem_Take*") then
            reaper.SetActiveTake(prev_active)
        end
        restore_item_selection(sel)
        return item_summary(it)
    end)
end
