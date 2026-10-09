-- Tracks

local function track_name(tr)
    if tr == reaper.GetMasterTrack(0) then return "MASTER" end
    local _, name = reaper.GetTrackName(tr)
    return name
end

local function V(tr, k) return reaper.GetMediaTrackInfo_Value(tr, k) end

local function track_summary(tr)
    return {
        index = track_index(tr),
        name = track_name(tr),
        guid = reaper.GetTrackGUID(tr),
        folder_depth = math.tointeger(V(tr, "I_FOLDERDEPTH")),
        volume_db = db_out(V(tr, "D_VOL")),
        pan = V(tr, "D_PAN"),
        mute = V(tr, "B_MUTE") == 1,
        solo = V(tr, "I_SOLO") ~= 0,
        arm = V(tr, "I_RECARM") == 1,
        auto_arm = V(tr, "B_AUTO_RECARM") == 1,
        selected = V(tr, "I_SELECTED") == 1,
        color = color_from_native(math.tointeger(V(tr, "I_CUSTOMCOLOR"))),
        fx_count = reaper.TrackFX_GetCount(tr),
        item_count = reaper.CountTrackMediaItems(tr),
    }
end

H.track_list = function(p)
    local out = {}
    for i = 0, reaper.CountTracks(0) - 1 do out[#out + 1] = track_summary(reaper.GetTrack(0, i)) end
    local m = reaper.GetMasterTrack(0)
    return {tracks = list(out), master = {volume_db = db_out(V(m, "D_VOL")), pan = V(m, "D_PAN"),
            mute = V(m, "B_MUTE") == 1, fx_count = reaper.TrackFX_GetCount(m)}}
end

H.track_get = function(p)
    local tr = get_track(p.track)
    local t = track_summary(tr)
    t.width = V(tr, "D_WIDTH")
    t.phase_inverted = V(tr, "B_PHASE") == 1
    t.input = math.tointeger(V(tr, "I_RECINPUT"))
    t.monitor = math.tointeger(V(tr, "I_RECMON"))
    t.record_mode = math.tointeger(V(tr, "I_RECMODE"))
    t.main_send = V(tr, "B_MAINSEND") == 1
    t.height = math.tointeger(V(tr, "I_TCPH"))
    t.sends = reaper.GetTrackNumSends(tr, 0)
    t.receives = reaper.GetTrackNumSends(tr, -1)
    t.hw_outputs = reaper.GetTrackNumSends(tr, 1)
    local fx = {}
    for i = 0, reaper.TrackFX_GetCount(tr) - 1 do
        local _, name = reaper.TrackFX_GetFXName(tr, i, "")
        fx[#fx + 1] = {index = i, name = name, enabled = reaper.TrackFX_GetEnabled(tr, i)}
    end
    t.fx = list(fx)
    local items = {}
    for i = 0, reaper.CountTrackMediaItems(tr) - 1 do
        local it = reaper.GetTrackMediaItem(tr, i)
        local take = reaper.GetActiveTake(it)
        items[#items + 1] = {index = item_index(it),
            position = reaper.GetMediaItemInfo_Value(it, "D_POSITION"),
            length = reaper.GetMediaItemInfo_Value(it, "D_LENGTH"),
            name = take and reaper.GetTakeName(take) or "",
            midi = take ~= nil and reaper.TakeIsMIDI(take)}
    end
    t.items = list(items)
    local env = {}
    for i = 0, reaper.CountTrackEnvelopes(tr) - 1 do
        local _, name = reaper.GetEnvelopeName(reaper.GetTrackEnvelope(tr, i))
        env[#env + 1] = name
    end
    t.envelopes = list(env)
    return t
end

-- apply optional properties; shared by create and set
local function apply_props(tr, p)
    if p.name ~= nil then reaper.GetSetMediaTrackInfo_String(tr, "P_NAME", p.name, true) end
    if p.volume_db ~= nil then reaper.SetMediaTrackInfo_Value(tr, "D_VOL", db_to_gain(p.volume_db)) end
    if p.pan ~= nil then
        if p.pan < -1 or p.pan > 1 then fail("pan must be -1..1") end
        reaper.SetMediaTrackInfo_Value(tr, "D_PAN", p.pan)
    end
    if p.width ~= nil then reaper.SetMediaTrackInfo_Value(tr, "D_WIDTH", p.width) end
    if p.mute ~= nil then reaper.SetMediaTrackInfo_Value(tr, "B_MUTE", p.mute and 1 or 0) end
    if p.solo ~= nil then reaper.SetMediaTrackInfo_Value(tr, "I_SOLO", p.solo and 2 or 0) end
    -- auto_arm=false must apply before arming, auto_arm=true after (dis)arming
    if p.auto_arm == false then reaper.SetMediaTrackInfo_Value(tr, "B_AUTO_RECARM", 0) end
    if p.arm ~= nil then
        -- with "automatic record-arm when selected" the arm state follows selection and a
        -- direct arm is silently overridden
        if V(tr, "B_AUTO_RECARM") == 1 then
            fail("track has automatic record-arm (follows selection): select it with track_select, or pass auto_arm=false")
        end
        reaper.SetMediaTrackInfo_Value(tr, "I_RECARM", p.arm and 1 or 0)
    end
    if p.auto_arm == true then reaper.SetMediaTrackInfo_Value(tr, "B_AUTO_RECARM", 1) end
    if p.phase_inverted ~= nil then reaper.SetMediaTrackInfo_Value(tr, "B_PHASE", p.phase_inverted and 1 or 0) end
    if p.color ~= nil then reaper.SetMediaTrackInfo_Value(tr, "I_CUSTOMCOLOR", color_to_native(p.color)) end
    if p.clear_color then reaper.SetMediaTrackInfo_Value(tr, "I_CUSTOMCOLOR", 0) end
    if p.input ~= nil then reaper.SetMediaTrackInfo_Value(tr, "I_RECINPUT", p.input) end
    if p.monitor ~= nil then reaper.SetMediaTrackInfo_Value(tr, "I_RECMON", p.monitor) end
    if p.record_mode ~= nil then reaper.SetMediaTrackInfo_Value(tr, "I_RECMODE", p.record_mode) end
    if p.folder_depth ~= nil then reaper.SetMediaTrackInfo_Value(tr, "I_FOLDERDEPTH", p.folder_depth) end
    if p.main_send ~= nil then reaper.SetMediaTrackInfo_Value(tr, "B_MAINSEND", p.main_send and 1 or 0) end
    if p.selected ~= nil then reaper.SetMediaTrackInfo_Value(tr, "I_SELECTED", p.selected and 1 or 0) end
    if p.height ~= nil then
        reaper.SetMediaTrackInfo_Value(tr, "I_HEIGHTOVERRIDE", p.height)
        reaper.TrackList_AdjustWindows(false)
    end
end

H.track_create = function(p)
    local n = reaper.CountTracks(0)
    local idx = opt(p.index, n)
    if idx < 0 or idx > n then fail("index must be 0..%d", n) end
    return undoable("create track", function()
        reaper.InsertTrackAtIndex(idx, true)
        local tr = reaper.GetTrack(0, idx)
        apply_props(tr, p)
        return track_summary(tr)
    end)
end

H.track_set = function(p)
    local tr = get_track(p.track)
    return undoable("set track", function()
        apply_props(tr, p)
        return track_summary(tr)
    end)
end

H.track_delete = function(p)
    local tr = get_track(p.track)
    if tr == reaper.GetMasterTrack(0) then fail("the master track can't be deleted") end
    local name = track_name(tr)
    undoable("delete track", function() reaper.DeleteTrack(tr) end)
    return {deleted = name, track_count = reaper.CountTracks(0)}
end

-- remember/restore track selection around operations that need it
local function save_track_selection()
    local sel = {}
    for i = 0, reaper.CountSelectedTracks(0) - 1 do sel[#sel + 1] = reaper.GetSelectedTrack(0, i) end
    return sel
end
local function restore_track_selection(sel)
    for i = 0, reaper.CountTracks(0) - 1 do reaper.SetTrackSelected(reaper.GetTrack(0, i), false) end
    for _, tr in ipairs(sel) do
        if reaper.ValidatePtr2(0, tr, "MediaTrack*") then reaper.SetTrackSelected(tr, true) end
    end
end

H.track_move = function(p)
    local tr = get_track(p.track)
    local n = reaper.CountTracks(0)
    local to = p.to_index
    if type(to) ~= "number" or to < 0 or to >= n then fail("to_index must be 0..%d", n - 1) end
    local from = track_index(tr)
    return undoable("move track", function()
        local sel = save_track_selection()
        reaper.SetOnlyTrackSelected(tr)
        -- ReorderSelectedTracks inserts before the given index (counted before removal)
        local before = to > from and to + 1 or to
        reaper.ReorderSelectedTracks(before, 0)
        restore_track_selection(sel)
        return track_summary(tr)
    end)
end

H.track_duplicate = function(p)
    local tr = get_track(p.track)
    if tr == reaper.GetMasterTrack(0) then fail("the master track can't be duplicated") end
    return undoable("duplicate track", function()
        local sel = save_track_selection()
        reaper.SetOnlyTrackSelected(tr)
        reaper.Main_OnCommand(40062, 0)            -- Track: Duplicate tracks
        local copy = reaper.GetTrack(0, track_index(tr) + 1)
        restore_track_selection(sel)
        return track_summary(copy)
    end)
end

H.track_select = function(p)
    local tracks = p.tracks or json_array({}, 0)
    if not p.add then
        for i = 0, reaper.CountTracks(0) - 1 do reaper.SetTrackSelected(reaper.GetTrack(0, i), false) end
    end
    for i = 1, array_len(tracks) do reaper.SetTrackSelected(get_track(tracks[i]), true) end
    local sel = {}
    for i = 0, reaper.CountSelectedTracks(0) - 1 do sel[#sel + 1] = track_index(reaper.GetSelectedTrack(0, i)) end
    return {selected = list(sel)}
end

H.track_chunk_get = function(p)
    local _, chunk = reaper.GetTrackStateChunk(get_track(p.track), "", false)
    return {chunk = chunk}
end

H.track_chunk_set = function(p)
    local tr = get_track(p.track)
    if type(p.chunk) ~= "string" or not p.chunk:match("^<TRACK") then fail("chunk must start with <TRACK") end
    local ok = undoable("set track chunk", function() return reaper.SetTrackStateChunk(tr, p.chunk, false) end)
    if not ok then fail("REAPER rejected the chunk") end
    return {ok = true}
end
