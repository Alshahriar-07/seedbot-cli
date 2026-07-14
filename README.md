# Seed Code

**Plant ideas. Grow code.**

Seed Code is a premium, terminal-based AI coding assistant powered by
[OpenRouter](https://openrouter.ai). It feels like a real developer tool —
fast, minimal, and professional — in the spirit of Claude Code, the Gemini CLI,
Ollama, and Git.

```
    ███████╗███████╗███████╗██████╗
    ██╔════╝██╔════╝██╔════╝██╔══██╗
    ███████╗█████╗  █████╗  ██║  ██║
    ╚════██║██╔══╝  ██╔══╝  ██║  ██║
    ███████║███████╗███████╗██████╔╝
    ╚══════╝╚══════╝╚══════╝╚═════╝

             Seed Code v0.1.0
         Plant ideas. Grow code.
```

## Features

- **Zero-config first run** — paste your OpenRouter key once; it's validated and
  stored locally under `~/.seedcode`.
- **Streaming responses** with live markdown and syntax-highlighted code blocks.
- **Conversation memory** within a session, auto-saved to history.
- **Slash commands**: `/help`, `/model`, `/config`, `/history`, `/reset`,
  `/clear`, `/about`, `/version`, `/exit`.
- **Never crashes** — network and API errors are shown as friendly messages,
  never raw tracebacks.

## Install

Requires **Python 3.12+**.

```bash
pip install .
```

This installs the `seedcode` command globally.

## Usage

```bash
seedcode
```

On first launch you'll be asked for your OpenRouter API key
(get one at <https://openrouter.ai/keys>). After that, just start chatting.

You can also supply the key via environment variable:

```bash
export OPENROUTER_API_KEY="sk-or-..."
seedcode
```

## Commands

| Command      | Description                         |
| ------------ | ----------------------------------- |
| `/help`      | Show available commands             |
| `/model`     | Show or change the active model     |
| `/config`    | Show current configuration          |
| `/history`   | List saved conversation sessions    |
| `/reset`     | Forget the current conversation     |
| `/clear`     | Clear the screen                    |
| `/about`     | About Seed Code                     |
| `/version`   | Show the version                    |
| `/exit`      | Quit                                |

## Configuration

Config lives at `~/.seedcode/config.json` (owner-only permissions where the OS
supports it). Default model: `z-ai/glm-5.2`, provider: OpenRouter.

## Credits

- **Developer:** Al shahriar sowan
- Concept & coding assistance: ChatGPT
- Development assistance: Claude Code

## License

MIT — see [LICENSE](LICENSE).
