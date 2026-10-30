# Phi Agent

![Phi Agent](assets/banner.png)

Phi Agent is developed by Phi Lab Foundation. It is derived from [Hermes Agent](https://github.com/NousResearch/hermes-agent) by Nous Research, used under the MIT License, and keeps the original copyright and author credits.

Phi Agent is a personal AI agent that works where you do: in your terminal, in a web dashboard, and in the chat apps you already use. It remembers what it learns, turns repeated work into reusable skills, runs jobs on a schedule, and hands parallel work to subagents. Bring any model. Keep your data on your own machine.

## Highlights

- **One agent, every surface.** A command line, a full terminal UI, a web dashboard and a messaging gateway share one agent core, one memory and one skill library.
- **20+ messaging platforms.** Telegram, Discord, Slack, Matrix, Signal, WhatsApp, Microsoft Teams, email, SMS and more, all from a single gateway.
- **Any model.** 40+ model providers, including Anthropic, OpenAI, Google Gemini, OpenRouter and LM Studio, plus any OpenAI-compatible endpoint such as your own local server.
- **Learns as it works.** Persistent memory, 58 built-in skills, more than 150 optional skills, and new skills it writes from its own experience.
- **Talks naturally while it works.** Phi's busy router reads every message that arrives mid-task and decides on the spot: answer a quick question on the side, start a new task in the background, queue the next step, or pass a correction straight to the running task. It is on by default.
- **Voice calls on Matrix.** An optional plugin lets you call Phi from Element X and talk a task through, using your own speech recognition and voice services.
- **Automation built in.** A cron scheduler that delivers results to any connected chat, subagent delegation, and isolated profiles for separate identities and workspaces.
- **Runs where you choose.** Tools execute locally, in Docker, over SSH, or in Modal, Daytona and Vercel sandboxes.
- **Extensible.** A plugin system, a catalog of 760+ community plugins, and 66 ready-to-add MCP servers.
- **Private by default.** Usage metrics stay off unless you opt in.

## Install

Phi Agent installs from source. You need git, [uv](https://docs.astral.sh/uv/), Python 3.11 to 3.14 (3.14 recommended) and Node.js 22.22+, 24.11+ or 26+.

The web dashboard is built with the Phi UI library, so clone both repositories side by side:

```sh
git clone https://github.com/PhicoinProject/phi-agent.git
git clone https://github.com/PhicoinProject/phi-ui.git

# Build the UI library
(cd phi-ui && npm install --ignore-scripts && npm run build)

# Install Phi Agent and build its interfaces
cd phi-agent
uv sync --locked --python 3.14 --extra all --extra matrix --extra web
npm ci --ignore-scripts
(cd web && npm run build)
npm run build --workspace ui-tui
```

Then activate the environment and pick a model:

```sh
source .venv/bin/activate
phi setup
```

## Use

```sh
phi --tui            # full terminal UI
phi --cli            # classic command line
phi dashboard        # web dashboard on http://127.0.0.1:9119
phi gateway setup    # connect Telegram, Discord, Slack, Matrix and more
phi gateway run      # run the messaging gateway in the foreground
phi profile create work   # a separate identity with its own memory and settings
```

The first start downloads a few runtime tools, so it needs internet access once. Settings live in `~/.phi/config.yaml` and secrets in `~/.phi/.env`. To update, pull both repositories and repeat the install steps.

### Busy router

The busy router asks your current chat model for each decision, with reasoning turned off so it answers in a moment. To use a dedicated decision model instead, point it at any OpenAI-compatible endpoint:

```yaml
plugins:
  entries:
    busy-router:
      settings:
        endpoint: http://127.0.0.1:8000/v1/chat/completions
        decision_model: your-decision-model
```

Add `busy-router` to `plugins.disabled` to turn it off.

## Documentation

Guides for every feature live in [website/docs](website/docs).

## Security

Report vulnerabilities privately to **ai@philab.fund**. See [SECURITY.md](SECURITY.md).

## License

MIT. Copyright © 2026 Phi Lab Foundation. Phi Agent is derived from Hermes Agent by Nous Research and keeps its original license and author credits. See [LICENSE](LICENSE) and [NOTICE](NOTICE).
