-- Markers and regions (identified by their displayed number + is_region)

local function all_markers()
    local out, i = {}, 0
    while true do
        local ret, isrgn, pos, rend, name, num, color = reaper.EnumProjectMarkers3(0, i)
        if ret == 0 then break end
        out[#out + 1] = {number = num, region = isrgn, position = pos, ["end"] = isrgn and rend or NULL,
                         name = name, color = color_from_native(color), enum_index = i}
        i = i + 1
    end
    return out
end

local function find_marker(num, region)
    for _, m in ipairs(all_markers()) do
        if m.number == num and m.region == (region and true or false) then return m end
    end
    fail("no %s number %s", region and "region" or "marker", tostring(num))
end

H.marker_list = function(p)
    local markers, regions = {}, {}
    for _, m in ipairs(all_markers()) do
        m.enum_index = nil
        if m.region then regions[#regions + 1] = m else markers[#markers + 1] = m end
    end
    return {markers = list(markers), regions = list(regions)}
end

H.marker_add = function(p)
    local pos = check_time(p.position, "position")
    local isrgn = p["end"] ~= nil
    if isrgn and p["end"] <= pos then fail("region end must be after position") end
    return undoable("add marker", function()
        local num = reaper.AddProjectMarker2(0, isrgn, pos, p["end"] or 0, p.name or "", opt(p.number, -1),
            p.color and color_to_native(p.color) or 0)
        if num < 0 then fail("REAPER could not add the marker") end
        return find_marker(num, isrgn)
    end)
end

H.marker_set = function(p)
    local m = find_marker(p.number, p.region)
    return undoable("edit marker", function()
        local pos = opt(p.position, m.position)
        local rend = m.region and opt(p["end"], m["end"]) or 0
        local name = opt(p.name, m.name)
        local color = m.color ~= NULL and color_to_native(m.color) or 0
        if p.color ~= nil then color = color_to_native(p.color) end
        if p.clear_color then color = 0 end
        -- flags &1: allow setting an empty name
        reaper.SetProjectMarker4(0, m.number, m.region, pos, rend, name, color, name == "" and 1 or 0)
        return find_marker(m.number, m.region)
    end)
end

H.marker_delete = function(p)
    find_marker(p.number, p.region)
    undoable("delete marker", function() reaper.DeleteProjectMarker(0, p.number, p.region and true or false) end)
    local _, nm, nr = reaper.CountProjectMarkers(0)
    return {markers = nm, regions = nr}
end
