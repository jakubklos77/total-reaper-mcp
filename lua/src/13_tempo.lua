-- Tempo and time signature

local function marker(i)
    local _, t, measure, beat, bpm, num, den, lin = reaper.GetTempoTimeSigMarker(0, i)
    local m = {index = i, time = t, measure = measure + 1, beat = beat + 1, bpm = bpm,
               linear = lin, qn = reaper.TimeMap2_timeToQN(0, t)}
    if num > 0 then m.time_signature = string.format("%d/%d", num, den) end
    return m
end

H.tempo_map_get = function(p)
    local out = {}
    for i = 0, reaper.CountTempoTimeSigMarkers(0) - 1 do out[#out + 1] = marker(i) end
    local num, den, bpm = reaper.TimeMap_GetTimeSigAtTime(0, 0)
    return {markers = list(out), project_bpm = reaper.Master_GetTempo(), start_bpm = bpm,
            start_time_signature = string.format("%d/%d", num, den)}
end

-- points: [[time, bpm, num(0=no change), den, linear], ...] or [{time, bpm, num, den, linear}]
H.tempo_map_set = function(p)
    local points = p.points or json_array({}, 0)
    return undoable("set tempo map", function()
        if opt(p.clear, true) then
            for i = reaper.CountTempoTimeSigMarkers(0) - 1, 0, -1 do reaper.DeleteTempoTimeSigMarker(0, i) end
        end
        if p.base_bpm then reaper.SetCurrentBPM(0, p.base_bpm, false) end
        local n, added = array_len(points), 0
        for i = 1, n do
            local q = points[i]
            local t, bpm, num, den, lin
            if q.time ~= nil then t, bpm, num, den, lin = q.time, q.bpm, q.num, q.den, q.linear
            else t, bpm, num, den, lin = q[1], q[2], q[3], q[4], q[5] end
            if reaper.SetTempoTimeSigMarker(0, -1, t, -1, -1, bpm, num or 0, den or 0, lin and true or false) then
                added = added + 1
            end
        end
        reaper.UpdateTimeline()
        if added ~= n then fail("REAPER accepted %d of %d tempo points", added, n) end
        return {markers = added}
    end)
end

H.tempo_marker_add = function(p)
    local t = check_time(p.time, "time")
    if not p.bpm then fail("bpm is required") end
    return undoable("add tempo marker", function()
        if not reaper.SetTempoTimeSigMarker(0, -1, t, -1, -1, p.bpm, p.num or 0, p.den or 0, p.linear and true or false) then
            fail("REAPER rejected the tempo marker")
        end
        reaper.UpdateTimeline()
        local i = reaper.FindTempoTimeSigMarker(0, t + 1e-9)
        return marker(i)
    end)
end

H.tempo_marker_set = function(p)
    local i = p.index
    if type(i) ~= "number" or i < 0 or i >= reaper.CountTempoTimeSigMarkers(0) then fail("no tempo marker %s", tostring(i)) end
    local _, t, measure, beat, bpm, num, den, lin = reaper.GetTempoTimeSigMarker(0, i)
    return undoable("edit tempo marker", function()
        reaper.SetTempoTimeSigMarker(0, i, opt(p.time, t), -1, -1, opt(p.bpm, bpm),
            opt(p.num, num), opt(p.den, den), opt(p.linear, lin))
        reaper.UpdateTimeline()
        return marker(reaper.FindTempoTimeSigMarker(0, opt(p.time, t) + 1e-9))
    end)
end

H.tempo_marker_delete = function(p)
    local i = p.index
    if type(i) ~= "number" or i < 0 or i >= reaper.CountTempoTimeSigMarkers(0) then fail("no tempo marker %s", tostring(i)) end
    undoable("delete tempo marker", function() reaper.DeleteTempoTimeSigMarker(0, i); reaper.UpdateTimeline() end)
    return {markers = reaper.CountTempoTimeSigMarkers(0)}
end

-- project tempo without markers (with markers present, edit them via tempo_marker_set)
H.tempo_set = function(p)
    if not p.bpm or p.bpm < 1 or p.bpm > 960 then fail("bpm must be 1..960") end
    if reaper.CountTempoTimeSigMarkers(0) > 0 then
        fail("project has tempo markers - use tempo_marker_set / tempo_map_set instead")
    end
    reaper.SetCurrentBPM(0, p.bpm, true)
    reaper.UpdateTimeline()
    return {bpm = reaper.Master_GetTempo()}
end
