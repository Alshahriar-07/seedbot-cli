# Seed Code — Windows Installation Scripts

Production scripts for installing, building, packaging, and removing Seed Code
on Windows (the primary platform).

| File | Purpose |
|------|---------|
| `install.bat` | Install Seed Code from source: Python 3.12+ check, pip upgrade, dependencies, editable install, verification. |
| `build.bat` | **Complete release pipeline**: branding assets → PyInstaller → `dist\seedcode.exe` (Seed Code icon embedded), then Inno Setup → `Release\SeedCodeSetup.exe`. Every stage verified. |
| `build_assets.py` | Generates `assets\windows\` (multi-resolution `seedcode.ico`, wizard bitmaps, exe version resource) — stdlib only, deterministic, self-verifying. |
| `setup.iss` | Inno Setup script (compiled by `build.bat`): one-click branded wizard, Program Files install, PATH, shortcuts, double verification (exe + `seedcode` on PATH), uninstaller with data prompt. No Python needed on the user's PC. |
| `uninstall.bat` | Remove a source install: PATH cleanup, `pip uninstall`, confirmed user-data deletion. |
| `README.md` | This document. |

---

## 1. Installing (end users)

From the repository root (or anywhere — the script finds the repo relative to
itself):

```bat
scripts\windows\install.bat
```

The installer:

1. Looks for **Python 3.12+** (tries `py -3.13`, `py -3.12`, `py -3`,
   `python`, `python3`). If none qualifies, it **opens
   <https://www.python.org/downloads/>** and exits with code 2.
2. Upgrades `pip`.
3. Installs dependencies from `requirements.txt`.
4. Installs Seed Code in editable mode (`pip install -e .`).
5. Verifies the package imports and reports where the `seedcode` command
   landed. Clear `[SUCCESS]` / `[ERROR]` messages either way.

A full log is appended to `%USERPROFILE%\.seedcode\logs\install.log`.

> If `seedcode` is not recognized immediately, open a **new** terminal —
> PATH changes only apply to fresh sessions.

## 2. Release pipeline (`build.bat`)

```bat
scripts\windows\build.bat
```

Runs the complete, hands-off release pipeline:

1. **Stage 0 — Branding.** `build_assets.py` generates the multi-resolution
   Seed Code icon (16–256 px), the wizard side/header bitmaps, and the exe
   version resource (publisher/product shown in Explorer). The icon is
   structurally verified before anything is built with it.
2. **Stage 1 — PyInstaller.** Ensures PyInstaller + project dependencies,
   **runs the full test suite as a release gate** (a failing test stops the
   pipeline), builds the one-file console executable **with the Seed Code
   icon and version resource embedded**, then verifies it twice: `--version`
   must report exactly the source version, and the icon payload must be
   present inside the binary. `dist\seedcode.exe`
3. **Stage 2 — Inno Setup.** Locates `ISCC.exe` (PATH, then the standard
   per-user and Program Files locations) and compiles `setup.iss`, then
   verifies the installer also embeds the icon:
   `Release\SeedCodeSetup.exe`

Log: `%USERPROFILE%\.seedcode\logs\build.log`. The `build\` work directory is
disposable cache; `dist\` and `Release\` are the outputs.

## 3. The public installer (`Release\SeedCodeSetup.exe`)

**True one-click install.** The end user downloads one file, runs it, and
accepts the defaults: License → Install → Finish. Nothing else — no Python,
no pip, no PATH editing, no terminal work. The packaged exe carries its own
Python runtime and every dependency inside it.

- **Branding everywhere.** The setup.exe, the installed seedcode.exe, the
  Start Menu / Desktop shortcuts, the taskbar, Explorer, and Add/Remove
  Programs all show the Seed Code icon — the default Python icon never
  appears (the icon is embedded in the exe by PyInstaller AND pinned on
  every shortcut by Inno Setup).
- **Zero prerequisites.** The installer refuses to even compile without the
  bundled standalone exe, and it never detects, downloads, or requires
  Python on the user's machine.
- Installs the self-contained `seedcode.exe` into **Program Files**.
- Adds the install directory to the **system PATH** (and broadcasts the
  change, so new CMD/PowerShell/Windows Terminal sessions pick it up).
- Creates **Start Menu** shortcuts and an optional **Desktop** shortcut.
- **Verifies twice** before claiming success: (1) the installed exe must
  report exactly the installer's own version; (2) the bare `seedcode`
  command must resolve and answer through PATH exactly as a **new terminal**
  will see it. Either failure aborts with a clear, specific error message.
- Offers to **launch Seed Code** on finish — a fresh machine gets the full
  first-run onboarding (choose provider → API key → model), with nothing
  preconfigured.
- Ships a full uninstaller that removes the exe, shortcuts, and PATH entry,
  then **asks** whether to also delete settings, API keys, chat history, and
  logs (`%USERPROFILE%\.seedcode`) — never silently.

After installation, from any directory in any new terminal:

```
C:\Users\You> seedcode
```

No `cd`, no venv, no `python`, no `pip` — just `seedcode`.

## 4. Uninstalling

```bat
scripts\windows\uninstall.bat
```

Removes any `seedcode` entries from the **user** PATH, uninstalls the Python
package, and asks before deleting user data at `%USERPROFILE%\.seedcode`.
Pass `/keepdata` to skip the user-data step entirely. If Seed Code was
installed via `SeedCodeSetup.exe`, prefer **Settings → Apps** (the Inno
uninstaller also reverts its PATH change).

---

## Exit codes

| Code | Meaning |
|------|---------|
| 0 | Success. |
| 1 | A pip/PyInstaller/ISCC/asset step failed (see the log). |
| 2 | Python 3.12+ not found. |
| 3 | Script is not inside the Seed Code repository. |
| 4 | Inno Setup 6 (ISCC.exe) not found (build.bat stage 2). |
| 5 | Verification failed: stale/locked output, version mismatch, or missing icon. |
