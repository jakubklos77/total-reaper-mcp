# REAPER DAW MCP setup (Linux host + Windows VM)

Claude Code runs on the Linux host. REAPER runs in the Windows VM. Claude Code starts
the MCP server on Windows over SSH and talks to it through stdin/stdout.

```
Linux: Claude Code ──stdio over SSH──► Windows: Python MCP server ──JSON files──► Lua bridge in REAPER
```

| What | Where |
|---|---|
| MCP server | https://github.com/shiehn/total-reaper-mcp |
| Repo (git clone, Linux host) | `Y:\music\total-reaper-mcp` on the share |
| Server path used on Windows | `C:\Program Files\REAPER (x64)\total-reaper-mcp` → symlink to the repo |
| venv | `.venv` inside the repo |
| Wrapper script (Windows side) | `run_reaper_mcp.sh` inside the repo |
| Launcher script (Linux side) | `~/Music/AI/reaper-mcp.sh` |
| Bridge data folder | `C:\Users\Jakub\AppData\Roaming\REAPER\Scripts\mcp_bridge_data` |

The repo, venv, this file and the wrapper all live in one place on the host share, so
`git pull` on Linux updates the server immediately.

---

## 1. Install uv (Windows, PowerShell)

uv provides a self-contained Python, so there's no system-wide Python install.
Cygwin's Python can't be used because the MCP SDK has no Cygwin builds.

```powershell
powershell -c "irm https://astral.sh/uv/install.ps1 | iex"
```

## 2. Clone the repo (Linux host)

```bash
git clone https://github.com/shiehn/total-reaper-mcp
```

There's no git on Windows; the VM sees the repo through the share (`Y:\`).

## 3. Install the venv (Windows, elevated Cygwin shell)

The install **cannot run on the share**. Windows Python fails there with
`WinError 1005 The volume does not contain a recognized file system`.
So: install into a temporary local copy, then move the venv to the share and replace
the copy with a symlink.

**a) Temporary local copy** (without `.git` and the `.venv` folders committed to the repo):

```bash
mkdir -p "/cygdrive/c/Program Files/REAPER (x64)/total-reaper-mcp"
tar -C /cygdrive/y/music/total-reaper-mcp \
    --exclude=.git --exclude=.venv --exclude=.venv-new -cf - . \
  | tar -C "/cygdrive/c/Program Files/REAPER (x64)/total-reaper-mcp" -xf -
```

**b) Create the venv and install:**

```bash
cd "/cygdrive/c/Program Files/REAPER (x64)/total-reaper-mcp"
uv venv --python 3.11
uv pip install --python .venv/Scripts/python.exe -e . "mcp<2"
```

`mcp<2` is required. The project is written for MCP SDK 1.x; with 2.x it fails with
`No module named 'mcp.server.fastmcp'`.

**c) Move the venv to the repo and replace the copy with a symlink:**

```bash
cp -r "/cygdrive/c/Program Files/REAPER (x64)/total-reaper-mcp/.venv" /cygdrive/y/music/total-reaper-mcp/
rm -rf "/cygdrive/c/Program Files/REAPER (x64)/total-reaper-mcp"
cmd /c mklink /D "C:\Program Files\REAPER (x64)\total-reaper-mcp" "Y:\music\total-reaper-mcp"
```

- Use `mklink` (a native Windows symlink), not Cygwin's `ln -s`. Windows Python may not follow Cygwin symlinks.
- **Keep the path `C:\Program Files\REAPER (x64)\total-reaper-mcp` exactly as it is.** The editable install
  (`-e .`) recorded this path inside the venv, which is why everything still works through the symlink.

## 4. Install the Lua bridge into REAPER

```bash
cmd /c mklink "C:\Users\Jakub\AppData\Roaming\REAPER\Scripts" "Y:\music\total-reaper-mcp\lua\mcp_bridge.lua"
```

Start it automatically with REAPER, without the console popup. Create
`%APPDATA%\REAPER\Scripts\__startup.lua` containing:

```lua
-- Start MCP bridge (console output suppressed)
local orig = reaper.ShowConsoleMsg
reaper.ShowConsoleMsg = function() end
dofile(reaper.GetResourcePath() .. "/Scripts/mcp_bridge.lua")
reaper.ShowConsoleMsg = orig
```

