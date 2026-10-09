-- Run a main-section action only if REAPER's name for that id contains `expect` (guards
-- against wrong/changed command ids doing something else).
function RUN_CHECKED_ACTION(id, expect)
    local name = reaper.kbd_getTextFromCmd(id, reaper.SectionFromUniqueID(0)) or ""
    if not name:lower():find(expect:lower(), 1, true) then
        error(string.format("action %d is '%s', expected '%s' - not run", id, name, expect), 0)
    end
    reaper.Main_OnCommand(id, 0)
end
