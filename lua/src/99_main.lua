-- REAPER MCP bridge - request loop. Source file; bundled by scripts/build_bridge.py.

local bridge_dir = reaper.GetResourcePath() .. '/Scripts/mcp_bridge_data/'

local function read_file(path)
    local f = io.open(path, "rb"); if not f then return nil end
    local s = f:read("a"); f:close(); return s
end

local function write_file(path, s)
    -- write to a temp name and rename, so the client never reads a half-written response
    local tmp = path .. ".tmp"
    local f = io.open(tmp, "wb"); if not f then return false end
    f:write(s); f:close()
    os.remove(path)
    return os.rename(tmp, path)
end

-- request ids are unique per server process (random base): list the directory
local function pending_request_ids()
    local ids, idx = {}, 0
    while true do
        local name = reaper.EnumerateFiles(bridge_dir, idx)   -- idx 0 forces a rescan
        if not name then break end
        local id = name:match("^request_(%d+)%.json$")
        if id then ids[#ids + 1] = id end
        idx = idx + 1
    end
    table.sort(ids, function(a, b) return #a < #b or (#a == #b and a < b) end)
    return ids
end

local DEBUG = reaper.GetExtState("MCP_BRIDGE", "debug") == "1"

local function handle(request)
    local func = request.func
    local args = request.args or json_array({}, 0)
    local n = resolve_args(args)
    local h = H[func]
    if not h then return {ok = false, error = "Unknown function: " .. tostring(func)} end
    local res = h(table.unpack(args, 1, n))
    if type(res) ~= "table" then res = {ret = res} end
    if res.ok == nil then res.ok = true end
    return res
end

local function process_requests()
    for _, id in ipairs(pending_request_ids()) do
        local req_path = bridge_dir .. "request_" .. id .. ".json"
        local resp_path = bridge_dir .. "response_" .. id .. ".json"
        local raw = read_file(req_path)
        os.remove(req_path)
        if raw then
            local response
            local ok, err = pcall(function()
                local request = decode_json(raw)
                if type(request) ~= "table" or not request.func then error("malformed request", 0) end
                if DEBUG then reaper.ShowConsoleMsg("MCP <- " .. raw:sub(1, 300) .. "\n") end
                response = handle(request)
            end)
            if not ok then response = {ok = false, error = tostring(err)} end
            local out = encode_json(response)
            if DEBUG then reaper.ShowConsoleMsg("MCP -> " .. out:sub(1, 300) .. "\n") end
            write_file(resp_path, out)
        end
    end
end

reaper.RecursiveCreateDirectory(bridge_dir, 0)

-- Opt-in hot reload for development: with ExtState MCP_BRIDGE/autoreload = "1" the bridge
-- re-runs its own script file when it changes (checked once a second). Each load bumps a
-- generation counter; the previous loop sees it and stops.
MCP_BRIDGE_GEN = (MCP_BRIDGE_GEN or 0) + 1
local my_gen = MCP_BRIDGE_GEN
local script_path = (debug.getinfo(1, "S").source or ""):match("^@(.+)$")
local loaded_src = script_path and read_file(script_path)
local last_check = reaper.time_precise()

local function maybe_reload()
    if reaper.GetExtState("MCP_BRIDGE", "autoreload") ~= "1" or not loaded_src then return false end
    local now = reaper.time_precise()
    if now - last_check < 1 then return false end
    last_check = now
    local src = read_file(script_path)
    if not src or src == loaded_src then return false end
    loaded_src = src
    local chunk, err = load(src, "@" .. script_path)
    if not chunk then
        reaper.ShowConsoleMsg("MCP bridge: reload failed, keeping the running version: " .. tostring(err) .. "\n")
        return false
    end
    reaper.ShowConsoleMsg("MCP bridge: source changed, reloading\n")
    chunk()
    return true
end

reaper.ShowConsoleMsg(string.format("REAPER MCP bridge started (gen %d, %s)\n", my_gen, bridge_dir))

local function loop()
    if MCP_BRIDGE_GEN ~= my_gen then return end   -- superseded by a reload
    process_requests()
    if maybe_reload() then return end
    reaper.defer(loop)
end
loop()
