#!/bin/bash
export REAPER_MCP_BRIDGE_DIR='C:/Users/Jakub/AppData/Roaming/REAPER/Scripts/mcp_bridge_data'
export PYTHONUNBUFFERED=1
export PYTHONDONTWRITEBYTECODE=1

# Go to reaper and total-reaper-mcp
cd "/cygdrive/c/Program Files/REAPER (x64)/total-reaper-mcp"

# Start the server
exec ./.venv/Scripts/python.exe -m server.app
