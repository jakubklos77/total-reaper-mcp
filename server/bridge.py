"""
REAPER File Bridge - Shared communication module

This module provides the file-based bridge for communicating with REAPER.
It's shared across all tool modules to maintain a single connection point.
"""

import os
import json
import asyncio
import logging
import time
from pathlib import Path
from typing import Optional, List, Dict, Any

logger = logging.getLogger(__name__)

# Bridge directory configuration
BRIDGE_DIR = Path(os.environ.get(
    'REAPER_MCP_BRIDGE_DIR',
    os.path.expanduser('~/Library/Application Support/REAPER/Scripts/mcp_bridge_data')
))
BRIDGE_DIR.mkdir(parents=True, exist_ok=True)

# ReaScript logging configuration
REASCRIPT_LOGGING_ENABLED = os.environ.get('REASCRIPT_LOGGING', '').lower() in ('1', 'true', 'yes')
REASCRIPT_LOG_FILE = Path(os.environ.get(
    'REASCRIPT_LOG_FILE',
    '/tmp/reascript_calls.jsonl'
))

class ReaperFileBridge:
    """File-based bridge for communicating with REAPER"""
    
    def __init__(self):
        self.bridge_dir = BRIDGE_DIR
        self.request_id = 0
        self.call_tracking = []  # Track calls during operations
        self.tracking_enabled = False
        # The Lua bridge scans NUMERIC request_<i>.json files, so ids must stay
        # numeric — we can't namespace the filename. Instead, purge stale
        # request/response files left over from a previous server run or from
        # timed-out calls: a lingering response_<id>.json would otherwise be
        # read as the answer to a brand-new same-id request after the in-memory
        # counter resets on restart (the sticky "Failed to get tracks info"
        # desync). Also start the counter high to avoid colliding with any
        # low-numbered leftovers a still-draining bridge might yet emit.
        self._purge_stale_files()

    def _purge_stale_files(self):
        try:
            for f in self.bridge_dir.glob('request_*.json'):
                f.unlink(missing_ok=True)
            for f in self.bridge_dir.glob('response_*.json'):
                f.unlink(missing_ok=True)
        except Exception as e:
            logger.debug(f"Bridge dir purge skipped: {e}")
        
    async def call_lua(self, func_name: str, args: Optional[List[Any]] = None) -> Dict[str, Any]:
        """Call a Lua function and wait for response"""
        self.request_id += 1
        request_file = self.bridge_dir / f"request_{self.request_id}.json"
        response_file = self.bridge_dir / f"response_{self.request_id}.json"

        # Clean slate for this id: drop any stale request/response left from a
        # previous (timed-out) call so we never read an old answer as ours.
        request_file.unlink(missing_ok=True)
        response_file.unlink(missing_ok=True)

        # Write request
        request_data = {
            "id": self.request_id,
            "func": func_name,
            "args": args or []
        }
        
        # Track call start time for performance logging
        call_start_time = time.time()
        
        # Log ReaScript call if enabled
        if REASCRIPT_LOGGING_ENABLED:
            log_entry = {
                "timestamp": call_start_time,
                "request_id": self.request_id,
                "type": "call",
                "function": func_name,
                "args": args or [],
                "dsl_tool": os.environ.get('CURRENT_DSL_TOOL', 'unknown')
            }
            try:
                with open(REASCRIPT_LOG_FILE, 'a') as f:
                    f.write(json.dumps(log_entry) + '\n')
            except Exception as e:
                logger.debug(f"Failed to log ReaScript call: {e}")
        
        try:
            with open(request_file, 'w') as f:
                json.dump(request_data, f)
            
            # Wait for response (with timeout). Configurable via env — heavy
            # ops (bulk MIDI insert of hundreds of notes) can exceed the old
            # hard 5 s and spuriously "time out" while the bridge is still busy.
            start_time = asyncio.get_event_loop().time()
            try:
                timeout = float(os.environ.get('REAPER_MCP_TIMEOUT', '15'))
            except ValueError:
                timeout = 15.0
            
            while asyncio.get_event_loop().time() - start_time < timeout:
                if response_file.exists():
                    try:
                        with open(response_file, 'r') as f:
                            response = json.load(f)
                        # Clean up files
                        request_file.unlink(missing_ok=True)
                        response_file.unlink(missing_ok=True)
                        
                        # Track call if tracking is enabled
                        if self.tracking_enabled:
                            duration_ms = (time.time() - call_start_time) * 1000
                            self.call_tracking.append({
                                "timestamp": call_start_time,
                                "function": func_name,
                                "args": args or [],
                                "response": response,
                                "duration_ms": duration_ms,
                                "success": response.get("ok", False)
                            })
                        
                        # Log ReaScript response if enabled
                        if REASCRIPT_LOGGING_ENABLED:
                            duration_ms = (time.time() - call_start_time) * 1000
                            log_entry = {
                                "timestamp": time.time(),
                                "request_id": self.request_id,
                                "type": "response",
                                "function": func_name,
                                "response": response,
                                "duration_ms": duration_ms,
                                "success": response.get("ok", False),
                                "dsl_tool": os.environ.get('CURRENT_DSL_TOOL', 'unknown')
                            }
                            try:
                                with open(REASCRIPT_LOG_FILE, 'a') as f:
                                    f.write(json.dumps(log_entry) + '\n')
                            except Exception as e:
                                logger.debug(f"Failed to log ReaScript response: {e}")
                        
                        return response
                    except json.JSONDecodeError:
                        # File might be partially written, wait a bit
                        await asyncio.sleep(0.01)
                await asyncio.sleep(0.1)
            
            # Timeout — remove BOTH files so a late-arriving response for this
            # id can't be mis-read by a future same-id request.
            request_file.unlink(missing_ok=True)
            response_file.unlink(missing_ok=True)
            logger.error("Timeout waiting for REAPER response")
            timeout_response = {"ok": False, "error": "Timeout waiting for REAPER response"}
            
            # Track timeout if tracking is enabled
            if self.tracking_enabled:
                duration_ms = (time.time() - call_start_time) * 1000
                self.call_tracking.append({
                    "timestamp": call_start_time,
                    "function": func_name,
                    "args": args or [],
                    "response": timeout_response,
                    "duration_ms": duration_ms,
                    "success": False,
                    "timeout": True
                })
            
            # Log timeout if enabled
            if REASCRIPT_LOGGING_ENABLED:
                duration_ms = (time.time() - call_start_time) * 1000
                log_entry = {
                    "timestamp": time.time(),
                    "request_id": self.request_id,
                    "type": "timeout",
                    "function": func_name,
                    "duration_ms": duration_ms,
                    "dsl_tool": os.environ.get('CURRENT_DSL_TOOL', 'unknown')
                }
                try:
                    with open(REASCRIPT_LOG_FILE, 'a') as f:
                        f.write(json.dumps(log_entry) + '\n')
                except Exception as e:
                    logger.debug(f"Failed to log ReaScript timeout: {e}")
            
            return timeout_response
            
        except Exception as e:
            logger.error(f"Bridge error: {e}")
            error_response = {"ok": False, "error": str(e)}
            
            # Track error if tracking is enabled
            if self.tracking_enabled:
                duration_ms = (time.time() - call_start_time) * 1000
                self.call_tracking.append({
                    "timestamp": call_start_time,
                    "function": func_name,
                    "args": args or [],
                    "response": error_response,
                    "duration_ms": duration_ms,
                    "success": False,
                    "error": str(e)
                })
            
            # Log error if enabled
            if REASCRIPT_LOGGING_ENABLED:
                duration_ms = (time.time() - call_start_time) * 1000
                log_entry = {
                    "timestamp": time.time(),
                    "request_id": self.request_id,
                    "type": "error",
                    "function": func_name,
                    "error": str(e),
                    "duration_ms": duration_ms,
                    "dsl_tool": os.environ.get('CURRENT_DSL_TOOL', 'unknown')
                }
                try:
                    with open(REASCRIPT_LOG_FILE, 'a') as f:
                        f.write(json.dumps(log_entry) + '\n')
                except Exception as e:
                    logger.debug(f"Failed to log ReaScript error: {e}")
            
            return error_response
    
    def start_tracking(self):
        """Start tracking ReaScript calls"""
        self.tracking_enabled = True
        self.call_tracking = []
    
    def stop_tracking(self):
        """Stop tracking and return collected calls"""
        self.tracking_enabled = False
        calls = self.call_tracking.copy()
        self.call_tracking = []
        return calls
    
    def get_tracked_calls(self):
        """Get tracked calls without clearing"""
        return self.call_tracking.copy()

# Singleton instance
bridge = ReaperFileBridge()