-- Actions (main section)

local function resolve_command(c)
    if type(c) == "number" then return math.tointeger(c) end
    if type(c) == "string" then
        if c:match("^%d+$") then return math.tointeger(tonumber(c)) end
        local id = reaper.NamedCommandLookup(c:sub(1, 1) == "_" and c or ("_" .. c))
        if id == 0 then fail("unknown named command '%s'", c) end
        return id
    end
    fail("command must be an id or a named command string like '_SWS_ABOUT'")
end

local function action_name(id) return reaper.kbd_getTextFromCmd(id, reaper.SectionFromUniqueID(0)) or "" end

H.action_run = function(p)
    local id = resolve_command(p.command)
    local name = action_name(id)
    if name == "" then fail("no action with id %d", id) end
    reaper.Main_OnCommand(id, 0)
    return {id = id, name = name, state = reaper.GetToggleCommandState(id)}
end

H.action_find = function(p)
    local words = {}
    for w in (p.query or ""):lower():gmatch("%S+") do words[#words + 1] = w end
    if #words == 0 then fail("query is required") end
    local sec = reaper.SectionFromUniqueID(0)
    local out, i, limit = {}, 0, opt(p.limit, 50)
    while #out < limit do
        local id, name = reaper.kbd_enumerateActions(sec, i)
        if not id or id == 0 then break end
        local lname, hit = name:lower(), true
        for _, w in ipairs(words) do if not lname:find(w, 1, true) then hit = false break end end
        if hit then
            local named = reaper.ReverseNamedCommandLookup(id)
            out[#out + 1] = {id = id, name = name, named_command = named and ("_" .. named) or NULL,
                             state = reaper.GetToggleCommandState(id)}
        end
        i = i + 1
    end
    return {actions = list(out)}
end

H.action_state = function(p)
    local id = resolve_command(p.command)
    return {id = id, name = action_name(id), state = reaper.GetToggleCommandState(id)}
end
