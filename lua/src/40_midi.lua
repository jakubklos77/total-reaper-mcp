-- MIDI editing. Positions use `unit`: "seconds" (project time), "qn" (project quarter notes,
-- follows the tempo map) or "ppq" (take ticks).

local function to_ppq(take, v, unit)
    if unit == "ppq" then return v
    elseif unit == "seconds" then return reaper.MIDI_GetPPQPosFromProjTime(take, v)
    elseif unit == "qn" then return reaper.MIDI_GetPPQPosFromProjQN(take, v)
    end
    fail("unit must be seconds, qn or ppq")
end

local function from_ppq(take, ppq, unit)
    if unit == "ppq" then return ppq
    elseif unit == "seconds" then return reaper.MIDI_GetProjTimeFromPPQPos(take, ppq)
    else return reaper.MIDI_GetProjQNFromPPQPos(take, ppq) end
end

local function to_hex(s) return (s:gsub(".", function(c) return string.format("%02x", c:byte()) end)) end
local function from_hex(h)
    if type(h) ~= "string" or h:find("[^%x]") or #h % 2 == 1 then fail("bad hex MIDI message: %s", tostring(h)) end
    return (h:gsub("%x%x", function(x) return string.char(tonumber(x, 16)) end))
end

local NOTE_FIELDS = {"index", "pitch", "velocity", "channel", "start_qn", "end_qn", "start_sec", "end_sec",
                     "start_ppq", "end_ppq", "selected", "muted"}
local CC_FIELDS = {"index", "type", "cc", "value", "channel", "qn", "sec", "ppq", "selected", "muted"}
local EVENT_FIELDS = {"ppq", "flags", "hex", "sec", "qn"}

local CC_TYPES = {[0xB0] = "cc", [0xE0] = "pitchbend", [0xC0] = "program", [0xD0] = "channel_pressure",
                  [0xA0] = "poly_aftertouch"}
local CC_STATUS = {cc = 0xB0, pitchbend = 0xE0, program = 0xC0, channel_pressure = 0xD0, poly_aftertouch = 0xA0}

local function note_row(take, i)
    local _, sel, mute, sp, ep, ch, pitch, vel = reaper.MIDI_GetNote(take, i)
    return json_array({i, pitch, vel, ch,
        reaper.MIDI_GetProjQNFromPPQPos(take, sp), reaper.MIDI_GetProjQNFromPPQPos(take, ep),
        reaper.MIDI_GetProjTimeFromPPQPos(take, sp), reaper.MIDI_GetProjTimeFromPPQPos(take, ep),
        sp, ep, sel, mute}, 12)
end

local function cc_row(take, i)
    local _, sel, mute, ppq, chanmsg, ch, m2, m3 = reaper.MIDI_GetCC(take, i)
    local typ = CC_TYPES[chanmsg] or string.format("0x%02x", chanmsg)
    local num, val = m2, m3
    if chanmsg == 0xE0 then num, val = NULL, (m3 << 7 | m2) - 8192
    elseif chanmsg == 0xC0 or chanmsg == 0xD0 then num, val = NULL, m2 end
    return json_array({i, typ, num, val, ch, reaper.MIDI_GetProjQNFromPPQPos(take, ppq),
        reaper.MIDI_GetProjTimeFromPPQPos(take, ppq), ppq, sel, mute}, 10)
end

