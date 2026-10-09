-- Transport and edit cursor

local function state()
    local ps = reaper.GetPlayState()
    local playing = ps & 1 ~= 0
    return {
        playing = playing, paused = ps & 2 ~= 0, recording = ps & 4 ~= 0,
        position = (playing or ps & 2 ~= 0) and reaper.GetPlayPosition() or reaper.GetCursorPosition(),
        cursor = reaper.GetCursorPosition(),
        repeat_enabled = reaper.GetSetRepeat(-1) == 1,
    }
end

H.transport_state = function(p) return state() end
H.transport_play = function(p) reaper.OnPlayButton(); return state() end
H.transport_stop = function(p) reaper.OnStopButton(); return state() end
H.transport_pause = function(p) reaper.OnPauseButton(); return state() end
H.transport_record = function(p) reaper.Main_OnCommand(1013, 0); return state() end  -- Transport: Record

H.transport_set_cursor = function(p)
    reaper.SetEditCurPos(check_time(p.position, "position"), opt(p.move_view, true), opt(p.seek_play, true))
    return state()
end

H.transport_set_repeat = function(p)
    reaper.GetSetRepeat(p.enabled and 1 or 0)
    return state()
end