To check that the bridge is running, the `mcp_bridge_data` folder should exist. To see the
startup message, run `mcp_bridge.lua` manually from Actions → Show action list.

## 5. Scripts

**`run_reaper_mcp.sh`** (in the repo, run on Windows by Cygwin bash). It sets the environment and starts
`.venv/Scripts/python.exe -m server.app` from the repo folder.

- `REAPER_MCP_BRIDGE_DIR` must be set to a Windows path (`C:/Users/Jakub/AppData/Roaming/REAPER/Scripts/mcp_bridge_data`).
  It is required; the server defaults to the macOS path, and tool calls would time out.
- The script needs **LF line endings** (CRLF breaks `cd` and `export` with a hidden `\r`). Fix with `dos2unix`.
- Run on its own, it prints nothing and waits for input; that's correct.

**`~/Music/AI/reaper-mcp.sh`** (Linux) runs `ssh -T reaper-vm <path to run_reaper_mcp.sh>`.

- Use `-T`, not `-t`, and no `bash -i`. stdout must contain only MCP JSON.
- The path contains spaces and parentheses, so it needs quoting for the remote shell,
  e.g. `"'/cygdrive/c/Program Files/REAPER (x64)/total-reaper-mcp/run_reaper_mcp.sh'"`.

SSH must work without a password (`~/.ssh/config`: `BatchMode yes`, `LogLevel QUIET`, key-based auth).

Register with Claude Code (this also applies to the VS Code extension):

```bash
claude mcp add reaper --scope user -- /home/jakub/Music/AI/reaper-mcp.sh
```

## 6. Testing

Handshake test from Linux. This should print a single line of JSON with `"serverInfo"`:

```bash
printf '%s\n' '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-06-18","capabilities":{},"clientInfo":{"name":"test","version":"1"}}}' \
  | ~/Music/AI/reaper-mcp.sh 2>/dev/null
```

The handshake doesn't touch REAPER, so nothing appears in the REAPER console.

In Claude Code: run `/mcp`, where `reaper` should be connected, then ask
*"List the tracks in the current REAPER project."*

## Troubleshooting

| Symptom | Cause / fix |
|---|---|
| `cd: $'...\r': No such file or directory` | CRLF line endings → `dos2unix` the script |
| `No module named 'mcp.server.fastmcp'` | MCP SDK 2.x installed → reinstall with `"mcp<2"` (step 3) |
| `WinError 1005` during install | Installing on the share → use the temporary local copy (step 3) |
| Tool calls time out | REAPER not running, bridge not started, or `REAPER_MCP_BRIDGE_DIR` doesn't match REAPER's resource path (Options → Show REAPER resource path) |
| `/mcp` shows failed | Run the handshake test; anything before the JSON (e.g. `.bashrc` output) breaks it |
| `bash: no job control in this shell` | Interactive bash on the remote side; harmless on stderr, but use `ssh -T` |
| Server can't import modules after moving things | The symlink path changed → it must stay `C:\Program Files\REAPER (x64)\total-reaper-mcp` |
| `git pull` complains about `.venv` | The upstream repo tracks `.venv` folders, so they collide with the local venv (see below) |

## Updating

- **Code only:** `git pull` on Linux, then restart Claude Code. Nothing to do on Windows.
- **Dependencies changed:** remove the symlink (`cmd /c rmdir "C:\Program Files\REAPER (x64)\total-reaper-mcp"`,
  which removes only the link), then repeat step 3.
- **`lua/mcp_bridge.lua` changed:** copy it to REAPER's Scripts folder again and restart REAPER.

**Note on `git pull` and `.venv`:** the upstream repo commits `.venv` and `.venv-new` folders, which overlap
with the local venv. If a pull complains, move `.venv` aside, pull, and move it back. Keep
`run_reaper_mcp.sh` and this file out of git by listing them in `.git/info/exclude`.

Optional server profiles: add `--profile mixing`, `midi-production` or `full` after `server.app`
in the wrapper (the default is `dsl-production`, about 87 tools).