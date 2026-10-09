-- FX on tracks (incl. input/record FX) and takes.
-- Target: {track} | {track, input_fx=true} | {item, take}

local function target(p)
    if p.item ~= nil then
        local item = get_item(p.item)
        local tk = get_take(item, p.take)
        return {kind = "take", obj = tk, item = item,
            count = function() return reaper.TakeFX_GetCount(tk) end, idx = function(i) return i end,
            api = function(name, ...) return reaper["TakeFX_" .. name](tk, ...) end}
    end
    local tr = get_track(p.track)
    if p.input_fx then
        return {kind = "input", obj = tr,
            count = function() return reaper.TrackFX_GetRecCount(tr) end,
            idx = function(i) return i | 0x1000000 end,
            api = function(name, ...) return reaper["TrackFX_" .. name](tr, ...) end}
    end
    return {kind = "track", obj = tr,
        count = function() return reaper.TrackFX_GetCount(tr) end, idx = function(i) return i end,
        api = function(name, ...) return reaper["TrackFX_" .. name](tr, ...) end}
end

local function fx_index(T, i)
    local n = T.count()
    if type(i) ~= "number" or i < 0 or i >= n then fail("no FX %s (chain has %d)", tostring(i), n) end
    return T.idx(i)
end

local function fx_info(T, i)
    local fi = T.idx(i)
    local _, name = T.api("GetFXName", fi, "")
    local _, preset = T.api("GetPreset", fi, "")
    local pidx, pcount = T.api("GetPresetIndex", fi)
    return {index = i, name = name, guid = T.api("GetFXGUID", fi),
            enabled = T.api("GetEnabled", fi), offline = T.api("GetOffline", fi),
            preset = preset ~= "" and preset or NULL, preset_index = pidx >= 0 and pidx or NULL,
            preset_count = pcount, params = T.api("GetNumParams", fi), open = T.api("GetOpen", fi)}
end

