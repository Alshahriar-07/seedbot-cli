# Assist Mode Implementation

## Overview

Replaced the separate Agent Mode and Desktop Mode toggles with a unified **Assist Mode** that enables all AI capabilities at once. Fixed the critical "No response" bug that affected desktop automation workflows.

## What Changed

### 1. Fixed "No response" Bug

**File**: `seedcode/core/agent.py`

**Root Cause**: When the AI model completed tool calls (filesystem, desktop, etc.) without emitting a final text summary, `run_turn()` returned an empty string, causing the UI to display `"(no response)"` instead of showing that work was completed.

**Fix**: Modified `run_turn()` to return `"Done."` when the final reply is empty:

```python
calls = parse_tool_calls(reply)
if not calls:
    self.add_assistant(reply)
    final = reply.strip()
    # Some models complete tool work without emitting a summary line.
    # Return a minimal acknowledgement so the UI never shows "(no response)".
    return final if final else "Done."
```

This ensures users always see feedback when the agent completes actions, especially in desktop automation scenarios where the model acts without narrating.

### 2. Created Unified Assist Mode

**File**: `seedcode/commands/assist.py` (new)

**Command**: `/assist on|off`

**What it does**:
- `/assist on` — Enables agent mode (filesystem, terminal, git, search, patch) AND desktop mode (mouse, keyboard, screen, windows, browser) together
- `/assist off` — Disables both modes, returning to plain chat
- `/assist` (bare) — Shows current status and available capabilities

**Benefits**:
- One command instead of toggling `/agent` and `/desktop` separately
- Clear status display showing what tools are available
- Handles Computer Engine availability gracefully (shows desktop as unavailable if not installed)
- Sets reasonable defaults (workspace permission mode)

### 3. Registered New Command

**File**: `seedcode/commands/__init__.py`

Added `assist` to the import list so the command is automatically registered when the module loads.

## Architecture

### Unified Execution Pipeline

All tools now flow through the same execution pipeline:

```
User Request
    ↓
AgentEngine.run_turn()
    ↓
Model reasons + chooses tools
    ↓
parse_tool_calls() extracts ```tool blocks
    ↓
PermissionManager.check_*() gates access
    ↓
Tool.run() executes action
    ↓
ToolResult feeds back to model
    ↓
Model responds (or calls more tools)
    ↓
Final response to user
```

### Tool Groups

**Core tools** (always available in agent mode):
- `read_file`, `write_file`, `list_files`, `create_file`, `delete_file`
- `run_command` (terminal)
- `git_status`, `git_diff`, `git_log`, `git_commit`, `git_push`
- `search_files`, `grep_content`
- `apply_patch`

**Desktop tools** (available when Computer Engine is installed):
- `desktop_type`, `desktop_key`, `desktop_click`, `desktop_scroll`
- `desktop_screenshot`, `desktop_see` (vision-enabled screen capture)
- `window_list`, `window_focus`, `window_info`
- `browser_navigate`, `browser_action`, `browser_state`

All tools use the same:
- Permission system (`PermissionManager`)
- Result format (`ToolResult`)
- Error handling (`ToolError`, `PermissionError_`)
- Execution loop (AgentEngine)

## Permission System

When `/assist on` is called:
- Default permission mode: **workspace** (safe default)
- Desktop actions prompt per-action: `[Y] Once  [A] Always (session)  [N] Deny`
- Users can change with `/permission read_only|workspace|full_access`

Permission levels:
- **read_only** — Inspect files, no mutations
- **workspace** — Read anywhere, mutate only inside workspace directory
- **full_access** — No path restrictions on mutations

## Verification

Run the verification script:

```bash
python verify_assist.py
```

Expected checks:
- ✓ Assist command imports successfully
- ✓ /assist registered in command registry
- ✓ AgentEngine creates without errors
- ✓ Core and desktop tool groups populated
- ✓ Computer Engine availability detected
- ✓ "No response" bug fix verified

## Manual Testing

1. Start Seed Code:
   ```bash
   python -m seedcode
   ```

2. Check status:
   ```
   /assist
   ```
   Should show: status table with agent/desktop availability

3. Enable Assist Mode:
   ```
   /assist on
   ```
   Should show: success message + capability table

4. Test filesystem tools:
   ```
   Create a test file called example.txt with "Hello from Assist Mode"
   ```
   Should: create file, show "Done." or brief summary

5. Test desktop tools (if available):
   ```
   Take a screenshot and save it to screenshot.png
   ```
   Should: capture screen, show result path, no "(no response)"

6. Disable:
   ```
   /assist off
   ```
   Should: disable both modes, return to chat

## Backward Compatibility

The original commands still work:
- `/agent on|off` — Agent mode only
- `/desktop on|off` — Desktop mode only (requires agent mode)
- `/permission <mode>` — Change permission level

Users can mix `/assist` with the granular commands if needed, but `/assist` is now the recommended entry point.

## Files Modified

1. **seedcode/core/agent.py**
   - Fixed `run_turn()` to return "Done." instead of empty string

2. **seedcode/commands/assist.py** (new)
   - Implemented `/assist on|off` command
   - Status display with capability table
   - Unified enable/disable logic

3. **seedcode/commands/__init__.py**
   - Registered `assist` command

4. **verify_assist.py** (new)
   - Verification script for implementation

## Related Documentation

- **IDENTITY_SYSTEM.md** — How the AI identifies itself across providers
- **STARTUP_FIX.md** — Resolution of import errors during refactor
- **Info_for_ai_agents/Memory.md** — System architecture notes

## Known Limitations

1. **Desktop Mode requires Computer Engine**: If `pywinauto`, `pillow`, or `keyboard` packages are missing, desktop tools are unavailable. The `/assist` command handles this gracefully by showing desktop as unavailable.

2. **Windows only**: Desktop automation currently uses Windows-specific libraries. Linux/macOS support would require cross-platform abstractions.

3. **Vision model requirement**: Desktop screenshots (`desktop_see`) require a vision-capable model. When using non-vision models, screenshots are taken but not attached to the conversation.

## Future Enhancements

- [ ] Add `/assist permission <mode>` shorthand
- [ ] Add tool usage statistics to `/assist` status
- [ ] Cross-platform desktop support (Linux, macOS)
- [ ] Browser automation beyond basic navigation
- [ ] Multi-monitor support for screenshots
