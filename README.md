# Seed Code

**Plant ideas. Grow code.**

Seed Code is a premium, terminal-based AI coding assistant with five fully
independent backends — [OpenRouter](https://openrouter.ai) (full catalogue,
free/paid filtering), **FreeModel Claude** and **FreeModel Codex**
(free AI models from [freemodel.dev](https://freemodel.dev)),
[AeroLink](https://aerolink.lat), and local [Ollama](https://ollama.com).
It feels like a real developer tool — fast, minimal, and professional — in
the spirit of Claude Code, the Gemini CLI, Ollama, and Git.

```
 ███████╗███████╗███████╗██████╗      ██████╗ ██████╗ ██████╗ ███████╗
 ██╔════╝██╔════╝██╔════╝██╔══██╗    ██╔════╝██╔═══██╗██╔══██╗██╔════╝
 ███████╗█████╗  █████╗  ██║  ██║    ██║     ██║   ██║██║  ██║█████╗
 ╚════██║██╔══╝  ██╔══╝  ██║  ██║    ██║     ██║   ██║██║  ██║██╔══╝
 ███████║███████╗███████╗██████╔╝    ╚██████╗╚██████╔╝██████╔╝███████╗
 ╚══════╝╚══════╝╚══════╝╚═════╝      ╚═════╝ ╚═════╝ ╚═════╝ ╚══════╝

                         S E E D   C O D E
                      Plant ideas. Grow code.
```

## Features

- **Five independent AI providers, one CLI** — switch anytime with
  `/provider`; each provider owns its API key, model, connection status,
  client, and even its own history, so switching never loses anything:
  - **OpenRouter** — two modes on one key: **Free Models** (default) or
    **Pro Models**; switch with `free`/`pro` in the model picker or
    `/settings mode free|pro`.
  - **FreeModel Claude** — Claude API at cc.freemodel.dev; Claude-family
    models (live catalogue with a maintained fallback list). Auto mode
    (`/model auto`) picks the best available model.
  - **FreeModel Codex** — Responses API at api.freemodel.dev; GPT/Codex
    models. The same FreeModel key (fe_oa_...) works on both FreeModel
    providers, but each stores it — and its model — independently.
  - **AeroLink** — Anthropic-compatible gateway; Claude-family models,
    fetched dynamically.
  - **Ollama** — fully local and key-free; lists the models you have
    installed (`/settings host <url>` to point elsewhere).
  - API keys are only ever saved after **real authenticated validation** —
    no format guessing.
- **Startup menu** — banner, current provider/model status, and a numbered
  menu (Start Chat, Provider, API Key, Model, Settings, About, Exit).
  Guided setup runs automatically until configuration is complete.
- **Streaming responses** with live markdown and syntax-highlighted code
  blocks.
- **Windows-first** — verified in Windows Terminal, PowerShell, CMD, and the
  VS Code terminal; one-click installer with PATH integration.
- **Conversation memory** within a session, auto-saved to history.
- **Never crashes** — network and API errors are shown as friendly messages,
  never raw tracebacks. Ctrl+C cancels the current response, not the app.
- **Quiet diagnostics** — a rotating log at `~/.seedcode/logs/seedcode.log`
  (API keys and message content are never logged).

## Install

### Windows (recommended)

Either download and run **`SeedCodeSetup.exe`** from the
[Releases page](https://github.com/Alshahriar-07/seedcode-cli/releases)
(one-click: installs to Program Files, adds `seedcode` to PATH, creates
Start Menu shortcuts — no Python required), or install from source:

```bat
scripts\windows\install.bat
```

To build the standalone exe + installer yourself:

```bat
scripts\windows\build.bat
```

Uninstall with `scripts\windows\uninstall.bat` (add `/keepdata` to preserve
your config and history).

### Any platform (pip)

Requires **Python 3.12+**.

```bash
pip install seedcode-cli
```

(or `pip install .` from a clone). This installs the `seedcode` command
globally. Linux/macOS helper scripts live in `scripts/linux/` and
`scripts/macos/`.

## Usage

```bash
seedcode
```

On first launch you get the menu; choosing **Start Chat** walks through
setup (provider → API key → validate → fetch models → select → save). For
FreeModel, get a free API key at <https://freemodel.dev/dashboard>; for
OpenRouter, create a key at <https://openrouter.ai/keys>; for AeroLink,
use your dashboard at <https://aerolink.lat>; for Ollama, just have
`ollama serve` running.

API keys can also come from environment variables (these override the
stored keys):

```bash
export OPENROUTER_API_KEY="sk-or-..."
export FREEMODEL_API_KEY="fe_oa_..."
export AEROLINK_API_KEY="..."
seedcode
```

## Commands

| Command      | Description                                            |
| ------------ | ------------------------------------------------------ |
| `/help`      | Show available commands                                |
| `/provider`  | Switch provider (OpenRouter/FreeModel Claude/FreeModel Codex/AeroLink/Ollama) |
| `/apikey`    | View, replace, remove, or validate the active key      |
| `/model`     | Browse the live model list ('auto' = FreeModel Auto)   |
| `/config`    | Show configuration (all providers' keys and models)    |
| `/settings`  | Change a setting: `username`, `stream`, `ollama_host`, `max_tokens` |
| `/doctor`    | Diagnose config, network, and provider health          |
| `/agent`     | Toggle agent mode (the AI can read, edit, search, and run commands in your project) |
| `/permission`| Show or set the agent permission mode: `read_only`, `workspace`, `full_access` |
| `/tools`     | List the tools available in agent mode                 |
| `/index`     | Show a compact tree of the current project             |
| `/history`   | List saved conversation sessions                       |
| `/reset`     | Forget the current conversation                        |
| `/clear`     | Clear the screen                                       |
| `/about`     | About Seed Code                                        |
| `/version`   | Show the version                                       |
| `/exit`      | Leave the chat (back to the main menu)                 |

## Configuration

Config lives at `~/.seedcode/config.json` (owner-only permissions where the
OS supports it). Each provider keeps its own entry, so nothing is shared or
overwritten:

```json
{
  "active_provider": "freemodel_claude",
  "providers": {
    "openrouter":       { "api_key": "sk-or-...", "model": "vendor/model" },
    "freemodel_claude": { "api_key": "fe_oa_...", "model": "claude-sonnet-4-6" },
    "freemodel_codex":  { "api_key": "fe_oa_...", "model": "auto" },
    "aerolink":         { "api_key": "...",       "model": "..." },
    "ollama":           { "api_key": "",          "model": "llama3.2" }
  },
  "ollama_host": "http://localhost:11434",
  "max_tokens": 1024
}
```

Chat history is stored per provider under `~/.seedcode/history/<provider>/`.

No model is ever hardcoded — you always pick from the provider's live
catalogue. `max_tokens` defaults to a free-tier-safe 1024 and is clamped to
1–4096 per request (older config formats migrate automatically).

Troubleshooting: check `~/.seedcode/logs/seedcode.log`; set
`SEEDCODE_DEBUG=1` for verbose logging.

## Credits

- **Created by:** Al Shahriar Sowan
- Vibe coded with GPT-5.5 + Claude Opus 4.8

## License

MIT — see [LICENSE](LICENSE).