H.midi_get = function(p)
    local item, take = get_midi_take(p)
    local _, nn, nc, nt = reaper.MIDI_CountEvts(take)
    local qn0 = reaper.MIDI_GetProjQNFromPPQPos(take, 0)
    local r = {
        item = item_index(item), take = math.tointeger(reaper.GetMediaItemTakeInfo_Value(take, "IP_TAKENUMBER")),
        counts = {notes = nn, ccs = nc, sysex_text = nt},
        ppq_per_qn = round(reaper.MIDI_GetPPQPosFromProjQN(take, qn0 + 1) - reaper.MIDI_GetPPQPosFromProjQN(take, qn0)),
        item_position = reaper.GetMediaItemInfo_Value(item, "D_POSITION"),
        item_length = reaper.GetMediaItemInfo_Value(item, "D_LENGTH"),
    }
    local _, chunk = reaper.GetItemStateChunk(item, "", false)
    r.follows_project_tempo = (chunk:match("IGNTEMPO (%d)") or "0") == "0"
    if opt(p.notes, true) then
        local rows = {}
        for i = 0, nn - 1 do rows[i + 1] = note_row(take, i) end
        r.note_fields, r.notes = list(NOTE_FIELDS), json_array(rows, nn)
    end
    if opt(p.ccs, true) then
        local rows = {}
        for i = 0, nc - 1 do rows[i + 1] = cc_row(take, i) end
        r.cc_fields, r.ccs = list(CC_FIELDS), json_array(rows, nc)
    end
    if p.events then
        local ok, buf = reaper.MIDI_GetAllEvts(take, "")
        if not ok then fail("MIDI_GetAllEvts failed") end
        local rows, n, pos, ppq = {}, 0, 1, 0
        while pos + 8 <= #buf do
            local off, flags, len
            off, flags, len, pos = string.unpack("<i4Bi4", buf, pos)
            local msg = buf:sub(pos, pos + len - 1)
            pos = pos + len
            ppq = ppq + off
            n = n + 1
            rows[n] = json_array({ppq, flags, to_hex(msg), reaper.MIDI_GetProjTimeFromPPQPos(take, ppq),
                                  reaper.MIDI_GetProjQNFromPPQPos(take, ppq)}, 5)
        end
        r.event_fields, r.events = list(EVENT_FIELDS), json_array(rows, n)
    end
    return r
end

