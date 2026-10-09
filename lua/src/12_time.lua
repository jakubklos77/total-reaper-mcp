-- Time selection, loop, grid, position conversion

H.time_selection_get = function(p)
    local s, e = reaper.GetSet_LoopTimeRange(false, false, 0, 0, false)
    local ls, le = reaper.GetSet_LoopTimeRange(false, true, 0, 0, false)
    -- "Options: Loop points linked to time selection": when on, setting one sets both
    return {time_selection = {start = s, ["end"] = e}, loop = {start = ls, ["end"] = le},
            linked = reaper.GetToggleCommandState(40621) == 1}
end

H.time_selection_set = function(p)
    local s, e = check_time(p.start, "start"), check_time(p["end"], "end")
    if e < s then fail("end must be >= start") end
    local target = opt(p.target, "time_selection")
    if target ~= "time_selection" and target ~= "loop" and target ~= "both" then
        fail("target must be time_selection, loop or both")
    end
    if target ~= "loop" then reaper.GetSet_LoopTimeRange(true, false, s, e, false) end
    if target ~= "time_selection" then reaper.GetSet_LoopTimeRange(true, true, s, e, false) end
    return H.time_selection_get({})
end

-- Convert a position given as seconds, quarter notes, or measure(+beat) (1-based, as REAPER
-- displays them) into all representations.
H.time_convert = function(p)
    local t
    if p.seconds ~= nil then t = p.seconds
    elseif p.qn ~= nil then t = reaper.TimeMap2_QNToTime(0, p.qn)
    elseif p.measure ~= nil then
        t = reaper.TimeMap2_beatsToTime(0, (p.beat or 1) - 1, p.measure - 1)
    elseif p.text ~= nil then t = reaper.parse_timestr_pos(p.text, -1)
    else fail("give one of seconds, qn, measure(+beat) or text") end
    local beat, measure, cml, fullbeats, cdenom = reaper.TimeMap2_timeToBeats(0, t)
    local num, den, bpm = reaper.TimeMap_GetTimeSigAtTime(0, t)
    return {
        seconds = t, qn = reaper.TimeMap2_timeToQN(0, t),
        measure = math.tointeger(measure) + 1, beat = beat + 1, full_beats = fullbeats,
        time_signature = string.format("%d/%d", num, den), bpm = bpm,
        text_measures = reaper.format_timestr_pos(t, "", 2),
        text_time = reaper.format_timestr_pos(t, "", 0),
    }
end

local function grid_state()
    local _, division, swingmode, swingamt = reaper.GetSetProjectGrid(0, false, 0, 0, 0)
    return {division = division, swing = swingmode == 1, swing_amount = swingamt,
            snap = reaper.GetToggleCommandState(1157) == 1}
end

H.grid_get = function(p) return grid_state() end

-- division in whole notes: 0.25 = quarter, 0.125 = eighth, 1/12 = eighth triplet ...
H.grid_set = function(p)
    local g = grid_state()
    local division = opt(p.division, g.division)
    if division <= 0 then fail("division must be > 0 (fraction of a whole note, e.g. 0.25)") end
    local swing = opt(p.swing, g.swing)
    reaper.GetSetProjectGrid(0, true, division, swing and 1 or 0, opt(p.swing_amount, g.swing_amount))
    if p.snap ~= nil and p.snap ~= g.snap then reaper.Main_OnCommand(1157, 0) end
    return grid_state()
end