H.fx_list = function(p)
    local T = target(p)
    local out = {}
    for i = 0, T.count() - 1 do out[#out + 1] = fx_info(T, i) end
    return {fx = list(out)}
end

H.fx_installed = function(p)
    local f = p.filter and p.filter:lower()
    local out, i = {}, 0
    while true do
        local ok, name, ident = reaper.EnumInstalledFX(i)
        if not ok then break end
        if not f or name:lower():find(f, 1, true) then out[#out + 1] = {name = name, ident = ident} end
        i = i + 1
        if #out >= opt(p.limit, 200) then break end
    end
    return {plugins = list(out), total_scanned = i}
end

H.fx_add = function(p)
    local T = target(p)
    if type(p.name) ~= "string" or p.name == "" then fail("name is required (see fx_installed)") end
    local n = T.count()
    local pos = opt(p.position, n)
    if pos < 0 or pos > n then fail("position must be 0..%d", n) end
    return undoable("add FX", function()
        local idx
        if T.kind == "take" then idx = reaper.TakeFX_AddByName(T.obj, p.name, -1000 - pos)
        else idx = reaper.TrackFX_AddByName(T.obj, p.name, T.kind == "input", -1000 - pos) end
        if idx < 0 then fail("plugin not found: '%s' (see fx_installed)", p.name) end
        return fx_info(T, idx & 0xFFFFFF)
    end)
end

H.fx_delete = function(p)
    local T = target(p)
    local fi = fx_index(T, p.fx)
    undoable("delete FX", function() T.api("Delete", fi) end)
    return {fx_count = T.count()}
end

H.fx_move = function(p)
    local T = target(p)
    local fi = fx_index(T, p.fx)
    return undoable("move FX", function()
        if p.to_track ~= nil then
            if T.kind == "take" then fail("moving take FX to a track is not supported") end
            local dest = get_track(p.to_track)
            local di = opt(p.to_index, reaper.TrackFX_GetCount(dest))
            reaper.TrackFX_CopyToTrack(T.obj, fi, dest, di, true)
            return {moved_to_track = track_index(dest), index = di}
        end
        local n = T.count()
        local to = p.to_index
        if type(to) ~= "number" or to < 0 or to >= n then fail("to_index must be 0..%d", n - 1) end
        if T.kind == "take" then reaper.TakeFX_CopyToTake(T.obj, fi, T.obj, to, true)
        else reaper.TrackFX_CopyToTrack(T.obj, fi, T.obj, T.idx(to), true) end
        return fx_info(T, to)
    end)
end

H.fx_set = function(p)
    local T = target(p)
    local fi = fx_index(T, p.fx)
    return undoable("set FX", function()
        if p.enabled ~= nil then T.api("SetEnabled", fi, p.enabled) end
        if p.offline ~= nil then T.api("SetOffline", fi, p.offline) end
        if p.wet ~= nil then
            local wi = T.api("GetParamFromIdent", fi, ":wet")
            if wi < 0 then fail("this FX has no wet/dry control") end
            T.api("SetParamNormalized", fi, wi, p.wet)
        end
        return fx_info(T, p.fx)
    end)
end

local function param_record(T, fi, j)
    local _, pname = T.api("GetParamName", fi, j, "")
    local val, minv, maxv = T.api("GetParam", fi, j)
    local _, fmt = T.api("GetFormattedParamValue", fi, j, "")
    return {index = j, name = pname, value = val, min = minv, max = maxv,
            normalized = T.api("GetParamNormalized", fi, j), formatted = fmt}
end

H.fx_params = function(p)
    local T = target(p)
    local fi = fx_index(T, p.fx)
    local f = p.filter and p.filter:lower()
    local out = {}
    for j = 0, T.api("GetNumParams", fi) - 1 do
        local _, pname = T.api("GetParamName", fi, j, "")
        if not f or pname:lower():find(f, 1, true) then out[#out + 1] = param_record(T, fi, j) end
    end
    local _, name = T.api("GetFXName", fi, "")
    return {fx = p.fx, name = name, params = list(out)}
end

local function find_param(T, fi, ref)
    local n = T.api("GetNumParams", fi)
    if type(ref) == "number" then
        if ref < 0 or ref >= n then fail("no parameter %d (FX has %d)", ref, n) end
        return ref
    end
    local lref, partial = tostring(ref):lower(), {}
    for j = 0, n - 1 do
        local _, pname = T.api("GetParamName", fi, j, "")
        if pname == ref then return j end
        if pname:lower():find(lref, 1, true) then partial[#partial + 1] = j end
    end
    if #partial == 1 then return partial[1] end
    if #partial == 0 then fail("no parameter named '%s'", tostring(ref)) end
    fail("parameter name '%s' is ambiguous (%d matches) - use the index", tostring(ref), #partial)
end

H.fx_param_set = function(p)
    local T = target(p)
    local fi = fx_index(T, p.fx)
    local ps = p.params or json_array({}, 0)
    if array_len(ps) == 0 then fail("params is required") end
    return undoable("set FX parameters", function()
        local out = {}
        for i = 1, array_len(ps) do
            local q = ps[i]
            local j = find_param(T, fi, q.param)
            if q.normalized ~= nil then
                if q.normalized < 0 or q.normalized > 1 then fail("normalized must be 0..1") end
                T.api("SetParamNormalized", fi, j, q.normalized)
            elseif q.value ~= nil then T.api("SetParam", fi, j, q.value)
            else fail("param %s: give value or normalized", tostring(q.param)) end
            out[#out + 1] = param_record(T, fi, j)
        end
        return {params = list(out)}
    end)
end

H.fx_presets = function(p)
    local T = target(p)
    local fi = fx_index(T, p.fx)
    local _, preset = T.api("GetPreset", fi, "")
    local pidx, count = T.api("GetPresetIndex", fi)
    return {preset = preset ~= "" and preset or NULL, index = pidx >= 0 and pidx or NULL, count = count}
end

H.fx_preset_set = function(p)
    local T = target(p)
    local fi = fx_index(T, p.fx)
    return undoable("set FX preset", function()
        if p.name ~= nil then
            if not T.api("SetPreset", fi, p.name) then fail("preset '%s' not found", p.name) end
        elseif p.index ~= nil then
            if not T.api("SetPresetByIndex", fi, p.index) then fail("no preset %d", p.index) end
        elseif p.step ~= nil then
            T.api("NavigatePresets", fi, p.step)
        else fail("give name, index or step") end
        return H.fx_presets(p)
    end)
end

H.fx_show = function(p)
    local T = target(p)
    local fi = fx_index(T, p.fx)
    local modes = {floating = 3, chain = 1, close_floating = 2, close_chain = 0}
    local m = modes[opt(p.mode, "floating")] or fail("mode must be floating, chain, close_floating or close_chain")
    T.api("Show", fi, m)
    return {open = T.api("GetOpen", fi)}
end
