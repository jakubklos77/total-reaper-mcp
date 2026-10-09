-- Rendering and freezing

local BOUNDS = {project = 1, time_selection = 2, custom = 0, all_regions = 3, selected_items = 4}

H.render_project = function(p)
    if reaper.GetPlayState() & 4 ~= 0 then fail("can't render while recording") end
    local function gs(k, v, set) return select(2, reaper.GetSetProjectInfo_String(0, k, v or "", set or false)) end
    local function gn(k, v, set) return reaper.GetSetProjectInfo(0, k, v or 0, set or false) end
    -- remember the project's render settings and put them back afterwards
    local saved = {file = gs("RENDER_FILE"), pattern = gs("RENDER_PATTERN"), format = gs("RENDER_FORMAT"),
                   bounds = gn("RENDER_BOUNDSFLAG"), s = gn("RENDER_STARTPOS"), e = gn("RENDER_ENDPOS"),
                   srate = gn("RENDER_SRATE"), chans = gn("RENDER_CHANNELS"), tail = gn("RENDER_TAILFLAG"),
                   settings = gn("RENDER_SETTINGS")}
    local ok, res = pcall(function()
        if p.directory then gs("RENDER_FILE", p.directory, true) end
        if p.file_name then gs("RENDER_PATTERN", p.file_name, true) end
        if p.bounds then
            local b = BOUNDS[p.bounds] or fail("bounds must be project, time_selection, custom, all_regions or selected_items")
            gn("RENDER_BOUNDSFLAG", b, true)
            if p.bounds == "custom" then
                gn("RENDER_STARTPOS", check_time(p.start, "start"), true)
                gn("RENDER_ENDPOS", check_time(p["end"], "end"), true)
            end
        end
        if p.wav_bits then
            -- REAPER's WAV render config ("evaw" + bit depth), base64-encoded
            local cfg = ({[16] = "ZXZhdxAAAQ==", [24] = "ZXZhdxgAAQ==", [32] = "ZXZhdyAAAQ=="})[p.wav_bits]
            gs("RENDER_FORMAT", cfg or fail("wav_bits must be 16, 24 or 32"), true)
        end
        if p.sample_rate then gn("RENDER_SRATE", p.sample_rate, true) end
        if p.channels then gn("RENDER_CHANNELS", p.channels, true) end
        if p.tail_ms then gn("RENDER_TAILFLAG", 0xFF, true); gn("RENDER_TAILMS", p.tail_ms, true) end
        local targets = gs("RENDER_TARGETS")
        local paths = {}
        for f in (targets .. ";"):gmatch("([^;]+);") do paths[#paths + 1] = f end
        if #paths == 0 then fail("nothing to render (empty bounds?)") end
        -- an existing output file makes REAPER show a modal "overwrite?" dialog, which would block
        -- the bridge: refuse, or delete the old file first when overwrite=true
        for _, f in ipairs(paths) do
            if reaper.file_exists(f) then
                if not p.overwrite then fail("output file exists: %s (pass overwrite=true or another file_name)", f) end
                local ok, err = os.remove(f)
                if not ok then fail("can't overwrite %s: %s", f, tostring(err)) end
            end
        end
        reaper.Main_OnCommand(42230, 0)     -- File: Render project, using the most recent render settings, auto-close render dialog
        local files = {}
        for _, f in ipairs(paths) do files[#files + 1] = {path = f, exists = reaper.file_exists(f)} end
        return {files = list(files)}
    end)
    gs("RENDER_FILE", saved.file, true); gs("RENDER_PATTERN", saved.pattern, true)
    gs("RENDER_FORMAT", saved.format, true); gn("RENDER_BOUNDSFLAG", saved.bounds, true)
    gn("RENDER_STARTPOS", saved.s, true); gn("RENDER_ENDPOS", saved.e, true)
    gn("RENDER_SRATE", saved.srate, true); gn("RENDER_CHANNELS", saved.chans, true)
    gn("RENDER_TAILFLAG", saved.tail, true); gn("RENDER_SETTINGS", saved.settings, true)
    if not ok then error(res, 0) end
    local missing = 0
    for _, f in ipairs(res.files) do if not f.exists then missing = missing + 1 end end
    if #res.files == 0 or missing > 0 then fail("render finished but %d of %d output files are missing", missing, #res.files) end
    return res
end

local FREEZE = {stereo = {41223, "freeze to stereo"}, mono = {40901, "freeze to mono"},
                multichannel = {40877, "freeze to multichannel"}}

local function with_tracks(refs, fn)
    local sel = {}
    for i = 0, reaper.CountSelectedTracks(0) - 1 do sel[#sel + 1] = reaper.GetSelectedTrack(0, i) end
    for i = 0, reaper.CountTracks(0) - 1 do reaper.SetTrackSelected(reaper.GetTrack(0, i), false) end
    local trs = {}
    for i = 1, array_len(refs) do trs[#trs + 1] = get_track(refs[i]); reaper.SetTrackSelected(trs[#trs], true) end
    if #trs == 0 then fail("tracks is required") end
    local ok, err = pcall(fn, trs)
    for i = 0, reaper.CountTracks(0) - 1 do reaper.SetTrackSelected(reaper.GetTrack(0, i), false) end
    for _, t in ipairs(sel) do if reaper.ValidatePtr2(0, t, "MediaTrack*") then reaper.SetTrackSelected(t, true) end end
    if not ok then error(err, 0) end
    return trs
end

local function frozen_count(tr) return reaper.BR_GetMediaTrackFreezeCount and reaper.BR_GetMediaTrackFreezeCount(tr) or nil end

H.track_freeze = function(p)
    local f = FREEZE[opt(p.mode, "stereo")] or fail("mode must be stereo, mono or multichannel")
    local trs = with_tracks(p.tracks, function() RUN_CHECKED_ACTION(f[1], f[2]) end)
    local out = {}
    for _, tr in ipairs(trs) do out[#out + 1] = {track = track_index(tr), items = reaper.CountTrackMediaItems(tr),
                                                fx = reaper.TrackFX_GetCount(tr)} end
    return {frozen = list(out)}
end

H.track_unfreeze = function(p)
    local trs = with_tracks(p.tracks, function() RUN_CHECKED_ACTION(41644, "unfreeze") end)
    local out = {}
    for _, tr in ipairs(trs) do out[#out + 1] = {track = track_index(tr), items = reaper.CountTrackMediaItems(tr),
                                                fx = reaper.TrackFX_GetCount(tr)} end
    return {unfrozen = list(out)}
end
