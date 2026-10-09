-- REAPER MCP bridge - core: JSON, handle registry, object resolution, helpers.
-- Source file; bundled into lua/mcp_bridge.lua by scripts/build_bridge.py.

H = {}          -- handler table: H.<tool_func> = function(p) ... end   (p = named params)

-- ============================================================================
-- JSON + handle registry
-- ============================================================================

-- Arrays carry their length in a metatable so nil holes survive round trips
-- (table.unpack(args) would otherwise stop at the first JSON null).
local ARRAY_MT = {}
local function json_array(t, n)
    return setmetatable(t, {__index = ARRAY_MT, __n = n or #t})
end
local function array_len(t)
    local mt = getmetatable(t)
    if mt and mt.__n then return mt.__n end
    return #t
end

-- Handle registry: userdata (MediaItem*, MediaTrack* ...) returned to the client
-- is encoded as {"__ptr": "<id>"}; when the client sends it back we resolve it to
-- the real pointer again, after validating it is still alive (a stale pointer
-- passed to the API can crash REAPER).
local HANDLES = {}
local HANDLE_TYPES = {"MediaItem_Take*", "MediaItem*", "MediaTrack*", "TrackEnvelope*",
                      "ReaProject*", "PCM_source*"}

local function register_handle(v)
    local key = tostring(v)
    HANDLES[key] = v
    return key
end

local function resolve_handle(t)
    local p = HANDLES[t.__ptr]
    if p == nil then error("Unknown handle " .. tostring(t.__ptr) .. " (bridge restarted?)") end
    for _, ty in ipairs(HANDLE_TYPES) do
        if reaper.ValidatePtr2(0, p, ty) then return p end
    end
    -- PCM sources etc. are not always project-validated; accept if ValidatePtr knows the type
    for _, ty in ipairs(HANDLE_TYPES) do
        if reaper.ValidatePtr(p, ty) then return p end
    end
    HANDLES[t.__ptr] = nil
    error("Stale handle " .. tostring(t.__ptr) .. " (object was deleted)")
end

local function resolve_args(args)
    local n = array_len(args)
    for i = 1, n do
        local a = args[i]
        if type(a) == "table" and a.__ptr then args[i] = resolve_handle(a) end
    end
    return n
end

local function encode_string(s)
    -- Escape quotes, backslashes and every control char. If the string is not
    -- valid UTF-8 (binary MIDI messages, chunk data), escape high bytes as
    -- \u00XX so the client can recover the exact bytes via latin-1.
    local valid = utf8.len(s) ~= nil
    local out = s:gsub('[%c"\\\128-\255]', function(c)
        if c == '"' then return '\\"'
        elseif c == '\\' then return '\\\\'
        elseif c == '\n' then return '\\n'
        elseif c == '\r' then return '\\r'
        elseif c == '\t' then return '\\t'
        end
        local b = c:byte()
        if b >= 128 and valid then return c end
        return string.format('\\u%04x', b)
    end)
    return '"' .. out .. '"'
end

-- JSON null that can live inside Lua tables (nil can't): keeps keys present in tool output
NULL = setmetatable({}, {__tostring = function() return "null" end})
local function nullable(v) if v == nil then return NULL end return v end

local function encode_json(v)
    local tv = type(v)
    if tv == "nil" or v == NULL then
        return "null"
    elseif tv == "boolean" then
        return tostring(v)
    elseif tv == "number" then
        if v ~= v or v == math.huge or v == -math.huge then return "null" end
        if math.type(v) == "integer" then return tostring(v) end
        return string.format("%.17g", v)
    elseif tv == "string" then
        return encode_string(v)
    elseif tv == "table" then
        local parts = {}
        local mt = getmetatable(v)
        local n = (mt and mt.__n) or #v
        if n > 0 or (mt and mt.__n) then
            for i = 1, n do parts[i] = encode_json(v[i]) end
            return "[" .. table.concat(parts, ",") .. "]"
        end
        for k, item in pairs(v) do
            parts[#parts + 1] = encode_string(tostring(k)) .. ":" .. encode_json(item)
        end
        return "{" .. table.concat(parts, ",") .. "}"
    elseif tv == "userdata" then
        return '{"__ptr":' .. encode_string(register_handle(v)) .. '}'
    end
    return "null"
end

-- Recursive-descent JSON decoder (strings may contain any of , [ ] { } ").
local function decode_json(str)
    if not str or str == "" then return nil end
    local pos = 1
    local function ws() pos = str:find("[^ \t\r\n]", pos) or #str + 1 end
    local value
    local function err(msg) error("JSON decode error at " .. pos .. ": " .. msg) end
    local function parse_string()
        pos = pos + 1
        local buf = {}
        while true do
            local c = str:sub(pos, pos)
            if c == "" then err("unterminated string") end
            if c == '"' then pos = pos + 1; break end
            if c == "\\" then
                local e = str:sub(pos + 1, pos + 1)
                if e == "u" then
                    local cp = tonumber(str:sub(pos + 2, pos + 5), 16)
                    if not cp then err("bad \\u escape") end
                    pos = pos + 6
                    -- surrogate pair
                    if cp >= 0xD800 and cp <= 0xDBFF and str:sub(pos, pos + 1) == "\\u" then
                        local lo = tonumber(str:sub(pos + 2, pos + 5), 16)
                        if lo and lo >= 0xDC00 and lo <= 0xDFFF then
                            cp = 0x10000 + (cp - 0xD800) * 0x400 + (lo - 0xDC00)
                            pos = pos + 6
                        end
                    end
                    buf[#buf + 1] = utf8.char(cp)
                else
                    local map = {n = "\n", r = "\r", t = "\t", b = "\b", f = "\f", ['"'] = '"', ["\\"] = "\\", ["/"] = "/"}
                    buf[#buf + 1] = map[e] or e
                    pos = pos + 2
                end
            else
                local s, e2 = str:find('^[^"\\]+', pos)
                buf[#buf + 1] = str:sub(s, e2)
                pos = e2 + 1
            end
        end
        return table.concat(buf)
    end
    value = function()
        ws()
        local c = str:sub(pos, pos)
        if c == "{" then
            pos = pos + 1
            local obj = {}
            ws()
            if str:sub(pos, pos) == "}" then pos = pos + 1; return obj end
            while true do
                ws()
                if str:sub(pos, pos) ~= '"' then err("expected key") end
                local k = parse_string()
                ws()
                if str:sub(pos, pos) ~= ":" then err("expected ':'") end
                pos = pos + 1
                obj[k] = value()
                ws()
                local d = str:sub(pos, pos); pos = pos + 1
                if d == "}" then return obj end
                if d ~= "," then err("expected ',' or '}'") end
            end
        elseif c == "[" then
            pos = pos + 1
            local arr, n = {}, 0
            ws()
            if str:sub(pos, pos) == "]" then pos = pos + 1; return json_array(arr, 0) end
            while true do
                n = n + 1
                arr[n] = value()
                ws()
                local d = str:sub(pos, pos); pos = pos + 1
                if d == "]" then return json_array(arr, n) end
                if d ~= "," then err("expected ',' or ']'") end
            end
        elseif c == '"' then
            return parse_string()
        elseif str:sub(pos, pos + 3) == "true" then pos = pos + 4; return true
        elseif str:sub(pos, pos + 4) == "false" then pos = pos + 5; return false
        elseif str:sub(pos, pos + 3) == "null" then pos = pos + 4; return nil
        else
            local s, e = str:find("^-?%d+%.?%d*[eE]?[-+]?%d*", pos)
            if not s then err("unexpected '" .. c .. "'") end
            pos = e + 1
            return tonumber(str:sub(s, e))
        end
    end
    local ok, res = pcall(value)
    if not ok then
        reaper.ShowConsoleMsg("MCP bridge: " .. tostring(res) .. "\n")
        return nil
    end
    return res
end

-- ============================================================================
-- Generic helpers
-- ============================================================================

local function round(x) return math.floor(x + 0.5) end

-- list(t) marks a Lua sequence as a JSON array (also when empty)
local function list(t) return json_array(t or {}, #(t or {})) end

local function fail(msg, ...) error(string.format(msg, ...), 0) end

local function opt(v, default) if v == nil then return default end return v end

local function db_to_gain(db) return 10 ^ (db / 20) end
local function gain_to_db(g) if g <= 0 then return -math.huge end return 20 * math.log(g, 10) end
local function db_out(g)    -- JSON can't hold -inf
    local d = gain_to_db(g); if d == -math.huge then return -150.0 end; return d
end

local function color_to_native(c)
    if c == nil or c == false or c == "" then return 0 end
    local r, g, b = c:match("^#?(%x%x)(%x%x)(%x%x)$")
    if not r then fail("color must be '#rrggbb', got %s", tostring(c)) end
    return reaper.ColorToNative(tonumber(r, 16), tonumber(g, 16), tonumber(b, 16)) | 0x1000000
end

local function color_from_native(n)
    if not n or n & 0x1000000 == 0 then return NULL end
    local r, g, b = reaper.ColorFromNative(n & 0xFFFFFF)
    return string.format("#%02x%02x%02x", r, g, b)
end

-- run fn inside one undo block (and without UI refresh); returns fn's result
local function undoable(desc, fn)
    reaper.Undo_BeginBlock2(0)
    reaper.PreventUIRefresh(1)
    local ok, res = pcall(fn)
    reaper.PreventUIRefresh(-1)
    reaper.Undo_EndBlock2(0, "MCP: " .. desc, -1)
    reaper.UpdateArrange()
    if not ok then error(res, 0) end
    return res
end

local function guid_of_track(tr) return reaper.GetTrackGUID(tr) end
local function guid_of_item(it)
    local _, g = reaper.GetSetMediaItemInfo_String(it, "GUID", "", false); return g
end

-- ============================================================================
-- Object resolution (index / GUID / name)
-- ============================================================================

local function track_index(tr)
    if tr == reaper.GetMasterTrack(0) then return -1 end
    return math.tointeger(reaper.GetMediaTrackInfo_Value(tr, "IP_TRACKNUMBER")) - 1
end

-- track ref: integer index (0-based, -1 = master), GUID "{...}", or exact track name
local function get_track(ref)
    if ref == nil then fail("track is required") end
    if type(ref) == "number" then
        if ref == -1 then return reaper.GetMasterTrack(0) end
        local tr = reaper.GetTrack(0, ref)
        if not tr then fail("no track at index %d (project has %d tracks)", ref, reaper.CountTracks(0)) end
        return tr
    end
    if type(ref) == "string" then
        if ref:match("^{.*}$") then
            for i = 0, reaper.CountTracks(0) - 1 do
                local tr = reaper.GetTrack(0, i)
                if reaper.GetTrackGUID(tr) == ref then return tr end
            end
            fail("no track with GUID %s", ref)
        end
        local found
        for i = 0, reaper.CountTracks(0) - 1 do
            local tr = reaper.GetTrack(0, i)
            local _, name = reaper.GetTrackName(tr)
            if name == ref then
                if found then fail("more than one track is named '%s' - use the index", ref) end
                found = tr
            end
        end
        if found then return found end
        fail("no track named '%s'", ref)
    end
    if type(ref) == "userdata" then return ref end
    fail("bad track reference %s", tostring(ref))
end

-- item ref: project-wide index (0-based) or GUID
local function get_item(ref)
    if ref == nil then fail("item is required") end
    if type(ref) == "number" then
        local it = reaper.GetMediaItem(0, ref)
        if not it then fail("no item at index %d (project has %d items)", ref, reaper.CountMediaItems(0)) end
        return it
    end
    if type(ref) == "string" then
        for i = 0, reaper.CountMediaItems(0) - 1 do
            local it = reaper.GetMediaItem(0, i)
            if guid_of_item(it) == ref then return it end
        end
        fail("no item with GUID %s", ref)
    end
    if type(ref) == "userdata" then return ref end
    fail("bad item reference %s", tostring(ref))
end

local function item_index(it)
    for i = 0, reaper.CountMediaItems(0) - 1 do
        if reaper.GetMediaItem(0, i) == it then return i end
    end
    return -1
end

-- take ref on an item: index, -1/nil = active take
local function get_take(item, ref)
    local take
    if ref == nil or ref == -1 then take = reaper.GetActiveTake(item)
    else take = reaper.GetMediaItemTake(item, ref) end
    if not take then fail("item has no take %s", tostring(ref or "(active)")) end
    return take
end

local function get_midi_take(p)
    local item = get_item(p.item)
    local take = get_take(item, p.take)
    if not reaper.TakeIsMIDI(take) then fail("take is not MIDI") end
    return item, take
end

local function check_time(t, what)
    if type(t) ~= "number" then fail("%s must be a number (seconds)", what) end
    return t
end

