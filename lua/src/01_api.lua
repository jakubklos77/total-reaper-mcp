-- reaper_api: call any ReaScript function by name (the long tail not covered by domain tools).
-- Pointers returned by REAPER come back as {"__ptr": "..."} handles and can be passed back.

H.reaper_api = function(p)
    local fname = p.func
    if type(fname) ~= "string" or reaper[fname] == nil then
        fail("unknown ReaScript function '%s'", tostring(fname))
    end
    local args = p.args or json_array({}, 0)
    local n = resolve_args(args)
    local res = table.pack(reaper[fname](table.unpack(args, 1, n)))   -- errors propagate as tool errors
    local vals = {}
    for i = 1, res.n do vals[i] = res[i] end
    return {ret = json_array(vals, res.n)}
end

H.ping = function()
    return {version = reaper.GetAppVersion(), bridge = 2}
end