-- Replace ALL events: events = [[pos, flags, hexmsg], ...] in `unit` (default ppq).
H.midi_set = function(p)
    local item, take = get_midi_take(p)
    local unit = opt(p.unit, "ppq")
    local evs = p.events or json_array({}, 0)
    local list_ = {}
    for i = 1, array_len(evs) do
        local e = evs[i]
        list_[i] = {ppq = round(to_ppq(take, e[1], unit)), flags = e[2] or 0, msg = from_hex(e[3]), idx = i}
    end
    table.sort(list_, function(a, b) if a.ppq ~= b.ppq then return a.ppq < b.ppq end return a.idx < b.idx end)
    local parts, last = {}, 0
    for i, e in ipairs(list_) do
        parts[i] = string.pack("<i4Bi4", e.ppq - last, e.flags, #e.msg) .. e.msg
        last = e.ppq
    end
    return undoable("replace MIDI", function()
        if not reaper.MIDI_SetAllEvts(take, table.concat(parts)) then fail("MIDI_SetAllEvts failed") end
        reaper.MIDI_Sort(take)
        if p.fit_item and #list_ > 0 then
            local pos = reaper.GetMediaItemInfo_Value(item, "D_POSITION")
            reaper.MIDI_SetItemExtents(item, reaper.TimeMap2_timeToQN(0, pos),
                reaper.MIDI_GetProjQNFromPPQPos(take, list_[#list_].ppq))
        end
        local _, nn, nc = reaper.MIDI_CountEvts(take)
        return {events = #list_, notes = nn, ccs = nc, item_length = reaper.GetMediaItemInfo_Value(item, "D_LENGTH")}
    end)
end

local function check_pitch(v, what)
    if type(v) ~= "number" or v < 0 or v > 127 or v ~= math.floor(v) then fail("%s must be an integer 0-127", what) end
    return math.tointeger(v)
end

H.midi_insert_notes = function(p)
    local item, take = get_midi_take(p)
    local unit = opt(p.unit, "qn")
    local notes = p.notes or json_array({}, 0)
    local n = array_len(notes)
    if n == 0 then fail("notes is required") end
    return undoable("insert notes", function()
        for i = 1, n do
            local q = notes[i]
            local s = to_ppq(take, q.start or fail("note %d: start is required", i), unit)
            local e
            if q["end"] ~= nil then e = to_ppq(take, q["end"], unit)
            elseif q.length ~= nil then
                if unit == "ppq" then e = s + q.length else e = to_ppq(take, q.start + q.length, unit) end
            else fail("note %d: give end or length", i) end
            if e <= s then fail("note %d: end must be after start", i) end
            reaper.MIDI_InsertNote(take, q.selected and true or false, q.muted and true or false, round(s), round(e),
                opt(q.channel, 0), check_pitch(q.pitch, "pitch"), check_pitch(opt(q.velocity, 96), "velocity"), true)
        end
        reaper.MIDI_Sort(take)
        local _, nn = reaper.MIDI_CountEvts(take)
        return {inserted = n, notes = nn}
    end)
end

-- note/cc filter: indices | pitch/cc range, time range (unit), channel, selected_only
local function matches(take, unit, f, idx, ppq, pitch, ch, sel)
    if f.indices then
        local hit = false
        for i = 1, array_len(f.indices) do if f.indices[i] == idx then hit = true break end end
        if not hit then return false end
    end
    if f.pitch_min and pitch < f.pitch_min then return false end
    if f.pitch_max and pitch > f.pitch_max then return false end
    if f.channel and ch ~= f.channel then return false end
    if f.selected_only and not sel then return false end
    if f.start and from_ppq(take, ppq, unit) < f.start - 1e-9 then return false end
    if f["end"] and from_ppq(take, ppq, unit) >= f["end"] - 1e-9 then return false end
    return true
end

local function selected_notes(take, p, unit)
    local _, nn = reaper.MIDI_CountEvts(take)
    local out = {}
    for i = 0, nn - 1 do
        local _, sel, mute, sp, ep, ch, pitch = reaper.MIDI_GetNote(take, i)
        if matches(take, unit, p, i, sp, pitch, ch, sel) then out[#out + 1] = i end
    end
    return out
end

H.midi_edit_notes = function(p)
    local item, take = get_midi_take(p)
    local unit = opt(p.unit, "qn")
    local edits = p.edits or json_array({}, 0)
    local n = array_len(edits)
    if n == 0 then fail("edits is required") end
    local _, nn = reaper.MIDI_CountEvts(take)
    return undoable("edit notes", function()
        for i = 1, n do
            local e = edits[i]
            if type(e.index) ~= "number" or e.index < 0 or e.index >= nn then fail("edit %d: no note index %s", i, tostring(e.index)) end
            local _, sel, mute, sp, ep, ch, pitch, vel = reaper.MIDI_GetNote(take, e.index)
            local ns = e.start ~= nil and round(to_ppq(take, e.start, unit)) or sp
            local ne = ep
            if e["end"] ~= nil then ne = round(to_ppq(take, e["end"], unit))
            elseif e.length ~= nil then
                ne = unit == "ppq" and ns + e.length or round(to_ppq(take, from_ppq(take, ns, unit) + e.length, unit))
            elseif e.start ~= nil then ne = ns + (ep - sp) end         -- moving keeps the length
            if ne <= ns then fail("edit %d: end must be after start", i) end
            reaper.MIDI_SetNote(take, e.index, opt(e.selected, sel), opt(e.muted, mute), ns, ne,
                opt(e.channel, ch), e.pitch and check_pitch(e.pitch, "pitch") or pitch,
                e.velocity and check_pitch(e.velocity, "velocity") or vel, true)
        end
        reaper.MIDI_Sort(take)
        return {edited = n}
    end)
end

H.midi_delete_notes = function(p)
    local item, take = get_midi_take(p)
    local idx = selected_notes(take, p, opt(p.unit, "qn"))
    return undoable("delete notes", function()
        for i = #idx, 1, -1 do reaper.MIDI_DeleteNote(take, idx[i]) end
        local _, nn = reaper.MIDI_CountEvts(take)
        return {deleted = #idx, notes = nn}
    end)
end

H.midi_insert_ccs = function(p)
    local item, take = get_midi_take(p)
    local unit = opt(p.unit, "qn")
    local ccs = p.ccs or json_array({}, 0)
    local n = array_len(ccs)
    if n == 0 then fail("ccs is required") end
    return undoable("insert CCs", function()
        for i = 1, n do
            local c = ccs[i]
            local typ = opt(c.type, "cc")
            local status = CC_STATUS[typ] or fail("cc %d: type must be cc, pitchbend, program, channel_pressure or poly_aftertouch", i)
            local m2, m3
            if typ == "pitchbend" then
                local v = round(c.value) + 8192
                if v < 0 or v > 16383 then fail("cc %d: pitchbend value must be -8192..8191", i) end
                m2, m3 = v & 0x7F, v >> 7
            elseif typ == "program" or typ == "channel_pressure" then
                m2, m3 = check_pitch(c.value, "value"), 0
            else
                m2, m3 = check_pitch(c.cc, "cc"), check_pitch(c.value, "value")
            end
            local pos = to_ppq(take, c.position or fail("cc %d: position is required", i), unit)
            reaper.MIDI_InsertCC(take, c.selected and true or false, c.muted and true or false, round(pos),
                status, opt(c.channel, 0), m2, m3)
        end
        reaper.MIDI_Sort(take)
        local _, _, nc = reaper.MIDI_CountEvts(take)
        return {inserted = n, ccs = nc}
    end)
end

H.midi_delete_ccs = function(p)
    local item, take = get_midi_take(p)
    local unit = opt(p.unit, "qn")
    local _, _, nc = reaper.MIDI_CountEvts(take)
    local idx = {}
    for i = 0, nc - 1 do
        local _, sel, mute, ppq, chanmsg, ch, m2 = reaper.MIDI_GetCC(take, i)
        local ok = matches(take, unit, {indices = p.indices, channel = p.channel, selected_only = p.selected_only,
                                        start = p.start, ["end"] = p["end"]}, i, ppq, 0, ch, sel)
        if ok and p.type and CC_TYPES[chanmsg] ~= p.type then ok = false end
        if ok and p.cc and (chanmsg ~= 0xB0 or m2 ~= p.cc) then ok = false end
        if ok then idx[#idx + 1] = i end
    end
    return undoable("delete CCs", function()
        for i = #idx, 1, -1 do reaper.MIDI_DeleteCC(take, idx[i]) end
        local _, _, left = reaper.MIDI_CountEvts(take)
        return {deleted = #idx, ccs = left}
    end)
end

-- Quantize note starts (and optionally ends) to a grid in quarter notes of the PROJECT tempo
-- map, so a tempo-synced performance quantizes to the played beats.
H.midi_quantize = function(p)
    local item, take = get_midi_take(p)
    local grid = p.grid or fail("grid is required (in quarter notes: 1 = quarter, 0.5 = eighth, 1/3 = eighth triplet)")
    if grid <= 0 then fail("grid must be > 0") end
    local strength = opt(p.strength, 1.0)
    if strength < 0 or strength > 1 then fail("strength must be 0..1") end
    local swing = opt(p.swing, 0)
    local idx = selected_notes(take, p, opt(p.unit, "qn"))
    local function snap(q)
        local k = math.floor(q / grid + 0.5)
        local target = k * grid
        if swing ~= 0 and k % 2 == 1 then target = target + swing * grid * 0.5 end
        return q + (target - q) * strength
    end
    return undoable("quantize notes", function()
        local moved = 0
        for _, i in ipairs(idx) do
            local _, sel, mute, sp, ep, ch, pitch, vel = reaper.MIDI_GetNote(take, i)
            local qs, qe = reaper.MIDI_GetProjQNFromPPQPos(take, sp), reaper.MIDI_GetProjQNFromPPQPos(take, ep)
            local ns = round(reaper.MIDI_GetPPQPosFromProjQN(take, snap(qs)))
            local ne
            if p.ends then ne = round(reaper.MIDI_GetPPQPosFromProjQN(take, snap(qe)))
            else ne = ns + (ep - sp) end
            if ne <= ns then ne = ns + math.max(1, ep - sp) end
            if ns ~= sp or ne ~= ep then moved = moved + 1 end
            reaper.MIDI_SetNote(take, i, sel, mute, ns, ne, ch, pitch, vel, true)
        end
        reaper.MIDI_Sort(take)
        return {notes = #idx, moved = moved}
    end)
end

H.midi_transpose = function(p)
    local item, take = get_midi_take(p)
    local st = p.semitones
    if type(st) ~= "number" or st ~= math.floor(st) then fail("semitones must be an integer") end
    local idx = selected_notes(take, p, opt(p.unit, "qn"))
    for _, i in ipairs(idx) do
        local _, _, _, _, _, _, pitch = reaper.MIDI_GetNote(take, i)
        if pitch + st < 0 or pitch + st > 127 then fail("note %d would leave the MIDI range (pitch %d)", i, pitch + st) end
    end
    return undoable("transpose notes", function()
        for _, i in ipairs(idx) do
            local _, sel, mute, sp, ep, ch, pitch, vel = reaper.MIDI_GetNote(take, i)
            reaper.MIDI_SetNote(take, i, sel, mute, sp, ep, ch, math.tointeger(pitch + st), vel, true)
        end
        reaper.MIDI_Sort(take)
        return {transposed = #idx}
    end)
end
