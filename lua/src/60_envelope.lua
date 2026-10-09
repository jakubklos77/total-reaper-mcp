-- Envelopes: track envelopes by name, FX parameter envelopes, take envelopes.
-- Target: {track, name} | {track, fx, param} | {item, take, name}

local BUILTIN = {   -- track envelope name -> action that shows it (verified by name before running)
    ["Volume"] = {40406, "volume envelope"}, ["Pan"] = {40407, "pan envelope"},
    ["Volume (Pre-FX)"] = {40408, "pre-fx volume envelope"}, ["Mute"] = {40867, "mute envelope"},
    ["Width"] = {41870, "width envelope"}, ["Trim Volume"] = {42020, "trim volume envelope"},
}

local function env_target(p, create)
    if p.item ~= nil then
        local tk = get_take(get_item(p.item), p.take)
        local env = reaper.GetTakeEnvelopeByName(tk, p.name or fail("name is required (Volume, Pan, Mute, Pitch)"))
        if not env then fail("take has no '%s' envelope (show it in REAPER first)", p.name) end
        return env
    end
    local tr = get_track(p.track)
    if p.fx ~= nil then
        local param = p.param
        if type(param) ~= "number" then fail("param (index) is required for FX envelopes") end
        local env = reaper.GetFXEnvelope(tr, p.fx, param, create and true or false)
        if not env then fail("no envelope for FX %d parameter %d", p.fx, param) end
        return env
    end
    local name = p.name or fail("name is required (e.g. Volume, Pan, Width, Mute)")
    local env = reaper.GetTrackEnvelopeByName(tr, name)
    if not env and create then
        local b = BUILTIN[name] or fail("'%s' can't be created automatically (built-in: Volume, Pan, Width, Mute, Volume (Pre-FX), Trim Volume)", name)
        local sel = {}
        for i = 0, reaper.CountSelectedTracks(0) - 1 do sel[#sel + 1] = reaper.GetSelectedTrack(0, i) end
        reaper.SetOnlyTrackSelected(tr)
        RUN_CHECKED_ACTION(b[1], b[2])
        for i = 0, reaper.CountTracks(0) - 1 do reaper.SetTrackSelected(reaper.GetTrack(0, i), false) end
        for _, t in ipairs(sel) do reaper.SetTrackSelected(t, true) end
        env = reaper.GetTrackEnvelopeByName(tr, name)
    end
    if not env then fail("track has no '%s' envelope (create=true makes it)", name) end
    return env
end

local function env_flags(env)
    local _, chunk = reaper.GetEnvelopeStateChunk(env, "", false)
    return {active = (chunk:match("\nACT (%d)") or "1") == "1",
            visible = (chunk:match("\nVIS (%d)") or "0") == "1",
            armed = (chunk:match("\nARM (%d)") or "0") == "1"}
end

local function env_summary(env)
    local _, name = reaper.GetEnvelopeName(env)
    local f = env_flags(env)
    return {name = name, points = reaper.CountEnvelopePoints(env), active = f.active, visible = f.visible,
            armed = f.armed, scaling_mode = reaper.GetEnvelopeScalingMode(env)}
end

H.envelope_list = function(p)
    local out = {}
    if p.item ~= nil then
        local tk = get_take(get_item(p.item), p.take)
        for i = 0, reaper.CountTakeEnvelopes(tk) - 1 do out[#out + 1] = env_summary(reaper.GetTakeEnvelope(tk, i)) end
    else
        local tr = get_track(p.track)
        for i = 0, reaper.CountTrackEnvelopes(tr) - 1 do
            local env = reaper.GetTrackEnvelope(tr, i)
            local s = env_summary(env)
            local _, fx, param = reaper.Envelope_GetParentTrack(env)
            if fx and fx >= 0 then s.fx, s.param = fx, param end
            out[#out + 1] = s
        end
    end
    return {envelopes = list(out)}
end

-- volume-type envelopes store fader-scaled values; value_db converts
local function is_volume(env)
    local _, name = reaper.GetEnvelopeName(env)
    return name:match("^Volume") or name:match("^Trim Volume")
end
local function raw_to_db(env, v) return db_out(reaper.ScaleFromEnvelopeMode(reaper.GetEnvelopeScalingMode(env), v)) end
local function db_to_raw(env, db) return reaper.ScaleToEnvelopeMode(reaper.GetEnvelopeScalingMode(env), db_to_gain(db)) end

H.envelope_get = function(p)
    local env = env_target(p, false)
    local s = env_summary(env)
    local vol = is_volume(env)
    local pts = {}
    for i = 0, reaper.CountEnvelopePoints(env) - 1 do
        local _, t, v, shape, tension, sel = reaper.GetEnvelopePoint(env, i)
        if (p.start == nil or t >= p.start - 1e-9) and (p["end"] == nil or t <= p["end"] + 1e-9) then
            pts[#pts + 1] = {index = i, time = t, value = v, value_db = vol and raw_to_db(env, v) or NULL,
                             shape = shape, tension = tension, selected = sel}
        end
    end
    s.point_list = list(pts)
    return s
end

-- points: [{time, value | value_db, shape=0, tension=0}]; replace=true deletes existing points
-- between the first and last new point first
H.envelope_points_set = function(p)
    local env = env_target(p, opt(p.create, true))
    local pts = p.points or json_array({}, 0)
    local n = array_len(pts)
    if n == 0 then fail("points is required") end
    return undoable("set envelope points", function()
        local tmin, tmax = math.huge, -math.huge
        for i = 1, n do tmin = math.min(tmin, pts[i].time); tmax = math.max(tmax, pts[i].time) end
        if opt(p.replace, true) then reaper.DeleteEnvelopePointRange(env, tmin - 1e-9, tmax + 1e-9) end
        for i = 1, n do
            local q = pts[i]
            local v = q.value
            if q.value_db ~= nil then
                if not is_volume(env) then fail("value_db only applies to volume envelopes") end
                v = db_to_raw(env, q.value_db)
            end
            if v == nil then fail("point %d: give value or value_db", i) end
            reaper.InsertEnvelopePoint(env, q.time, v, opt(q.shape, 0), opt(q.tension, 0), false, true)
        end
        reaper.Envelope_SortPoints(env)
        return env_summary(env)
    end)
end

H.envelope_points_delete = function(p)
    local env = env_target(p, false)
    local s, e = opt(p.start, -1e9), opt(p["end"], 1e9)
    return undoable("delete envelope points", function()
        local before = reaper.CountEnvelopePoints(env)
        reaper.DeleteEnvelopePointRange(env, s - 1e-9, e + 1e-9)
        return {deleted = before - reaper.CountEnvelopePoints(env), points = reaper.CountEnvelopePoints(env)}
    end)
end

H.envelope_set = function(p)
    local env = env_target(p, opt(p.create, true))
    return undoable("set envelope", function()
        local _, chunk = reaper.GetEnvelopeStateChunk(env, "", false)
        if p.active ~= nil then chunk = chunk:gsub("\nACT %d", "\nACT " .. (p.active and 1 or 0), 1) end
        if p.visible ~= nil then chunk = chunk:gsub("\nVIS %d", "\nVIS " .. (p.visible and 1 or 0), 1) end
        if p.armed ~= nil then chunk = chunk:gsub("\nARM %d", "\nARM " .. (p.armed and 1 or 0), 1) end
        reaper.SetEnvelopeStateChunk(env, chunk, false)
        reaper.TrackList_AdjustWindows(false)
        return env_summary(env)
    end)
end
