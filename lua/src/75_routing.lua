-- Sends, receives and hardware outputs.  category: "send" | "receive" | "hardware"

local CAT = {send = 0, receive = -1, hardware = 1}
local MODES = {[0] = "post_fader", [1] = "pre_fx", [3] = "post_fx"}
local MODE_IDS = {post_fader = 0, pre_fx = 1, post_fx = 3}

local function S(tr, cat, i, k) return reaper.GetTrackSendInfo_Value(tr, cat, i, k) end

local function send_info(tr, cat, i)
    local r = {index = i, volume_db = db_out(S(tr, cat, i, "D_VOL")), pan = S(tr, cat, i, "D_PAN"),
               mute = S(tr, cat, i, "B_MUTE") == 1, mode = MODES[math.tointeger(S(tr, cat, i, "I_SENDMODE"))] or "other",
               src_channel = math.tointeger(S(tr, cat, i, "I_SRCCHAN")),
               dst_channel = math.tointeger(S(tr, cat, i, "I_DSTCHAN")),
               midi_flags = math.tointeger(S(tr, cat, i, "I_MIDIFLAGS"))}
    if cat == 0 then r.dest_track = track_index(reaper.GetTrackSendInfo_Value(tr, 0, i, "P_DESTTRACK"))
    elseif cat == -1 then r.source_track = track_index(reaper.GetTrackSendInfo_Value(tr, -1, i, "P_SRCTRACK")) end
    return r
end

H.send_list = function(p)
    local tr = get_track(p.track)
    local out = {}
    for name, cat in pairs(CAT) do
        local rows = {}
        for i = 0, reaper.GetTrackNumSends(tr, cat) - 1 do rows[#rows + 1] = send_info(tr, cat, i) end
        out[name .. "s"] = list(rows)
    end
    return out
end

local function apply_send(tr, cat, i, p)
    if p.volume_db ~= nil then reaper.SetTrackSendInfo_Value(tr, cat, i, "D_VOL", db_to_gain(p.volume_db)) end
    if p.pan ~= nil then reaper.SetTrackSendInfo_Value(tr, cat, i, "D_PAN", p.pan) end
    if p.mute ~= nil then reaper.SetTrackSendInfo_Value(tr, cat, i, "B_MUTE", p.mute and 1 or 0) end
    if p.mode ~= nil then
        reaper.SetTrackSendInfo_Value(tr, cat, i, "I_SENDMODE", MODE_IDS[p.mode] or fail("mode must be post_fader, pre_fx or post_fx"))
    end
    if p.src_channel ~= nil then reaper.SetTrackSendInfo_Value(tr, cat, i, "I_SRCCHAN", p.src_channel) end
    if p.dst_channel ~= nil then reaper.SetTrackSendInfo_Value(tr, cat, i, "I_DSTCHAN", p.dst_channel) end
    if p.midi_flags ~= nil then reaper.SetTrackSendInfo_Value(tr, cat, i, "I_MIDIFLAGS", p.midi_flags) end
end

H.send_create = function(p)
    local src = get_track(p.track)
    local dest = p.dest_track ~= nil and get_track(p.dest_track) or nil
    if dest == src then fail("a track can't send to itself") end
    return undoable("create send", function()
        local i = reaper.CreateTrackSend(src, dest)
        if i < 0 then fail("REAPER could not create the send") end
        local cat = dest and 0 or 1
        apply_send(src, cat, i, p)
        local r = send_info(src, cat, i)
        r.category = dest and "send" or "hardware"
        return r
    end)
end

local function send_ref(p)
    local tr = get_track(p.track)
    local cat = CAT[opt(p.category, "send")] or fail("category must be send, receive or hardware")
    local n = reaper.GetTrackNumSends(tr, cat)
    if type(p.index) ~= "number" or p.index < 0 or p.index >= n then fail("no %s %s (track has %d)", opt(p.category, "send"), tostring(p.index), n) end
    return tr, cat
end

H.send_set = function(p)
    local tr, cat = send_ref(p)
    return undoable("set send", function() apply_send(tr, cat, p.index, p); return send_info(tr, cat, p.index) end)
end

H.send_delete = function(p)
    local tr, cat = send_ref(p)
    undoable("delete send", function() reaper.RemoveTrackSend(tr, cat, p.index) end)
    return {remaining = reaper.GetTrackNumSends(tr, cat)}
end
