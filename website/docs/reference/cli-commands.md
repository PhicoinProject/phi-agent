---
sidebar_position: 1
title: "CLI Commands Reference"
description: "Authoritative reference for Phi terminal commands and command families"
---

# CLI Commands Reference

Python dependency commands on this page use a
[PM-prepared source checkout](./package-management.md#developer-workflow).
After a dependency change, reactivate the checkout and restart Phi.

This page covers the **terminal commands** you run from your shell.

For in-chat slash commands, see [Slash Commands Reference](./slash-commands.md).

## Global entrypoint

```bash
phi [global-options] <command> [subcommand/options]
```

### Global options

| Option | Description |
|--------|-------------|
| `--version`, `-V` | Show version and exit. |
| `--profile <name>`, `-p <name>` | Select which Phi profile to use for this invocation. Overrides the sticky default set by `phi profile use`. |
| `--resume <session>`, `-r <session>` | Resume a previous session by ID or title. The keyword `latest` resumes the most recent session (workspace-scoped, same lookup as `-c`). |
| `--continue [name]`, `-c [name]` | Resume the most recent session, or the most recent session matching a title. |
| `--in <dir>` | Change into `<dir>` before starting or resuming. Scopes `--resume latest` / `-c` lookups to that directory's workspace and keeps the session there (skips the recorded-cwd restore). |
| `--worktree`, `-w` | Start in an isolated git worktree for parallel-agent workflows. |
| `--yolo` | Bypass dangerous-command approval prompts. |
| `--pass-session-id` | Include the session ID in the agent's system prompt. |
| `--ignore-user-config` | Ignore `~/.phi/config.yaml` and fall back to built-in defaults. Credentials in `.env` are still loaded. |
| `--ignore-rules` | Skip auto-injection of `AGENTS.md`, `SOUL.md`, `.cursorrules`, memory, and preloaded skills. |
| `--tui` | Launch the [TUI](../user-guide/tui.md) instead of the classic CLI. Equivalent to `PHI_TUI=1`. Always wins over `display.interface`. |
| `--cli` | Force the classic prompt_toolkit REPL. Use this to override `display.interface: tui` for a single invocation. |
| `--dev` | With `--tui`: run the TypeScript sources directly via `tsx` instead of the prebuilt bundle (for TUI contributors). |

### `phi-agent` (legacy single-query runner)

The install also ships `phi-agent`, a minimal runner that sends one query and exits: `phi-agent --query "summarize README.md"` (or `phi-agent "summarize README.md"`). `phi-agent --help` lists its options (`--model`, `--base-url`, `--max-turns`, `--enabled-toolsets`, `--disabled-toolsets`, `--list-tools`, `--save-trajectories`, …) and `phi-agent --version` prints the version; neither starts the agent. Run with no query, it prints the same help and exits. For anything else use `phi` (`phi -z <prompt>` is the scripted one-shot).

## Top-level commands

| Command | Purpose |
|---------|---------|
| `phi chat` | Interactive or one-shot chat with the agent. |
| `phi model` | Interactively choose the default provider and model. |
| `phi moa` | Configure named Mixture of Agents presets selectable from the model picker. |
| `phi fallback` | Manage fallback providers tried when the primary model errors. |
| `phi gateway` | Run or manage the messaging gateway service. |
| `phi proxy` | Local OpenAI-compatible proxy that attaches OAuth provider credentials. See [Subscription Proxy](../user-guide/features/subscription-proxy.md). |
| `phi egress` | Outbound credential-injection firewall for remote terminal sandboxes (iron-proxy). Disabled by default. See [Egress proxy](../user-guide/egress/iron-proxy.md). |
| `phi lsp` | Manage Language Server Protocol integration (semantic diagnostics for write_file/patch). |
| `phi setup` | Interactive setup wizard for all or part of the configuration. |
| `phi whatsapp` | Configure and pair the WhatsApp bridge. |
| `phi whatsapp-cloud` | Configure the official Meta WhatsApp Business Cloud API adapter (Business account + public webhook required). Distinct from `phi whatsapp` (Baileys personal-account bridge). |
| `phi slack` | Slack helpers (currently: generate the app manifest with every command as a native slash). |
| `phi auth` | Manage credentials — add, list, remove, reset, status, logout. Handles OAuth flows for Codex/Nous/Anthropic. |
| `phi login` / `logout` | **Deprecated** — use `phi auth` instead. |
| `phi send` | Send a one-shot message to a configured messaging platform (Telegram, Discord, Slack, Signal, SMS, …). Useful from shell scripts, cron jobs, CI hooks, and monitoring daemons — no agent loop, no LLM. |
| `phi peer` | Register peer Phi gateways on other machines and DM their agents' canonical Bot Chats (`phi peer dm <peer>[/<agent>] "…"`). The transport behind cross-machine bot-to-bot messaging. |
| `phi secrets` | Manage external secret sources (currently Bitwarden Secrets Manager) for pulling API keys at process startup instead of from `~/.phi/.env`. |
| `phi migrate` | Diagnose and (optionally) rewrite `config.yaml` to replace references to retired models or deprecated settings (e.g. `migrate xai`). |
| `phi codex-runtime` | Noninteractive counterpart of `/codex-runtime`: `migrate [--dry-run] [--json]` regenerates the Phi-managed block in `~/.codex/config.toml` for the selected profile. See [Codex app-server runtime](../user-guide/features/codex-app-server-runtime.md#running-the-migration-from-a-script). |
| `phi status` | Show agent, auth, and platform status. |
| `phi usage` | Show the configured account's rate-limit windows (the `/usage` block) without a session; `--json` for scripts. |
| `phi cron` | Inspect and tick the cron scheduler. |
| `phi pause` / `phi resume` | Global emergency stop: no new cron fires (built-in ticker, managed-cron webhook, misfire catch-up), kanban dispatch or gateway turns start until resumed. Interactive CLI, TUI and Desktop turns are gateway turns, so they are held too, and each surface shows "Phi is paused" with the reason and "run `phi resume`". Turns already running finish; in-flight work is never killed. |
| `phi kanban` | Multi-profile collaboration board (tasks, links, dispatcher). |
| `phi project` | Manage named, multi-folder workspaces (projects). Anchors desktop session grouping and, when bound to a kanban board, gives tasks a deterministic worktree + branch convention. State is per-profile. |
| `phi webhook` | Manage dynamic webhook subscriptions for event-driven activation. |
| `phi hooks` | Inspect, approve, or remove shell-script hooks declared in `config.yaml`. |
| `phi doctor` | Diagnose config and dependency issues. |
| `phi security audit` | On-demand supply-chain audit (OSV.dev) for the venv, plugin requirements, and pinned MCP servers. |
| `phi approvals` | Approval-prompt tools — mine approval history into allowlist proposals. |
| `phi dump` | Copy-pasteable setup summary for support/debugging. |
| `phi prompt-size` | Show a byte breakdown of the system prompt + tool schemas (skills index, memory, profile). Runs offline. |
| `phi debug` | Debug tools — upload logs and system info for support. |
| `phi backup` | Back up Phi home directory to a zip file. |
| `phi checkpoints` | Inspect / prune / clear `~/.phi/checkpoints/` (the shadow store used by `/rollback`). Run with no args for a status overview. |
| `phi import` | Restore a Phi backup from a zip file. |
| `phi logs` | View, tail, and filter agent/gateway/error log files. |
| `phi config` | Show, edit, migrate, and query configuration files. |
| `phi skin` | List, switch, and tweak display skins. |
| `phi console` | Open the safe Phi command console. |
| `phi pairing` | Approve or revoke messaging pairing codes. |
| `phi skills` | Browse, install, publish, audit, and configure skills. |
| `phi bundles` | Group several skills under a single `/<name>` slash command. See [Skill Bundles](../user-guide/features/skills.md#skill-bundles). |
| `phi curator` | Background skill maintenance — status, run, pause, pin. See [Curator](../user-guide/features/curator.md). |
| `phi journey` (aliases `learning`, `memory-graph`) | Timeline of learned skills + memories over time. |
| `phi memory` | Configure external memory provider. Plugin-specific subcommands (e.g. `phi honcho`) register automatically when their provider is active. |
| `phi acp` | Run Phi as an ACP server for editor integration. |
| `phi mcp` | Manage MCP server configurations. Running Phi as an MCP server is the [mcp-serve plugin](../user-guide/features/mcp.md#running-phi-as-an-mcp-server). |
| `phi connectors` | List, connect, rename and disconnect hosted connector accounts. |
| `phi plugins` | Manage Phi Agent plugins (install, enable, disable, remove). |
| `phi portal` | Nous Portal status, subscription link, and Tool Gateway routing. See [Tool Gateway](../user-guide/features/tool-gateway.md). |
| `phi tools` | Configure enabled tools per platform. |
| `phi computer-use` | Install or check the Computer Use (cua-driver) backend (macOS/Windows/Linux). |
| `phi pets` | Browse, install, and select [petdex](../user-guide/features/pets.md) animated pets shown across the CLI, TUI, and desktop app. Subcommands: `list`, `install`, `select`, `show`, `off`, `scale`, `remove`, `doctor`. |
| `phi sessions` | Browse, export, prune, rename, and delete sessions. |
| `phi insights` | Show token/cost/activity analytics. |
| `phi claw` | OpenClaw migration (`migrate`, `cleanup`), from the [`agent-importers`](../user-guide/import-from-other-agents.md) plugin; `phi claw migrate` is the same as `phi import-agent openclaw`. |
| `phi import-agent` | Import an OpenClaw, Claude Code, Codex CLI or Cursor setup (from the [`agent-importers`](../user-guide/import-from-other-agents.md) plugin). |
| `phi dashboard` | Launch the web dashboard for managing config, API keys, and sessions. |
| `phi serve` | Start the Phi backend server (headless; powers the desktop app and remote backends). |
| `phi desktop` (alias `gui`) | Build and launch the native Electron desktop app. |
| `phi profile` | Manage profiles — multiple isolated Phi instances. |
| `phi completion` | Print shell completion scripts (bash/zsh/fish). |
| `phi --version` | Show version information. |
| `phi update` | Update to the latest stable release (or the selected channel) and reinstall dependencies. `--check` previews without installing; `--backup` takes a pre-pull `PHI_HOME` snapshot. |
| `phi uninstall` | Remove Phi from the system. |

## `phi chat`

```bash
phi chat [options]
```

Common options:

| Option | Description |
|--------|-------------|
| `-q`, `--query "..."` | Seed the session with a prompt. On a real TTY the prompt is submitted **literally** as the first turn of a normal interactive session (it is never parsed as a slash command or `!` shell escape) and the session stays open — ideal for OS launchers and desktop integrations. With `--oneshot`, `-Q`, or non-TTY stdio it answers and exits. |
| `--query-file PATH` | Read the query from a file (`-` = stdin). Nothing is shell-interpreted, so quotes, `$(...)`, and backticks arrive verbatim — use this for programmatic or untrusted message bodies (Bot Mode teammate DMs use it). Mutually exclusive with `-q`. |
| `--oneshot` | With `-q`/`--query-file`: answer the query and exit (the pre-0.21 single-query behavior) instead of seeding an interactive session. Implied on non-TTY stdio and by `-Q`. |
| `-m`, `--model <model>` | Override the model for this run. |
| `-t`, `--toolsets <csv>` | Enable a comma-separated set of toolsets. |
| `--provider <provider>` | Force a provider: `auto`, `openrouter`, `nous`, `openai-codex` (aliases `chatgpt`, `chatgpt-codex`), `copilot-acp`, `copilot`, `anthropic`, `gemini`, `huggingface`, `novita` (aliases `novita-ai`, `novitaai`), `openai-api`, `zai`, `kimi-coding`, `kimi-coding-cn`, `minimax`, `minimax-cn`, `minimax-oauth`, `kilocode`, `xiaomi`, `arcee`, `gmi`, `upstage` (alias `solar`), `alibaba`, `alibaba-cn`, `alibaba-coding-plan` (alias `alibaba_coding`), `alibaba-coding-plan-cn`, `alibaba-token-plan`, `alibaba-token-plan-cn`, `deepseek`, `nvidia`, `ollama-cloud`, `xai` (alias `grok`), `xai-oauth` (alias `grok-oauth`), `qwen-oauth`, `bedrock`, `opencode-zen`, `opencode-go`, `commandcode`, `commandcode-anthropic`, `ai-gateway`, `azure-foundry`, `lmstudio`, `stepfun`, `tencent-tokenhub` (alias `tencent`, `tokenhub`), `router` (aliases `ramp-router`, `ramp`), `nebius-token-factory` (aliases `nebius`, `nebius-tf`, `tokenfactory`), `tencent-tokenplan` (aliases `tokenplan`, `tencent-lkeap`). |
| `-s`, `--skills <name>` | Preload one or more skills for the session (can be repeated or comma-separated). |
| `-v`, `--verbose` | Verbose output. |
| `-Q`, `--quiet` | Programmatic mode: suppress banner/spinner/tool previews. |
| `--format stream-json` | Emit structured JSONL for a `-q` / `--query` invocation. Implies `--quiet`; cannot be combined with `--tui`. |
| `--image <path>` | Attach a local image to a single query. |
| `--resume <session>` / `--continue [name]` | Resume a session directly from `chat`. |
| `--worktree` | Create an isolated git worktree for this run. |
| `--checkpoints` | Enable filesystem checkpoints before destructive file changes. |
| `--yolo` | Skip approval prompts. |
| `--pass-session-id` | Pass the session ID into the system prompt. |
| `--ignore-user-config` | Ignore `~/.phi/config.yaml` and use built-in defaults. Credentials in `.env` are still loaded. Useful for isolated CI runs, reproducible bug reports, and third-party integrations. |
| `--ignore-rules` | Skip auto-injection of `AGENTS.md`, `SOUL.md`, `.cursorrules`, persistent memory, and preloaded skills. Combine with `--ignore-user-config` for a fully isolated run. |
| `--safe-mode` | Troubleshooting mode: disable ALL customizations — user config, rules/memory injection, plugins, shell hooks, and MCP servers (implies `--ignore-user-config` and `--ignore-rules`). The gateway freezes code defaults plus your explicit options into the session and runs the turn in an isolated worker process that never reads the profile, so a broken `config.yaml` cannot block it. Requires an explicit `--model` (there is no profile default to inherit); pair with `--provider custom --base-url <url> --api-key <key>` for a fully explicit endpoint. |
| `--base-url <url>` / `--api-key <key>` | Explicit OpenAI-compatible endpoint and launch-only key for `--provider custom`. The key is held in the running gateway's memory for this session and never written to disk. |
| `--source <tag>` | Session source tag for filtering (default: `cli`; one-shot runs default to `oneshot`, which pickers hide). Use `tool` for third-party integrations that should not appear in user session lists. An explicit `--source` is always stored as given, even for a one-shot run launched from inside a TUI or Desktop session. |
| `--max-turns <N>` | Maximum tool-calling iterations per conversation turn (default: 500, or `agent.max_turns` in config). |

Examples:

```bash
phi
phi chat -q "Summarize the latest PRs"          # seeds an interactive session
phi chat --oneshot -q "Summarize the latest PRs"  # answer and exit
phi chat --provider openrouter --model anthropic/claude-sonnet-4.6
phi chat --toolsets web,terminal,skills
phi chat --quiet -q "Return only JSON"
phi chat -q "Inspect this repository" --format stream-json
phi chat --worktree -q "Review this repo and open a PR"
phi chat --ignore-user-config --ignore-rules -q "Repro without my personal setup"
phi chat --safe-mode --model gpt-4.1 -q "Is this bug mine or Phi'?"
phi chat --safe-mode --provider custom --base-url http://127.0.0.1:8000/v1 --model local -q "Isolate against a local server"
```

### `--format stream-json` — structured JSONL output

Use `--format stream-json` when a program needs to consume progress without
scraping terminal output. It requires `-q` / `--query` (or `--query-file`), implies
quiet non-interactive CLI mode, and rejects an explicit `--tui` request. Every
stdout line is one JSON object; diagnostics and the `session_id:` line stay on stderr.

```bash
phi chat -q "Summarize this repository" --format stream-json
```

Every event carries `timestamp` (Unix epoch milliseconds).

| Event `type` | Fields |
|---|---|
| `system` | `subtype: "init"`, `model`, `session_id` |
| `text` | `text` — a streamed assistant text delta |
| `tool_use` | `name`; `input` when the tool arguments are available |
| `tool_result` | `name`, `output` (capped at 5000 chars), `duration_ms`, `is_error` |
| `result` | `session_id`, `exit_code`, `text`, `tokens` (`input`, `output`, `total`, `cache_read`, `cache_write`), `duration_ms`; `error` when the turn failed; `replay_gap: true` when the run fell behind the gateway's stream and re-attached, so its `text` events stopped early (`text` here is still the whole reply) |

Once a conversation starts, its terminal record is always `result` — including
`exit_code: 130` when it is interrupted with Ctrl-C. Treat that record as the
completion signal; the process exit code matches its `exit_code`.

#### Exit codes for one-shot runs

When chat answers and exits (`-Q`, `chat --oneshot`, or a query with non-TTY
stdio) the process exit code reports the turn's outcome, on both the quiet and
the non-quiet path: `0` the turn completed; `1` it failed, stopped partway
(`partial`), hit the iteration budget, or never ran (credentials / agent init
failed); `130` it was interrupted. A Kanban dispatcher-spawned worker
(`PHI_KANBAN_TASK` set) whose turn failed only because the provider was
rate-limited, overloaded, returning 5xx, timing out, or the account hit a
billing/quota wall, exits
`75` (`EX_TEMPFAIL`) so the dispatcher requeues the task without counting a
failure. With `--format stream-json` the terminal `result` record carries the
same `exit_code`.

#### Delegation in finite chat runs

When chat answers and exits, `delegate_task` waits for its children and returns their
results in the same turn instead of running them in the background. Details and limits:
[Delegation: finite chat runs](../user-guide/features/delegation.md#finite-chat-runs).

### `phi -z <prompt>` — scripted one-shot

For programmatic callers (shell scripts, CI, cron, parent processes piping in a prompt), `phi -z` is the purest one-shot entry point: **single prompt in, final response text out, nothing else on stdout or stderr.** No banner, no spinner, no tool previews, no `Session:` line — just the agent's final reply as plain text.

```bash
phi -z "What's the capital of France?"
# → Paris.

# Parent scripts can cleanly capture the response:
answer=$(phi -z "summarize this" < /path/to/file.txt)
```

Per-run overrides (no mutation to `~/.phi/config.yaml`):

| Flag | Equivalent env var | Purpose |
|---|---|---|
| `-m` / `--model <model>` | `PHI_INFERENCE_MODEL` | Override the model for this run |
| `--provider <provider>` | _(none)_ | Override the provider for this run |
| `--usage-file <path>` | _(none)_ | Write a JSON usage report after the run (see below) |

```bash
phi -z "…" --provider openrouter --model openai/gpt-5.5
# or:
PHI_INFERENCE_MODEL=anthropic/claude-sonnet-4.6 phi -z "…"
```

Same agent, same tools, same skills — just strips every interactive / cosmetic layer. If you need tool output in the transcript too, use `phi chat --oneshot -q` instead; `-z` is explicitly for "I only want the final answer".

Exit codes: `0` the turn completed; `2` it failed or stopped partway (`partial`,
iteration budget, `completed: false`) — even when an explanation was printed;
`130` it was interrupted; `1` a completed turn produced no text at all; `2` also
for usage errors (bad flags) before the run starts. These codes intentionally
differ from `chat -q`/`-Q` above (which exit `1` for failed/partial/budget and
`0` for a completed turn with no text): `-z` reserves `1` for "answered nothing".
Judge the run by the exit code (or the `--usage-file` flags), not by whether
stdout is non-empty.

#### `--usage-file` — JSON usage report for pipelines

`phi -z "…" --usage-file /path/report.json` writes a machine-readable usage report after the run: `estimated_cost_usd`, `input_tokens` / `output_tokens` / `cache_read_tokens` / `cache_write_tokens` / `reasoning_tokens` / `total_tokens`, `api_calls`, `model`, `provider`, `session_id`, `service_tier`, the `completed` / `failed` / `partial` / `interrupted` flags and `turn_exit_reason` (why `completed` is false, e.g. `max_iterations_reached(3/3)`). Those top-level counters cover the **main agent loop** only. Auxiliary LLM calls made on the same run (title generation, vision, context compression, `web_extract`, background review, …) are reported separately under `auxiliary` — the same totals plus a per-task `by_task` map — and `total_including_auxiliary` (`estimated_cost_usd`, `total_tokens`, `api_calls`) is the grand total to bill on. The report is written **even when the run fails**, so batch pipelines can always account for spend. It has no effect outside `-z`/`--oneshot`, and a broken usage write never masks the run's own outcome.

```bash
phi -z "summarize this repo" --usage-file ~/.phi/cache/scratch/usage.json
jq .total_including_auxiliary.estimated_cost_usd ~/.phi/cache/scratch/usage.json
jq .auxiliary.by_task ~/.phi/cache/scratch/usage.json      # what did title generation / vision cost?
```

## `phi model`

Interactive provider + model selector. **This is the command for adding new providers, setting up API keys, and running OAuth flows.** Run it from your terminal — not from inside an active Phi chat session.

```bash
phi model
```

Use this when you want to:
- **add a new provider** (OpenRouter, Anthropic, Copilot, DeepSeek, custom, etc.)
- log into OAuth-backed providers (Anthropic, Copilot, Codex, Nous Portal)
- enter or update API keys
- pick from provider-specific model lists
- configure a custom/self-hosted endpoint
- save the new default into config

:::warning phi model vs /model — know the difference
**`phi model`** (run from your terminal, outside any Phi session) is the **full provider setup wizard**. It can add new providers, run OAuth flows, prompt for API keys, and configure endpoints.

**`/model`** (typed inside an active Phi chat session) can only **switch between providers and models you've already set up**. It cannot add new providers, run OAuth, or prompt for API keys.

**If you need to add a new provider:** Exit your Phi session first (`Ctrl+C` or `/quit`), then run `phi model` from your terminal prompt.
:::

### `/model` slash command (mid-session)

Switch between already-configured models without leaving a session:

```
/model                              # Show current model and available options
/model claude-sonnet-4              # Switch model (auto-detects provider)
/model zai:glm-5                    # Switch provider and model
/model custom:qwen-2.5              # Use model on your custom endpoint
/model custom                       # Auto-detect model from custom endpoint
/model custom:local:qwen-2.5        # Use a named custom provider
/model openrouter:anthropic/claude-sonnet-4  # Switch back to cloud
```

By default, `/model` changes apply **to the current session only**. Add `--global` to persist the change to `config.yaml` (or set `model.persist_switch_by_default: true` to make every switch persist):

```
/model claude-sonnet-4 --global     # Switch and save as new default
```

:::info What if I only see OpenRouter models?
If you've only configured OpenRouter, `/model` will only show OpenRouter models. To add another provider (Anthropic, DeepSeek, Copilot, etc.), exit your session and run `phi model` from the terminal.
:::

On a `--global` switch, provider and base URL changes are persisted to `config.yaml` alongside the model. When switching away from a custom endpoint, the stale base URL is cleared to prevent it leaking into other providers.

## `phi gateway`

```bash
phi gateway <subcommand>
```

Subcommands:

| Subcommand | Description |
|------------|-------------|
| `run` | Run the gateway in the foreground. Recommended for WSL, Docker, and Termux. |
| `ensure` | Discover or request a local session runtime without installing a service or replacing an existing owner. Emits JSON; see below. |
| `start` | Start the installed systemd/launchd background service. |
| `stop` | Stop the service (or foreground process). |
| `restart` | Restart the service. |
| `status` | Show service status. |
| `list` | List **all profiles** and whether each profile's gateway is currently running (with PID where available). Handy when you run multiple profiles side-by-side and want a single overview. |
| `install` | Install as a systemd (Linux) or launchd (macOS) background service. |
| `uninstall` | Remove the installed service. |
| `setup` | Interactive messaging-platform setup. |
| `migrate` | Fold per-profile standalone gateways onto the one host gateway (`--multiplex`, the only mode — `phi update` runs it automatically unless a real boundary blocks it). Re-running it converges a half-migrated host; a manifest on disk is the resume record, never a rollback (there is no `--standalone`). Runs a preflight (duplicate bot tokens, secondary port-binders without a `/p/<profile>/` ingress) and changes nothing when blocked. Flags: `--dry-run`, `-y`/`--yes`. See [Migrating from per-profile gateways](../user-guide/multi-profile-gateways.md#migrating-from-per-profile-gateways). |
| `migrate-legacy` | Remove legacy `phi.service` units left over from pre-rename installs. Profile units (`phi-gateway-<profile>.service`) and unrelated services are never touched. Flags: `--dry-run`, `-y`/`--yes`. |
| `enroll` | Experimental: enroll this gateway with a relay connector and save relay credentials for connector-backed platforms. See [Phi Relay](../user-guide/messaging/relay.md). |

Options:

| Option | Description |
|--------|-------------|
| `--all` | On `start` / `restart` / `stop`: act on **every profile's** gateway, not just the active `PHI_HOME`. Useful if you run multiple profiles side-by-side and want to restart them all after `phi update`. |
| `-y`, `--yes` | On `stop` / `restart`: when the gateway is running chat turns, cron jobs or background delegations, the command lists them and asks `y/N` before interrupting them. `--yes` skips the question. With no terminal to ask on (scripts, cron) it refuses unless `--yes` is passed. `--interrupt` is an alias. |
| `--detach` | On `restart`: when no gateway service is installed, start the replacement in the background (the way `phi gateway ensure` starts one) instead of in the current terminal. The desktop app and the updater's recovery restart pass it so their short-lived restart call never becomes the gateway itself. Service, supervisor and Windows-task restarts are unchanged. |
| `--no-supervise` | On `run`: inside the s6-overlay Docker image, opt out of auto-supervision and use pre-s6 foreground semantics — gateway runs as the container's main process with no auto-restart. No-op outside the s6 image. Equivalent to setting `PHI_GATEWAY_NO_SUPERVISE=1`. |
| `--external-supervisor` | On `run`: declare that a wrapper-provided process manager owns the foreground gateway. Use this when `sudo`, `env -i`, or another wrapper strips launchd/systemd's native environment marker. In-chat restarts and updates exit back to that manager instead of spawning a detached replacement. |

`--external-supervisor` is a restart-policy contract: an in-chat restart,
`phi gateway restart`, or service-restart update exits with status `75`
(the CLI then waits for the supervisor's fresh PID instead of running a
foreground gateway of its own), so the wrapper's supervisor must
relaunch the gateway after that nonzero exit. For systemd, use
`Restart=on-failure` or `Restart=always` and do not include `75` in
`RestartPreventExitStatus`; for launchd, configure `KeepAlive` to relaunch after
unsuccessful exits. Without that policy, a requested restart leaves the gateway
stopped.

`phi gateway enroll` accepts `--token`, `--connector-url`, `--gateway-id`, and `--wake-url`. It exchanges the enrollment token with the connector and writes the resulting `GATEWAY_RELAY_ID`, `GATEWAY_RELAY_SECRET`, `GATEWAY_RELAY_DELIVERY_KEY`, optional `GATEWAY_RELAY_URL`, and (when `--wake-url` is given) `GATEWAY_RELAY_WAKE_URL` values to the active profile's `.env`.

:::tip WSL users
Use `phi gateway run` instead of `phi gateway start` — WSL's systemd support is unreliable. Wrap it in tmux for persistence: `tmux new -s phi 'phi gateway run'`. See [WSL FAQ](./faq.md#wsl-gateway-keeps-disconnecting-or-phi-gateway-start-fails) for details.
:::

### Local runtime discovery and startup

`phi gateway ensure [--json] [--timeout 60]` discovers or starts the active profile's
session runtime and prints one JSON object (`state`, `reason_code`, and an `endpoint` only
once authenticated discovery reports compatible readiness; never tickets or credentials).
It waits for an existing or starting owner instead of replacing it and never installs a
service. Exit `0` means ready; any other code is a refusal or a deadline, never permission
to start a replacement. Service identity checks, the home-permission policy behind
`unsafe_control_permissions`, and every exit code:
[Gateway internals: `phi gateway ensure`](../developer-guide/gateway-internals.md#phi-gateway-ensure).

## `phi lsp`

```bash
phi lsp <subcommand>
```

Manage the Language Server Protocol integration. LSP runs real
language servers (pyright, gopls, rust-analyzer, …) in the
background and feeds their diagnostics into the post-write check
used by `write_file` and `patch`. Gated on git workspace detection
— LSP only runs when the cwd or edited file is inside a git
worktree.

Subcommands:

| Subcommand | Description |
|------------|-------------|
| `status` | Show service state, configured servers, install status. |
| `list` | Print the registry of supported servers. Pass `--installed-only` to skip missing ones. |
| `install <id>` | Eagerly install one server's binary. |
| `install-all` | Install every server with a known auto-install recipe. |
| `restart` | Tear down running clients so the next edit re-spawns. |
| `which <id>` | Print the resolved binary path for one server. |

See [LSP — Semantic Diagnostics](../user-guide/features/lsp.md) for
the full guide, supported languages, and configuration knobs.

## `phi setup`

```bash
phi setup [model|tts|terminal|gateway|tools|agent] [--non-interactive] [--reset] [--quick] [--reconfigure] [--portal]
```

**Easiest path:** `phi setup --portal` — OAuth into Nous Portal and opt into the [Tool Gateway](../user-guide/features/tool-gateway.md) in one shot.

**First run:** launches the first-time wizard.

**Returning user (already configured):** drops straight into the full reconfigure wizard — every prompt shows your current value as its default, press Enter to keep or type a new value. No menu.

**Coming from another agent:** when the first run finds an OpenClaw, Claude Code, Codex CLI or Cursor setup (`~/.openclaw`, `~/.claude`, `~/.codex`, `~/.cursor`), it first asks **"Import your setup from …?"** (default yes). With more than one found, you then pick which from a checklist. Setup installs the [`agent-importers`](../user-guide/import-from-other-agents.md) plugin from the catalog, unless you already have it, and runs its import for each pick, which shows a preview and asks before changing anything (OpenClaw's allowlisted API keys and bot tokens are included, as the old built-in step did). Nothing found, a no, `--non-interactive` or a setup started by the dashboard: no question and nothing installed. On an already configured install, run `phi import-agent` instead.

Jump into one section instead of the full wizard:

| Section | Description |
|---------|-------------|
| `model` | Provider and model setup. |
| `terminal` | Terminal backend and sandbox setup. |
| `gateway` | Messaging platform setup. |
| `tools` | Enable/disable tools per platform. |
| `agent` | Agent behavior settings. |

Options:

| Option | Description |
|--------|-------------|
| `--quick` | On returning-user runs: only prompt for items that are missing or unset. Skip items you already have configured. |
| `--non-interactive` | Use defaults / environment values without prompts. |
| `--reset` | Reset configuration to defaults before setup. |
| `--reconfigure` | Backwards-compat alias — bare `phi setup` on an existing install now does this by default. |
| `--portal` | One-shot Nous Portal setup: log in via OAuth, set Nous as the inference provider, and opt into the [Tool Gateway](../user-guide/features/tool-gateway.md). Skips the rest of the wizard. |

## `phi portal`

```bash
phi portal [status|open|tools]
```

Inspect Nous Portal auth, Tool Gateway routing, and reach the subscription page. Subcommand-less invocation runs `status`.

| Subcommand | Description |
|------------|-------------|
| `status` (default) | Portal auth state + per-tool Tool Gateway routing summary. Also shown when no subcommand is given. |
| `open` | Open `portal.nousresearch.com/manage-subscription` in your default browser. |
| `tools` | List every Tool Gateway partner (Firecrawl, FAL, OpenAI TTS, Browser Use, Modal) and which are routed via Nous. |

For configuration of the gateway itself, see [Tool Gateway](../user-guide/features/tool-gateway.md). For the one-shot setup path, see `phi setup --portal` above.

## `phi whatsapp`

```bash
phi whatsapp
```

Runs the WhatsApp pairing/setup flow, including mode selection and QR-code pairing.

## `phi slack`

```bash
phi slack manifest              # print manifest to stdout
phi slack manifest --write      # write to ~/.phi/slack-manifest.json
phi slack manifest --long-description-file AGENTS.md --write
phi slack manifest --slashes-only  # just the features.slash_commands array
```

Generates a Slack app manifest that registers every gateway command in
`COMMAND_REGISTRY` (`/btw`, `/stop`, `/model`, …) as a first-class
Slack slash command — matching Discord and Telegram parity. Paste the
output into your Slack app config at
[https://api.slack.com/apps](https://api.slack.com/apps) → your app →
**Features → App Manifest → Edit**, then **Save**. Slack prompts for
reinstall if scopes or slash commands changed.

| Flag | Default | Purpose |
|------|---------|---------|
| `--write [PATH]` | stdout | Write to a file instead of stdout. Bare `--write` writes `$PHI_HOME/slack-manifest.json`. |
| `--name NAME` | `Phi` | Bot display name in Slack. |
| `--description DESC` | default blurb | Bot description shown in the Slack app directory. |
| `--long-description TEXT` | unset | Set `display_information.long_description` inline (175–4,000 characters). Incompatible with `--slashes-only`. |
| `--long-description-file PATH` | unset | Read the long description from a UTF-8 text file, preserving its contents exactly. Mutually exclusive with `--long-description` and incompatible with `--slashes-only`. |
| `--slashes-only` | off | Emit only `features.slash_commands` for merging into a manually-maintained manifest. |

Run `phi slack manifest --write` again after `phi update` to pick
up any new commands.


## `phi send`

```bash
phi send --to <target> "message text"
phi send --to <target> --file <path>
echo "message" | phi send --to <target>
phi send --list [platform]
```

Send a one-shot message to a configured messaging platform without spinning up an agent or gateway loop. Reuses the gateway's already-configured credentials (`~/.phi/.env` + `~/.phi/config.yaml`) so ops scripts, cron jobs, CI hooks, and monitoring daemons can post status updates without reimplementing each platform's REST client.

For bot-token platforms (Telegram, Discord, Slack, Signal, SMS, WhatsApp-CloudAPI) no running gateway is required — `phi send` talks directly to the platform's REST endpoint. Plugin platforms that need a persistent adapter still require a live gateway.

| Option | Description |
|--------|-------------|
| `-t`, `--to <TARGET>` | Delivery target. Formats: `platform` (uses home channel), `platform:chat_id`, `platform:chat_id:thread_id`, or `platform:#channel-name`. Examples: `telegram`, `telegram:-1001234567890`, `discord:#ops`, `slack:C0123ABCD`, `signal:+15551234567`. |
| `-f`, `--file <PATH>` | Read the message body from `PATH` (text files only — logs, reports, markdown). Pass `-` to force reading from stdin. To send an image or other binary file, use `MEDIA:<path>` (see below). |
| `-s`, `--subject <LINE>` | Prepend a subject/header line before the message body. |
| `-l`, `--list [platform]` | List configured targets across all platforms (or only the given platform). |
| `-q`, `--quiet` | Suppress stdout on success — useful in scripts (rely on exit code only). |
| `--json` | Emit raw JSON result instead of human-readable output. |

If neither a positional `message` argument nor `--file` is provided, `phi send` reads from stdin when it is not a TTY. Exit codes: `0` on success, `1` on delivery/backend failure, `2` on usage errors.

### Sending images and other media

`--file` is for *text* bodies only. To deliver an image, document, video, or audio file as a native platform attachment, reference it inside the message text with the `MEDIA:<local_path>` directive:

```bash
phi send --to telegram "MEDIA:~/.phi/cache/scratch/screenshot.png"
phi send --to telegram "Build chart for today MEDIA:~/.phi/cache/scratch/chart.png"   # with caption
phi send --to discord:#ops "MEDIA:~/.phi/cache/scratch/report.pdf"
```

By default, image files are sent as photos (platforms like Telegram recompress these). Add `[[as_document]]` to the message to deliver them as uncompressed file attachments instead:

```bash
phi send --to telegram "[[as_document]] MEDIA:~/.phi/cache/scratch/screenshot.png"
```

Examples:

```bash
phi send --to telegram "deploy finished"
echo "RAM 92%" | phi send --to telegram:-1001234567890
phi send --to discord:#ops --file ~/.phi/cache/scratch/report.md
phi send --to slack:#eng --subject "[CI]" --file build.log
phi send --list                  # all platforms
phi send --list telegram         # filter by platform
```



## `phi peer`

```bash
phi peer add <name> --url http://host:port --key <API_SERVER_KEY>
phi peer list
phi peer dm <peer>[/<agent>] "message"
phi peer run <peer>[/<agent>] --idempotency-key <key> "message"
phi peer status <peer>[/<agent>] <run_id>
phi peer stop <peer>[/<agent>] <run_id>
phi peer remove <name>
```

Bot-to-bot DMs across machines. Register another Phi gateway (any machine
running the `api_server` platform) as a *peer*, then message its agents:
`phi peer dm` resolves the remote agent's canonical **Bot Chat** session
over the peer's API server, runs one agent turn there, and prints the reply
on stdout — the cross-machine twin of the local
`phi -p <bot> chat --in ~ -c "Bot Chat" …` bot-messaging command.

`<peer>` alone targets the peer gateway's main agent;
`<peer>/<agent>` targets a named profile on a multiplexed peer (routed via
its `/p/<profile>/` mirror).

| Subcommand | Description |
|--------|-------------|
| `add <name> --url <URL> [--key <KEY>] [--note TEXT]` | Register or update a peer. The URL goes to `config.yaml` (`bot_peers`); the key is stored as `PHI_PEER_<NAME>_KEY` in `~/.phi/.env`. |
| `list` | List peers and whether each has a key configured. |
| `dm <peer>[/<agent>] [message]` | Message the peer agent's canonical Bot Chat and print the reply (`--json` for machine-readable output; message falls back to stdin). |
| `run <peer>[/<agent>] [message]` | Start a long canonical Bot Chat turn asynchronously and return its `run_id`, session ID, and idempotency key (`--json` supported). Reuse `--idempotency-key` when retrying the same request. |
| `status <peer>[/<agent>] <run_id>` | Poll an asynchronous peer run and print its final output when complete (`--json` supported). |
| `stop <peer>[/<agent>] <run_id>` | Stop the exact asynchronous peer run without targeting another turn (`--json` supported). |
| `remove <name>` | Remove a peer from the registry (the `.env` key entry is left in place). |

When at least one peer is registered, the Bot Mode messaging protocol
(`agent.bot_mode_protocol`) taught to every canonical Bot Chat automatically
includes the peer roster and the `phi peer dm` pattern, so agents discover
cross-machine teammates without SOUL edits. See
[Bot Mode](../user-guide/bot-mode.md).

Exit codes: `0` on success, `1` on delivery/peer failure, `2` on usage errors.

## `phi secrets`

```bash
phi secrets bitwarden <subcommand>
phi secrets bw <subcommand>          # short alias
```

Pull API keys from an external secret manager at process startup instead of storing them in `~/.phi/.env`. Currently supports **Bitwarden Secrets Manager**. See the full guide: [Bitwarden integration](../user-guide/secrets/bitwarden.md).

`bitwarden` (alias `bw`) subcommands:

| Subcommand | Description |
|------------|-------------|
| `setup` | Interactive wizard: install the pinned `bws` binary, store an access token, and pick a project. Accepts `--project-id`, `--access-token`, and `--server-url` for non-interactive use. |
| `status` | Show current config, binary path/version, and token validation status. |
| `token` | Rotate the access token: validates the new token against Bitwarden before storing it in `.env` (a rejected token changes nothing). Accepts `--access-token` for non-interactive use and `--no-verify` to skip the probe. |
| `sync` | Fetch secrets now and report what changed. Add `--apply` to actually export the secrets into the current shell's environment (default is dry-run). |
| `install` | Install or repair the PM-pinned `bws` binary. `--force` requests the same integrity check and repair, not an unconditional download. |
| `disable` | Turn off the Bitwarden integration. |


## `phi migrate`

```bash
phi migrate <type>
```

Diagnose and (optionally) rewrite the active `config.yaml` to replace references to retired models or deprecated settings. A timestamped backup of the original `config.yaml` is taken before any rewrite (skip with `--no-backup`).

| Subcommand | Description |
|------------|-------------|
| `xai` | Scan `config.yaml` for references to xAI models scheduled for retirement on May 15, 2026 and (with `--apply`) rewrite them in-place to the official replacements per the xAI migration guide. Defaults to dry-run. |

Common flags for migration subcommands:

| Flag | Description |
|------|-------------|
| `--apply` | Rewrite `config.yaml` in-place (default: dry-run, no writes). |
| `--no-backup` | Skip the timestamped backup of `config.yaml` when applying. |

> Not to be confused with `phi import-agent openclaw` (one-shot import of OpenClaw configuration into Phi) — `phi migrate` is the top-level config-rewrite command.


## `phi codex-runtime`

```bash
phi codex-runtime migrate [--dry-run] [--json]
```

Runs the `~/.codex/config.toml` migration that `/codex-runtime codex_app_server` triggers, without a chat session: Phi' `mcp_servers` (plus installed codex plugins and the `default_permissions` default) are projected into the managed block for the selected profile (`phi -p <name> codex-runtime migrate`). User text outside the block is kept verbatim; a user-owned `[mcp_servers.<name>]` with the same name as a Phi server is preserved and the Phi projection for that name skipped (reported as `preserved_user_servers`). The result is validated as TOML before an atomic write; exit code is 1 when the report contains errors.

| Flag | Description |
|------|-------------|
| `--dry-run` | Compute and report the migration without writing `config.toml`. |
| `--json` | Print the full migration report as JSON (`migrated`, `preserved_user_servers`, `skipped_keys_per_server`, `errors`, `target_path`, `written`). |


## `phi proxy`

```bash
phi proxy <subcommand>
```

Run a local OpenAI-compatible HTTP server that forwards requests to an OAuth-authenticated upstream provider (e.g. Nous Portal, xAI). External apps can point at the proxy with any bearer token; the proxy attaches your real OAuth credentials on the way out. See [Subscription Proxy](../user-guide/features/subscription-proxy.md) for the full guide.

| Subcommand | Description |
|------------|-------------|
| `start` | Run the proxy in the foreground. Flags: `--provider <nous\|xai>` (default `nous`), `--host <addr>` (default `127.0.0.1`; use `0.0.0.0` to expose on LAN), `--port <int>` (default `8645`). |
| `status` | Show which proxy upstreams are ready (credentials present, OAuth valid). |
| `providers` | List available proxy upstream providers. |


## `phi security`

```bash
phi security <subcommand>
```

On-demand vulnerability scan against [OSV.dev](https://osv.dev). Covers the Phi venv (installed PyPI distributions), Python dependencies declared by plugins under `~/.phi/plugins/`, and pinned `npx`/`uvx` MCP servers in `config.yaml`. Does NOT scan globally-installed packages or editor/browser extensions.

| Subcommand | Description |
|------------|-------------|
| `audit` | Run a one-shot supply-chain audit. |

`audit` flags:

| Flag | Default | Description |
|------|---------|-------------|
| `--json` | off | Emit machine-readable JSON instead of human-readable text. |
| `--fail-on <level>` | `critical` | Exit non-zero when any finding meets this severity (`low`, `moderate`, `high`, `critical`). |
| `--skip-venv` | off | Skip scanning the Phi Python venv. |
| `--skip-plugins` | off | Skip scanning plugin requirements files. |
| `--skip-mcp` | off | Skip scanning pinned MCP servers in `config.yaml`. |


## `phi login` / `phi logout` *(Deprecated)*

:::caution
`phi login` has been removed. Use `phi auth` to manage OAuth credentials, `phi model` to select a provider, or `phi setup` for full interactive setup.
:::

## `phi auth`

Manage credential pools for same-provider key rotation. See [Credential Pools](../user-guide/features/credential-pools.md) for full documentation.

```bash
phi auth                                              # Interactive wizard
phi auth list                                         # Show all pools
phi auth list openrouter                              # Show specific provider
phi auth add openrouter --api-key sk-or-v1-xxx        # Add API key
phi auth add openrouter --type oauth                  # Browser login (OpenRouter PKCE) mints a key for you
phi auth add anthropic --type oauth                   # Add OAuth credential
phi auth add openai-codex --type oauth --priority 0   # Add an account and try it first
phi auth add openai-codex --browser                   # Codex: browser auth-code + PKCE on localhost:1455 instead of device code
phi auth remove openrouter 2                          # Remove by index
phi auth priority openrouter backup-key 0             # Move a credential to the front of fill_first order
phi auth reset openrouter                             # Clear cooldowns
phi auth reset openrouter 2                           # Clear the cooldown on one credential
phi auth refresh openai-codex work                    # Refresh one OAuth credential and clear its cooldown
phi auth status anthropic                             # Show auth status for a provider
phi auth logout anthropic                             # Log out and clear stored auth state
```

Subcommands: `add`, `list`, `remove`, `reset`, `priority`, `refresh`, `status`, `logout`. Spotify login moved to the `spotify` catalog plugin's `phi spotify login`. When called with no subcommand, launches the interactive management wizard.

## `phi usage`

The account-limits block of the `/usage` slash command — Codex 5-hour / weekly windows, plan and banked
resets; Anthropic OAuth windows; OpenRouter credits — without starting a session, so shell scripts and cron
jobs can read it.

```bash
phi usage                          # configured model provider, human-readable block
phi usage --provider openai-codex  # a specific provider
phi usage --json                   # one JSON document on stdout
```

| Option | Description |
|--------|-------------|
| `--provider NAME` | Provider to query (default: the configured `model.provider`). Supported: `openai-codex`, `anthropic`, `openrouter`. |
| `--json` | Print one JSON document instead of the human-readable block. |

Credentials resolve exactly as they do for `/usage` in a session with no live agent (the auth store, then
the credential pool); the command never adds or refreshes a credential it would not use for chat. Exit code
`0` on success; `1` with a single stderr line when no credential is configured for the provider, the provider
has no usage endpoint, or the fetch fails (stdout stays empty).

`--json` schema (keys are stable; new keys may be added):

```json
{
  "provider": "openai-codex",
  "source": "usage_api",
  "title": "Account limits",
  "plan": "Plus",
  "fetched_at": "2026-09-19T07:58:55+00:00",
  "windows": [
    {"label": "Session", "used_percent": 37.0, "resets_at": "2026-09-19T21:00:00+00:00", "detail": null},
    {"label": "Weekly", "used_percent": 12.5, "resets_at": "2026-09-25T09:00:00+00:00", "detail": null}
  ],
  "details": ["You have 1 reset banked - use /usage reset to activate"],
  "unavailable_reason": null
}
```

`used_percent` is `null` when the provider did not report the window; `resets_at` is ISO-8601 UTC or `null`
(some windows carry a free-text `detail` instead); `plan` is `null` when unknown.

## `phi status`

```bash
phi status [--full] [--deep]
```

By default prints a one-screen summary: model, active provider, every provider with
credentials (the same list the `/model` picker offers), gateway state, the messaging
platforms the gateway would start, and scheduled jobs. No key values are printed.

| Option | Description |
|--------|-------------|
| `--full` | Print every section (API keys redacted, auth providers, terminal backend, sessions, ...). `--all` is an alias. |
| `--deep` | Run deeper checks that may take longer. Implies `--full`. |

## `phi cron`

```bash
phi cron <list|create|edit|pause|resume|run|remove|status|runs|incidents|doctor|tick>
```

| Subcommand | Description |
|------------|-------------|
| `list` | Show scheduled jobs. |
| `create` / `add` | Create a scheduled job from a prompt, optionally attaching one or more skills via repeated `--skill`. Supports a per-job reasoning pin via `--reasoning-effort <none\|minimal\|low\|medium\|high\|xhigh\|max\|ultra>`. |
| `edit` | Update a job's schedule, prompt, name, delivery, repeat count, or attached skills. Supports `--clear-skills`, `--add-skill`, and `--remove-skill`, plus `--reasoning-effort` (empty string clears the pin). |
| `pause` | Pause a job without deleting it. |
| `resume` | Resume a paused job. A recurring slot that came due while paused stays due (one catch-up run or a logged skip on the next tick); otherwise the next future run is computed. |
| `run` | Trigger a job on the next scheduler tick. |
| `remove` | Delete a scheduled job. |
| `status` | Check whether the cron scheduler is running. |
| `doctor` | Read-only fleet health check: failed runs, failed deliveries, overdue/missing `next_run_at`, missing scripts or workdirs. Exits non-zero when issues are found. |
| `tick` | Run due jobs once and exit. |

The cron **trigger** is pluggable via the `cron.provider` config key. Empty
(the default) uses the built-in in-process ticker. Set it to `chronos` (the
NAS-managed provider for scale-to-zero hosted gateways) — configured via the
`cron.chronos.*` keys (`portal_url`, `callback_url`, `expected_audience`,
`nas_jwks_url`) — or name a custom provider under `plugins/cron/<name>/` or
`$PHI_HOME/plugins/<name>/`. An unknown or unavailable provider falls back to
the built-in, so cron is never left without a trigger. See the
[cron internals](../developer-guide/cron-internals.md#gateway-integration) doc.

## `phi kanban`

```bash
phi kanban [--board <slug>] <action> [options]
```

Multi-profile, multi-project collaboration board. Each install can host many boards (one per project, repo, or domain); each board is a standalone queue with its own SQLite DB and dispatcher scope. New installs start with one board called `default`, whose DB is `~/.phi/kanban.db` for back-compat; additional boards live at `~/.phi/kanban/boards/<slug>/kanban.db`. The gateway-embedded dispatcher sweeps every board per tick.

**Global flags (apply to every action below):**

| Flag | Purpose |
|------|---------|
| `--board <slug>` | Operate on a specific board. Defaults to the current board (set via `phi kanban boards switch`, the `PHI_KANBAN_BOARD` env var, or `default`). |

**This is the human / scripting surface.** Agent workers spawned by the dispatcher drive the board through a dedicated `kanban_*` [toolset](../user-guide/features/kanban.md#how-workers-interact-with-the-board) (`kanban_show`, `kanban_complete`, `kanban_request_review`, `kanban_request_changes`, `kanban_block`, `kanban_create`, `kanban_link`, `kanban_comment`, `kanban_heartbeat`; orchestrator profiles also get `kanban_list` and `kanban_unblock`) instead of shelling to `phi kanban`. Workers have `PHI_KANBAN_BOARD` pinned in their env so they physically cannot see other boards.

| Action | Purpose |
|--------|---------|
| `init` | Create `kanban.db` if missing. Idempotent. |
| `boards list` / `boards ls` | List all boards with task counts. `--json`, `--all` (include archived). |
| `boards create <slug>` | Create a new board. Flags: `--name`, `--description`, `--icon`, `--color`, `--switch` (make active). Slug is kebab-case, auto-downcased. |
| `boards switch <slug>` / `boards use` | Persist `<slug>` as the active board (writes `~/.phi/kanban/current`). |
| `boards show` / `boards current` | Print the currently-active board's name, DB path, and task counts. |
| `boards rename <slug> "<name>"` | Change a board's display name. Slug is immutable. |
| `boards rm <slug>` | Archive (default) or hard-delete a board. `--delete` skips the archive step. Archived boards move to `boards/_archived/<slug>-<ts>/`. Refused for `default`. |
| `create "<title>"` | Create a new task on the active board. Flags: `--body`, `--assignee`, `--parent` (repeatable), `--workspace scratch\|worktree\|dir:<path>`, `--tenant`, `--priority`, `--triage`, `--idempotency-key`, `--max-runtime`, `--max-retries`, `--skill` (repeatable). |
| `list` / `ls` | List tasks on the active board. Filter with `--mine`, `--assignee`, `--status`, `--tenant`, `--archived`, `--json`. |
| `show <id>` | Show a task with comments and events. `--json` for machine output. |
| `assign <id> <profile>` | Assign or reassign. Use `none` to unassign. Refused while task is running. |
| `link <parent> <child>` | Add a dependency. Cycle-detected. Both tasks must be on the same board. |
| `unlink <parent> <child>` | Remove a dependency. |
| `claim <id>` | Atomically claim a ready task. Prints resolved workspace path. |
| `comment <id> "<text>"` | Append a comment. The next worker that claims the task reads it as part of its `kanban_show()` response. |
| `complete <id>` | Mark task done. Flags: `--result`, `--summary`, `--metadata`. |
| `block <id> "<reason>"` | Mark task blocked for human input. Also appends the reason as a comment. |
| `request-review <id>` | Move a task to `review` with a reviewer handoff — NOT a block. Flags: `--summary`, `--metadata`, `--reviewer` (reassigns before review dispatch). |
| `request-changes <id> <reason>` | Reviewer verdict for an active review run: close the review attempt and route the task back to its original implementer. |
| `reopen-review <id>...` | Send review task(s) back for changes (`review` → ready/todo). Flag: `--reason` (appended as a comment). |
| `schedule <id> "<reason>"` | Park time-delay/follow-up work in `scheduled` so it is not shown as a human blocker. |
| `unblock <id>` | Restore a blocked task to its source phase (`review` or `ready`), or `todo` while dependencies remain open. |
| `archive <id>` | Hide from default list. `gc` will remove scratch workspaces. |
| `tail <id>` | Follow a task's event stream. |
| `dispatch` | One dispatcher pass on the active board. Flags: `--dry-run`, `--max N`, `--failure-limit N`, `--json`. |
| `context <id>` | Print the full context a worker would see (title + body + parent results + comments). |
| `specify <id>` / `specify --all` | Flesh out a triage-column task into a concrete spec (title + body with goal, approach, acceptance criteria) via the auxiliary LLM, then promote it to `todo`. Flags: `--tenant` (scope `--all` to one tenant), `--author`, `--json`. Configure the model under `auxiliary.triage_specifier` in `config.yaml`. |
| `decompose <id>` / `decompose --all` | Fan a triage-column task out into a graph of child tasks routed to specialist profiles by description. Falls back to specify-style single-task promotion when the LLM decides the task doesn't benefit from fan-out. Same flags as `specify`. Configure the decomposer model under `auxiliary.kanban_decomposer` in `config.yaml`; `kanban.orchestrator_profile` only controls who owns the root/orchestration task after fan-out. Also runs automatically every dispatcher tick when `kanban.auto_decompose: true` (the default). See [Auto vs Manual orchestration](../user-guide/features/kanban.md#auto-vs-manual-orchestration). |
| `gc` | Remove scratch workspaces for archived tasks. |

Examples:

```bash
# Create a second board and put a task on it without switching away.
phi kanban boards create atm10-server --name "ATM10 Server" --icon 🎮
phi kanban --board atm10-server create "Restart server" --assignee ops

# Switch the active board for subsequent calls.
phi kanban boards switch atm10-server
phi kanban list                  # shows atm10-server tasks

# Archive a board (recoverable) or hard-delete it.
phi kanban boards rm atm10-server
phi kanban boards rm atm10-server --delete
```

Board resolution order (highest precedence first): `--board <slug>` flag → `PHI_KANBAN_BOARD` env var → `~/.phi/kanban/current` file → `default`.

All actions are also available as a slash command in the gateway (`/kanban …`), with the same argument surface — including `boards` subcommands and the `--board` flag.

For the full design — comparison with Cline Kanban / Paperclip / NanoClaw / Gemini Enterprise, eight collaboration patterns, four user stories, concurrency correctness proof — see the [Kanban user guide](../user-guide/features/kanban.md).

## `phi egress`

Outbound credential-injection firewall for remote terminal sandboxes. Wraps the [iron-proxy](https://github.com/ironsh/iron-proxy) daemon — a TLS-intercepting proxy that swaps opaque proxy tokens for real upstream API credentials at the network boundary, so sandboxes never hold real keys. Disabled by default; see the full [Egress proxy](../user-guide/egress/iron-proxy.md) page for setup + architecture.

```bash
phi egress install                  # download the pinned iron-proxy binary
phi egress install --force          # check and repair the managed copy

phi egress setup                    # interactive wizard: CA, mappings, config
phi egress setup --tunnel-port N    # override the tunnel listener port (default 9090)
phi egress setup --from-bitwarden   # use Bitwarden Secrets Manager as credential source
phi egress setup --no-bitwarden     # explicitly switch back to env-based credentials
phi egress setup --rotate-tokens    # mint fresh proxy tokens (default preserves existing)

phi egress start                    # spawn the managed proxy daemon
phi egress stop                     # SIGTERM (then SIGKILL after 5s grace)
phi egress restart                  # stop (if running) then start — needed for secret changes
phi egress reload                   # hot-reload the ruleset in-place (no restart, no dropped
                                       #   connections) via the loopback management API

phi egress status                   # binary + config + pid + listening + mappings
phi egress status --show-tokens     # print proxy tokens in full (default: redacted)

phi egress disable                  # flip proxy.enabled = false (does not stop a running proxy)
phi egress config                   # print the path to proxy.yaml for inspection
```

### Common flows

```bash
# First-time setup
export OPENROUTER_API_KEY=…
phi egress setup && phi egress start
phi config set terminal.backend docker   # if not already

# Switching credential source after the fact
phi egress setup --from-bitwarden       # env → bitwarden
phi egress setup --no-bitwarden         # bitwarden → env
# (just `setup` without either flag preserves the existing mode)

# Rotating all tokens (e.g. after a suspected token leak)
phi egress setup --rotate-tokens    # setup offers to restart the running daemon for you
# (running sandboxes still hold old tokens; restart them too)

# Adding a new upstream
# Edit ~/.phi/config.yaml proxy.extra_allowed_hosts: [api.example.com]
phi egress setup
phi egress restart                  # one-command apply (stop + start)
```

### Diagnostic shortcuts

```bash
phi egress status                     # current state in one view
cat ~/.phi/proxy/proxy.yaml           # the rendered iron-proxy config
tail -20 ~/.phi/proxy/iron-proxy.log  # daemon-level diagnostics
tail -f ~/.phi/proxy/iron-proxy.log | jq  # daemon + per-request log (line-delimited JSON; v0.39 combines both streams)
```

Common failure modes + recovery are covered in [Egress proxy → Troubleshooting](../user-guide/egress/iron-proxy.md#troubleshooting).

## `phi project`

```bash
phi project <create|list|show|add-folder|remove-folder|rename|set-primary|use|archive|restore|bind-board>
```

Projects are human-named workspaces that can span multiple folders / repos. They anchor desktop session grouping and, when bound to a kanban board, give tasks a deterministic worktree + branch convention. State is per-profile.

| Subcommand | Description |
|------------|-------------|
| `create` | Create a new project. |
| `list` (alias `ls`) | List projects. |
| `show` | Show a project's details. |
| `add-folder` | Add a folder / repo to a project. |
| `remove-folder` | Remove a folder from a project. |
| `rename` | Rename a project. |
| `set-primary` | Set the primary folder. |
| `use` | Set the active project. |
| `archive` | Archive a project (recoverable). |
| `restore` | Restore an archived project. |
| `bind-board` | Bind a kanban board to this project. |

## `phi webhook`

```bash
phi webhook <subscribe|list|remove|test>
```

Manage dynamic webhook subscriptions for event-driven agent activation. Requires the webhook platform to be enabled in config — if not configured, prints setup instructions.

| Subcommand | Description |
|------------|-------------|
| `subscribe` / `add` | Create a webhook route. Returns the URL and HMAC secret to configure on your service. |
| `list` / `ls` | Show all agent-created subscriptions. |
| `remove` / `rm` | Delete a dynamic subscription. Static routes from config.yaml are not affected. |
| `test` | Send a test POST to verify a subscription is working. |

### `phi webhook subscribe`

```bash
phi webhook subscribe <name> [options]
```

| Option | Description |
|--------|-------------|
| `--prompt` | Prompt template with `{dot.notation}` payload references. |
| `--events` | Comma-separated event types to accept (e.g. `issues,pull_request`). Empty = all. |
| `--description` | Human-readable description. |
| `--skills` | Comma-separated skill names to load for the agent run. |
| `--deliver` | Delivery target: `log` (default), `telegram`, `discord`, `slack`, `github_comment`. |
| `--deliver-chat-id` | Target chat/channel ID for cross-platform delivery. |
| `--secret` | Custom HMAC secret. Auto-generated if omitted. |
| `--deliver-only` | Skip the agent — deliver the rendered `--prompt` as the literal message. Zero LLM cost, sub-second delivery. Requires `--deliver` to be a real target (not `log`). |
| `--mirror-to-session` | Also write each delivered message into the target chat's session, so replying to it in that chat has context. Off by default; only enable it for sources whose content you trust in your conversation. |
| `--script` | Filter/transform script under `~/.phi/scripts/`. The webhook payload is passed as JSON on stdin; JSON stdout replaces the payload, and empty stdout, `[SILENT]`, or a nonzero exit code ignores the webhook. See [Script Filters and Transforms](../user-guide/messaging/webhooks.md#script-filters-and-transforms). |
| `--route-profile` | Bind the route to a multiplexed profile: it is then reachable only at `/p/<profile>/webhooks/<name>` and the agent runs as that profile. Validated against existing profiles; kept on update when omitted. Not the same as the global `-p/--profile`, which selects the gateway whose subscriptions file is written. See [Multi-profile gateways](../user-guide/multi-profile-gateways.md). |

Subscriptions persist to `~/.phi/webhook_subscriptions.json` and are hot-reloaded by the webhook adapter without a gateway restart. Re-running `subscribe` for an existing name keeps its secret and profile binding unless you pass `--secret` / `--route-profile`.

## `phi doctor`

```bash
phi doctor [--fix]
```

| Option | Description |
|--------|-------------|
| `--fix` | Attempt automatic repairs where possible. |

Exit status: `0` when the report lists no unresolved problems, `1` when at least one remains (including problems `--fix` could not repair), so a health gate or CI step can trust `phi doctor` as a check.

The **API Connectivity** section includes an `IPv6 route` check: it opens one short (2 s) IPv6 TCP connection to a known dual-stack host. A route that is advertised but only times out (a blackholed IPv6 prefix) is reported as a warning naming the remedy, `network.force_ipv4: true`. Having no IPv6 route at all is healthy and reported as OK; the check is skipped when `force_ipv4` is already set.

Custom-endpoint config checks (both warn-only; `--fix` does not rewrite them):

- `custom_providers` that is not a YAML list (for example a string left by a bad `config set`) is reported as an error naming the key and the received type — the runtime ignores every custom endpoint until it is a list again.
- A legacy `custom_providers` list entry with no matching `providers:` entry (same endpoint URL) is reported with the move to make: such an entry is still served from the retired list store (the model picker and the Custom Endpoints page dual-read it) rather than the `providers:` map every other surface edits, and the one-shot v12 migration that moved the list into `providers:` does not run again.

**Config Structure** also flags any list/mapping setting stored as one quoted string (`plugins.enabled: '["a","b"]'`, `model_catalog.excluded_providers: '["openai-api"]'` — the shape older `config set` versions wrote): every reader ignores such a string, so the plugins silently stay unmounted and the exclusion never applies. The finding names the key and the `phi config set <key> '<literal>'` command that stores a real list; the same warning appears in the startup banner. `--fix` does not rewrite the file.

## `phi dump`

```bash
phi dump [--show-keys]
```

Outputs a compact, plain-text summary of your entire Phi setup. Designed to be copy-pasted into Discord, GitHub issues, or Telegram when asking for support — no ANSI colors, no special formatting, just data.

| Option | Description |
|--------|-------------|
| `--show-keys` | Show redacted API key prefixes (first and last 4 characters) instead of just `set`/`not set`. |

### What it includes

| Section | Details |
|---------|---------|
| **Header** | Phi version, release date, git commit hash |
| **Environment** | OS, Python version, OpenAI SDK version |
| **Identity** | Active profile name, PHI_HOME path |
| **Model** | Configured default model and provider |
| **Terminal** | Backend type (local, docker, ssh, etc.) |
| **API keys** | Presence check for all 22 provider/tool API keys |
| **Features** | Enabled toolsets, MCP server count, memory provider |
| **Services** | Gateway status, configured messaging platforms |
| **Workload** | Cron job counts, installed skill count |
| **Config overrides** | Any config values that differ from defaults. Credentials in them are redacted: a `fallback_providers` entry's `api_key`, and credentials in its `base_url` (userinfo, `key`/token query parameters, signed-URL signatures). |

### Example output

```
--- phi dump ---
version:          0.8.0 (2026.4.8) [af4abd2f]
os:               Linux 6.14.0-37-generic x86_64
python:           3.11.14
openai_sdk:       2.24.0
profile:          default
phi_home:      ~/.phi
model:            anthropic/claude-opus-4.6
provider:         openrouter
terminal:         local

api_keys:
  openrouter           set
  openai               not set
  anthropic            set
  nous                 not set
  firecrawl            set
  ...

features:
  toolsets:           all
  mcp_servers:        0
  memory_provider:    built-in
  gateway:            running (systemd)
  platforms:          telegram, discord
  cron_jobs:          3 active / 5 total
  skills:             42

config_overrides:
  agent.max_turns: 250
  compression.threshold: 0.85
  display.streaming: True
--- end dump ---
```

### When to use

- Reporting a bug on GitHub — paste the dump into your issue
- Asking for help in Discord — share it in a code block
- Comparing your setup to someone else's
- Quick sanity check when something isn't working

:::tip
`phi dump` is specifically designed for sharing. For interactive diagnostics, use `phi doctor`. For a visual overview, use `phi status`.
:::

## `phi debug`

```bash
phi debug share [options]
```

Upload a debug report (system info + recent logs) to a paste service and get a shareable URL. Useful for quick support requests — includes everything a helper needs to diagnose your issue.

| Option | Description |
|--------|-------------|
| `--lines <N>` | Number of log lines to include per log file (default: 200). |
| `--expire <days>` | Paste expiry in days (default: 7). |
| `--nous` | Upload to Nous-internal diagnostics storage instead of a public paste service. Use this when Nous support asks for a private diagnostic bundle. |
| `--local` | Print the report locally instead of uploading. |
| `--no-redact` | Disable upload-time secret redaction. By default, uploads are redacted. |

The report includes system info (OS, Python version, Phi version), recent agent, gateway, GUI/dashboard, and desktop logs (512 KB limit per file), plus the update and Desktop update hand-off logs when present, and redacted API key status. By default, uploads are redacted so secrets are not included; this covers the system dump (including config values such as `fallback_providers` entries and credentials in their URLs) as well as the logs, and the gateway `/debug` report too.

Default uploads use public paste services tried in order: paste.rs, dpaste.com. `--nous` uploads the same debug bundle to private Nous diagnostics storage instead; the returned viewer link is for the Nous team and auto-deletes after 14 days.

### Examples

```bash
phi debug share              # Upload debug report, print URL
phi debug share --lines 500  # Include more log lines
phi debug share --expire 30  # Keep paste for 30 days
phi debug share --nous       # Upload a private diagnostics bundle for Nous support
phi debug share --local      # Print report to terminal (no upload)
```

## `phi backup`

```bash
phi backup [options]
```

Create a zip archive of your Phi configuration, skills, sessions, and data. The backup excludes the phi-agent codebase itself, and it does not nest earlier backup artifacts (`backups/`, `state-snapshots/`) — each of those already contains its own copy of `state.db`.

| Option | Description |
|--------|-------------|
| `-o`, `--output <path>` | Output path for the zip file (default: `~/phi-backup-<timestamp>.zip`). |
| `-q`, `--quick` | Quick snapshot: only critical state files (config.yaml, state.db, .env, auth, cron jobs). Much faster than a full backup. |
| `-l`, `--label <name>` | Label for the snapshot (only used with `--quick`). |
| `-k`, `--keep <N>` | After a full backup, delete older `phi-backup-*.zip` files in the output directory beyond the newest N (default 3; `0` keeps everything). Custom-named zips are never touched. |

The backup uses SQLite's `backup()` API for safe copying, so it works correctly even when Phi is running (WAL-mode safe).

**Exit status:** `0` only when every selected file landed in the archive. If some files could not be added (`Backup incomplete: …`), the zip is kept so the rest can still be restored, but the command exits `1` — a cron or systemd timer will not report a partial archive as success, and `--keep` pruning is skipped so older complete archives survive. `2` means another backup was already running.

**What's excluded from the zip:**

- `*.db-wal`, `*.db-shm`, `*.db-journal` — SQLite's WAL / shared-memory / journal sidecars. The `*.db` file already got a consistent snapshot via `sqlite3.backup()`; shipping the live sidecars alongside it would let a restore see a half-committed state.
- `checkpoints/` — per-session trajectory caches. Hash-keyed and regenerated per session; wouldn't port cleanly to another install anyway.
- `models/`, `runtimes/`, `node/` at the root of `~/.phi` (and of each `profiles/<name>/`) — regenerable runtime downloads, often tens of GB. Deeper directories with the same names (a skill's `models/`) are kept.
- Browser profiles: `browser-profile/` (the real-profile snapshot — copied Cookies / Login Data), `browser-profiles/` (live CDP profiles) at any depth, and `browser_profiles/` (the Browser Use CLI backend's Chromium user-data dir, with its own Login Data / Cookies) at the root of `~/.phi` and of each `profiles/<name>/`. Credential stores that must never enter an archive; all are regenerated on the next launch.
- Regenerable entries of `cache/` at those same roots — model/plugin catalogs, stamps, browser profiles, tool-output spill. Durable artifacts stay in: `cache/images`, `cache/audio`, `cache/videos`, `cache/documents`, `cache/screenshots` (media delivered to or received from you) and `cache/citations` (the grounded-citations ledger). A deeper `cache/` (inside a skill) is kept whole.
- Unix sockets, devices, and symlinks — a zip cannot hold them; before they were excluded, a stray `gateway.sock` made every full backup report `Backup incomplete`.
- The `phi-agent` code itself (this is a user-data backup, not a repo snapshot).

### Examples

```bash
phi backup                           # Full backup to ~/phi-backup-*.zip
phi backup -o ~/backups/phi.zip   # Full backup to specific path
phi backup --quick                   # Quick state-only snapshot
phi backup --quick --label "pre-upgrade"  # Quick snapshot with label
```

## `phi checkpoints`

```bash
phi checkpoints [COMMAND]
```

Inspect and manage the shadow git store at `~/.phi/checkpoints/` — the storage layer behind the in-session `/rollback` command. Safe to run any time; does not require the agent to be running.

| Subcommand | Description |
|------------|-------------|
| `status` (default) | Show total size, project count, and per-project breakdown. Bare `phi checkpoints` is equivalent. |
| `list` | Alias for `status`. |
| `prune` | Force a cleanup sweep — delete orphan and stale projects, GC the store, enforce the size cap. Ignores the 24h idempotency marker. |
| `clear` | Delete the entire checkpoint base. Irreversible; asks for confirmation unless `-f`. |
| `clear-legacy` | Delete only the `legacy-<timestamp>/` archives produced by the v1→v2 migration. Exits `2` (after printing `Could not delete N archive(s)`) when any archive could not be removed, e.g. read-only git objects on Windows. |

### Options

| Option | Subcommand | Description |
|--------|------------|-------------|
| `--limit N` | `status`, `list` | Max projects to list (default 20). |
| `--retention-days N` | `prune` | Drop projects whose `last_touch` is older than N days (default 7). |
| `--max-size-mb N` | `prune` | After the orphan/stale pass, drop the oldest commit per project until total store size ≤ N MB (default 500). |
| `--keep-orphans` | `prune` | Skip deleting projects whose working directory no longer exists. |
| `-f`, `--force` | `clear`, `clear-legacy` | Skip the confirmation prompt. |

### Examples

```bash
phi checkpoints                                  # status overview
phi checkpoints prune --retention-days 3         # aggressive cleanup
phi checkpoints prune --max-size-mb 200          # tighten size cap once
phi checkpoints clear-legacy -f                  # drop v1 archive dirs
phi checkpoints clear -f                         # wipe everything
```

See [Checkpoints and `/rollback`](../user-guide/checkpoints-and-rollback.md) for the full architecture and the in-session commands.

## `phi import`

```bash
phi import <zipfile> [options]
```

Restore a previously created Phi backup into your Phi home directory. All files in the archive overwrite existing files in your Phi home; `--force` only skips the confirmation prompt that fires when the target already has a Phi installation.

| Option | Description |
|--------|-------------|
| `-f`, `--force` | Skip the existing-installation confirmation prompt. |

:::warning
Stop the gateway before importing to avoid conflicts with running processes.
:::

**Exit status:** `1` when the archive is damaged — before anything is written, every member is decompressed once and its CRC checked; if any fail, the command prints `Error: backup archive is damaged (N member(s) …)` with the offending members and stops with the Phi home untouched. Also `1` when any file from the archive could not be restored (listed under `Warnings (N files skipped)` and summarised as `Import incomplete: …`). The files that did land stay in place, but a script or the dashboard will not report a partial restore as success. Runtime files the import deliberately keeps from this machine (`gateway.pid`, `gateway_state.json`, …) and the older-backup session warning below do not change the exit status.

### SQLite databases

`.db` members (`state.db`, `kanban.db`, `response_store.db`, …) are not published with a rename like ordinary files. Renaming would replace the file's inode while a gateway, dashboard, or WebUI process still holds the old one open: that process would keep reading pre-import pages and keep writing sessions nobody else can see, and those sessions would simply be absent from the database everyone opens next — with nothing logged. Instead the imported pages are written **into the existing database file**, the same way `/snapshot restore` does it, so every open connection converges on the imported data.

If the live database cannot be replaced safely — the page copy failed *and* another process still holds the file open — the import leaves that database untouched and lists it under `Warnings (N files skipped)`. Stop the holding processes and re-run.

Importing an older backup over newer work is still allowed, but it is no longer silent. When the imported `state.db` holds fewer messages than the one it replaced, the summary reports it:

```
  ⚠ Session data replaced by older backup contents:
    state.db: 12 session(s) / 8912 message(s) -> 3 / 24
    Anything recorded after the backup was taken is not in it.
    Recover from a newer backup or snapshot: phi snapshot list
```

### Examples
```bash
phi import ~/phi-backup-20260423.zip           # Prompts before overwriting existing config
phi import ~/phi-backup-20260423.zip --force   # Overwrite without prompting
```

## `phi logs`

```bash
phi logs [log_name] [options]
```

View, tail, and filter Phi log files. All logs are stored in `~/.phi/logs/` (or `<profile>/logs/` for non-default profiles).

### Log files

| Name | File | What it captures |
|------|------|-----------------|
| `agent` (default) | `agent.log` | All agent activity — API calls, tool dispatch, session lifecycle (INFO and above) |
| `errors` | `errors.log` | Warnings and errors only — a filtered subset of agent.log |
| `gateway` | `gateway.log` | Messaging gateway activity — platform connections, message dispatch, webhook events |
| `gui` | `gui.log` | Dashboard / TUI-gateway / PTY-bridge / websocket events |
| `desktop` | `desktop.log` | Electron desktop app — boot, backend spawn output, and recent Python tracebacks |
| `mcp` | `mcp-stderr.log` | stderr of every stdio MCP server, one `starting MCP server` banner per launch |
| `update` | `update.log` | Full stdout/stderr mirror of `phi update` runs (append-only) — the root cause of update/dependency failures |
| `handoff` | `desktop-update-handoff.log` | Desktop-driven update hand-off stages, including the Desktop rebuild retry output |

### Options

| Option | Description |
|--------|-------------|
| `log_name` | Which log to view: `agent` (default), `errors`, `gateway`, `gui`, `desktop`, `update`, `handoff`, or `list` to show available files with sizes. |
| `-n`, `--lines <N>` | Number of lines to show (default: 50). |
| `-f`, `--follow` | Follow the log in real time, like `tail -f`. Press Ctrl+C to stop. |
| `--level <LEVEL>` | Minimum log level to show: `DEBUG`, `INFO`, `WARNING`, `ERROR`, `CRITICAL`. |
| `--session <ID>` | Filter lines containing a session ID substring. |
| `--since <TIME>` | Show lines from a relative time ago: `30m`, `1h`, `2d`, etc. Supports `s` (seconds), `m` (minutes), `h` (hours), `d` (days). |
| `--component <NAME>` | Filter by component: `gateway`, `agent`, `tools`, `cli`, `cron`. |

A line without its own timestamp, such as a traceback frame or the rest of a multi-line message, is shown or hidden together with the timestamped line above it.

### Examples

```bash
# View the last 50 lines of agent.log (default)
phi logs

# Follow agent.log in real time
phi logs -f

# View the last 100 lines of gateway.log
phi logs gateway -n 100

# Show only warnings and errors from the last hour
phi logs --level WARNING --since 1h

# Filter by a specific session
phi logs --session abc123

# Follow errors.log, starting from 30 minutes ago
phi logs errors --since 30m -f

# List all log files with their sizes
phi logs list
```

### Filtering

Filters can be combined. When multiple filters are active, a log line must pass **all** of them to be shown:

```bash
# WARNING+ lines from the last 2 hours containing session "tg-12345"
phi logs --level WARNING --since 2h --session tg-12345
```

Lines without a parseable timestamp are included when `--since` is active (they may be continuation lines from a multi-line log entry). Lines without a detectable level are included when `--level` is active.

### Log rotation

Phi uses Python's `RotatingFileHandler`. Old logs are rotated automatically — look for `agent.log.1`, `agent.log.2`, etc. The `phi logs list` subcommand shows all log files including rotated ones.


## `phi prompt-size`

```bash
phi prompt-size [--platform <name>] [--json]
```

Reports the fixed prompt budget for a fresh session — what gets sent on every
API call *before* any conversation content. Useful when a downstream adapter or
proxy has a tighter prompt budget than the model's context window, or when you
want to see which block (skills index, memory, profile) dominates.

It builds the same system prompt the agent would, then breaks it down:

- **System prompt total** — full assembled prompt (identity, guidance, skills
  index, context files, memory, profile, timestamp).
- **Skills index** — the `<available_skills>` block. This is often the largest
  single block when many skills are installed.
- **Memory** and **user profile** — your `MEMORY.md` / `USER.md` snapshots.
- **Prompt tiers** — stable / context / volatile, matching how Phi layers
  the prompt for cache-friendliness.
- **Tool schemas** — the JSON for all enabled tools (the other half of the
  fixed per-call payload).

Runs entirely offline — no API call, works with no credentials configured.

```bash
# Human-readable breakdown for the CLI platform (default)
phi prompt-size

# Simulate a messaging platform's prompt (different platform hint)
phi prompt-size --platform telegram

# Machine-readable output for scripts
phi prompt-size --json
```

:::tip
The skills index and tool schemas scale with how many skills and tools you have
enabled. To shrink the prompt, disable unused toolsets (`phi tools`) or
uninstall skills you don't need (`phi skills`). Context files (AGENTS.md,
.cursorrules) in your current directory also count toward the total.
:::

## `phi config`

```bash
phi config <subcommand>
```

Subcommands:

| Subcommand | Description |
|------------|-------------|
| `show` | Show current config values. |
| `edit` | Open `config.yaml` in your editor. |
| `get <key> [--json] [--raw]` | Print a single config value by dotted key (e.g. `phi config get model.default`). `--json` emits machine-readable output. Credential-shaped values (`api_key`, `*_TOKEN`, `*_SECRET`, `password`, …) are masked (`sk-o...7890`) because the agent runs this from sessions whose transcripts persist; `--raw` prints the real value (or set `security.redact_secrets: false`). A nested key under a known section that the schema does not define (`compression.compressor.enabled`) still prints its file value, plus a stderr notice that Phi may not read it; stdout and the exit code (0) are unchanged. |
| `set <key> <value> [--force]` | Set a config value. Dotted paths go to `config.yaml`; every `UPPER_SNAKE` name (`OPENROUTER_API_KEY`, `DISCORD_HOME_CHANNEL`, `TELEGRAM_GROUP_ALLOWED_USERS`, `PHI_TIMEZONE`, …) is an environment variable and goes to `.env` — the same file the platform setup flows and `/sethome` write, and the one every runtime reader resolves against. `config set` never writes an `UPPER_SNAKE` key into `config.yaml`, `--force` included; names on the env writer's denylist (`PHI_YOLO_MODE`, `PATH`, …) are refused outright; any other `UPPER_SNAKE` name is saved to `.env` as-is (plugins, skills and external tools read it from the process environment). A known key written under the wrong prefix (`gateway.discord.foo`, where `discord.foo` is itself a known key) is refused with a did-you-mean and nothing is written; any other unknown path under a known section (`agent.max_turnz`, or a runtime-read key that has no seeded default) is written with a did-you-mean notice, and an unknown lowercase *top-level* key is written with a notice (top-level scalars are bridged into the environment for skills). `--force` writes the refused wrong-prefix path too. Values are type-checked against the schema: a key that must hold a list or a mapping (`custom_providers`, `model.aliases`, `display.platforms`, `plugins.enabled`/`plugins.disabled`, `model_catalog.excluded_providers`, any key already holding one) refuses a plain string or a wrong-shaped literal, and a value that looks like a list/mapping but is not valid YAML/JSON is refused instead of being stored as a string — nothing is written and the error names the expected type. Pass a YAML/JSON literal (`phi config set custom_providers '[{name: x, base_url: https://...}]'`); to store a string that merely starts with `[` or `{`, quote it in YAML (`"'[text'"`). `--force` still replaces a whole mapping section; a non-list in a list slot has no override, except that a bare name for a list of names read leniently (`agent.disabled_toolsets`, `skills.disabled`) is stored as a one-item list. |
| `unset <key>` | Remove a config key, reverting it to the built-in default. For `UPPER_SNAKE` names this removes the `.env` entry and also drops a stale top-level `config.yaml` copy left by older `config set` runs (`get` reports such a copy as stale). |
| `path` | Print the config file path. |
| `env-path` | Print the `.env` file path. |
| `check` | Check for missing or stale config. |
| `migrate` | Add newly introduced options interactively. |

`config set model.provider <provider>` keeps the `model:` block on one route: a `model.base_url` /
`model.api_mode` left over from the previous provider is removed (and listed) when it is another
provider's endpoint — otherwise the new provider's key would be posted to the old endpoint and fail
with a credential error naming the wrong provider. A URL that is the new provider's own endpoint, a
named `custom_providers` entry's endpoint, or any URL under `custom`/local aliases stays; an
unrecognised host (a proxy, a LAN server) stays with a warning that it still applies.

### Dots inside key names

`phi config set/get/unset` use `.` as the nesting separator, but many real
key names contain literal dots — model IDs (`grok-4.6`, `glm-5.3-flash`),
Matrix room IDs (`!room:example.org`), versioned provider names. Two rules
make these addressable:

- **Existing keys just work.** When navigating an existing mapping, an
  existing literal key that matches the dotted remainder is preferred over
  splitting. `phi config set providers.p.models.grok-4.6.supports_vision true`
  updates the real `grok-4.6` entry (and `get`/`unset` resolve the same way).
- **Creating a new dotted key requires escaping.** Escape literal dots with a
  backslash: `phi config set 'providers.p.models.grok-4\.7.context_length' 128000`
  creates the literal `grok-4.7` key. (Quote the key so your shell keeps the
  backslash.)

If an unescaped write would create a nested mapping that shadows an existing
dotted sibling (e.g. creating `grok-4` next to an existing `grok-4.6`), the
command fails with an error instead of silently writing a phantom entry the
runtime would never read.

## `phi pairing`

```bash
phi pairing <list|approve|revoke|clear-pending>
```

| Subcommand | Description |
|------------|-------------|
| `list` | Show pending and approved users. |
| `approve <platform> <code>` | Approve a pairing code. |
| `revoke <platform> <user-id>` | Revoke a user's access. |
| `clear-pending` | Clear pending pairing codes. |

## `phi skills`

```bash
phi skills <subcommand>
```

Subcommands:

| Subcommand | Description |
|------------|-------------|
| `browse` | Paginated browser for skill registries. |
| `search` | Search skill registries. |
| `install` | Install a skill. |
| `inspect` | Preview a skill without installing it. |
| `list` | List installed skills. |
| `check` | Check installed hub skills for upstream updates. |
| `update` | Reinstall hub skills with upstream changes when available. |
| `audit` | Re-scan installed hub skills. |
| `uninstall` | Remove a hub-installed skill. |
| `reset` | Un-stick a bundled skill flagged as `user_modified` by clearing its manifest entry. With `--restore`, also replaces the user copy with the bundled version. |
| `opt-out` | Stop bundled skills from being seeded into the active profile. Writes a `.no-bundled-skills` marker so the installer, `phi update`, and any sync skip bundled-skill seeding. Safe by default — nothing on disk is touched. With `--remove`, also deletes already-present bundled skills that are **unmodified** (user-edited, hub-installed, and hand-written skills are never removed; previews and confirms first, `--yes` to skip). |
| `opt-in` | Undo `opt-out` by removing the `.no-bundled-skills` marker so bundled skills are seeded again on the next `phi update`. With `--sync`, re-seed immediately. |
| `publish` | Publish a skill to a registry. |
| `snapshot` | Export/import skill configurations. |
| `tap` | Manage custom skill sources. |
| `config` | Interactive enable/disable configuration for skills by platform. |

Common examples:

```bash
phi skills browse
phi skills browse --source official
phi skills search react --source skills-sh
phi skills search https://mintlify.com/docs --source well-known
phi skills inspect official/security/1password
phi skills inspect skills-sh/vercel-labs/json-render/json-render-react
phi skills install official/mcp/fastmcp
phi skills install skills-sh/anthropics/skills/pdf --force
phi skills install https://sharethis.chat/SKILL.md                     # Direct URL (+ referenced support files)
phi skills install https://example.com/SKILL.md --name my-skill        # Override name when frontmatter has none
phi skills check
phi skills update
phi skills config
phi skills reset google-workspace
phi skills reset google-workspace --restore --yes
phi skills opt-out                  # stop future bundled-skill seeding (nothing deleted)
phi skills opt-out --remove --yes   # also delete UNMODIFIED bundled skills
phi skills opt-in --sync            # undo: remove marker and re-seed now
```

Notes:
- `--force` can override non-dangerous policy blocks for third-party/community skills.
- `--force` does not override a `dangerous` scan verdict.
- `--source skills-sh` searches the public `skills.sh` directory.
- `--source well-known` lets you point Phi at a site exposing `/.well-known/skills/index.json`.
- `--source browse-sh` searches [browse.sh](https://browse.sh)'s catalog of 200+ site-specific browser-automation skills. Identifiers look like `browse-sh/airbnb.com/search-listings-ddgioa`.
- Passing an `http(s)://…/*.md` URL installs `SKILL.md` plus explicitly referenced files under `references/`, `templates/`, `scripts/`, `assets/`, and `examples/`. When frontmatter has no `name:` and the URL slug isn't a valid identifier, an interactive terminal prompts for a name; non-interactive surfaces (`/skills install` inside the TUI, gateway platforms) require `--name <x>` instead.

## `phi bundles`

```bash
phi bundles <subcommand>
```

Skill bundles group several skills under one `/<bundle-name>` slash command. Invoking the bundle loads every referenced skill into a single combined user message. Storage: `~/.phi/skill-bundles/<slug>.yaml`. See [Skill Bundles](../user-guide/features/skills.md#skill-bundles) for the YAML schema and behavior.

Subcommands:

| Subcommand | Description |
|------------|-------------|
| `list` | List installed bundles (default when no subcommand given) |
| `show <name>` | Show one bundle's name, description, skills, and file path |
| `create <name>` | Create a new bundle. Pass `--skill <id>` (repeat) or omit for interactive entry. `--description`, `--instruction`, `--force` available. |
| `delete <name>` | Remove a bundle file |
| `reload` | Re-scan `~/.phi/skill-bundles/` and report added/removed bundles |

Examples:

```bash
phi bundles create backend-dev \
  --skill github-code-review \
  --skill test-driven-development \
  --skill github-pr-workflow \
  -d "Backend feature work"

phi bundles list
phi bundles show backend-dev
phi bundles delete backend-dev
```

In a chat session, `/bundles` lists installed bundles and `/<bundle-name>` loads one.

## `phi curator`

```bash
phi curator <subcommand>
```

The curator is an auxiliary-model background task that periodically reviews agent-created skills, prunes stale ones, consolidates overlaps, and archives obsolete skills. Bundled and hub-installed skills are never touched. Archives are recoverable; auto-deletion never happens.

| Subcommand | Description |
|------------|-------------|
| `status` | Show curator status and skill stats |
| `run` | Trigger a curator review now (blocks until the LLM pass finishes) |
| `run --background` | Start the LLM pass in a background thread and return immediately |
| `run --dry-run` | Preview only — produce the review report with no mutations |
| `backup` | Take a manual tar.gz snapshot of `~/.phi/skills/` (curator also snapshots automatically before every real run) |
| `rollback` | Restore `~/.phi/skills/` from a snapshot (defaults to newest) |
| `rollback --list` | List available snapshots |
| `rollback --id <ts>` | Restore a specific snapshot by id |
| `rollback -y` | Skip the confirmation prompt |
| `pause` | Pause the curator until resumed |
| `resume` | Resume a paused curator |
| `pin <skill>` | Pin a skill so the curator never auto-transitions it |
| `unpin <skill>` | Unpin a skill |
| `restore <skill>` | Restore an archived skill |
| `archive <skill>` | Archive a skill manually |
| `prune` | Manually prune skills the curator would normally clean up |
| `list-archived` | List archived skills (recoverable via `restore`) |

On a fresh install the first scheduled pass is deferred by one full `interval_hours` (7 days by default) — the gateway will not curate immediately on the first tick after `phi update`. Use `phi curator run --dry-run` to preview before that happens.

See [Curator](../user-guide/features/curator.md) for behavior and config.

## `phi moa`

Configure named Mixture of Agents presets. Presets appear as selectable models under a `Mixture of Agents` provider in every model picker; `/moa <prompt>` runs one prompt through the default preset.

```bash
phi moa list
phi moa configure [name]
phi moa delete <name>
```

`phi moa configure` reuses Phi' provider → model picker for each reference model and the aggregator. A preset is an execution-mode configuration, not a primary model or provider.

## `phi fallback`

```bash
phi fallback <subcommand>
```

Manage the fallback provider chain. Fallback providers are tried in order when the primary model fails with rate-limit, overload, or connection errors.

| Subcommand | Description |
|------------|-------------|
| `list` (alias: `ls`) | Show the current fallback chain (default when no subcommand) |
| `add` | Pick a provider + model (same picker as `phi model`) and append to the chain |
| `remove` (alias: `rm`) | Pick an entry to delete from the chain |
| `clear` | Remove all fallback entries |

See [Fallback Providers](../user-guide/features/fallback-providers.md).

## `phi hooks`

```bash
phi hooks <subcommand>
```

Inspect shell-script hooks declared in `~/.phi/config.yaml`, test them against synthetic payloads, and manage the first-use consent allowlist at `~/.phi/shell-hooks-allowlist.json`.

| Subcommand | Description |
|------------|-------------|
| `list` (alias: `ls`) | List configured hooks with matcher, timeout, and consent status |
| `test <event>` | Fire every hook matching `<event>` against a synthetic payload |
| `revoke` (aliases: `remove`, `rm`) | Remove a command's allowlist entries (takes effect on next restart) |
| `doctor` | Check each configured hook: exec bit, allowlist, mtime drift, JSON validity, and synthetic run timing |

See [Hooks](../user-guide/features/hooks.md) for event signatures and payload shapes.

## `phi memory`

```bash
phi memory <subcommand>
```

Set up and manage external memory provider plugins. Bundled providers: retaindb, byterover; honcho, hindsight, supermemory, mem0, openviking and holographic (plugin catalog) after `phi plugins install <name>` (`phi update` does this automatically for a provider already named in `memory.provider`). Only one external provider can be active at a time. Built-in memory (MEMORY.md/USER.md) is always active.

Subcommands:

| Subcommand | Description |
|------------|-------------|
| `setup` | Interactive provider selection and configuration. |
| `status` | Show current memory provider config. |
| `off` | Disable external provider (built-in only). |

:::info Provider-specific subcommands
When an external memory provider is active, it may register its own top-level `phi <provider>` command for provider-specific management (e.g. `phi honcho` when Honcho is active). Inactive providers do not expose their subcommands. Run `phi --help` to see what's currently wired in.
:::

## `phi acp`

```bash
phi acp
```

Starts Phi as an ACP (Agent Client Protocol) stdio server for editor integration.

Related entrypoints:

```bash
phi-acp
python -m acp_adapter
```

Install support first:

```bash
cd ~/.phi/phi-agent && python -c "import pm; pm.sync_venv(['acp'], explicit=True)"
```

See [ACP Editor Integration](../user-guide/features/acp.md) and [ACP Internals](../developer-guide/acp-internals.md).

## `phi mcp`

```bash
phi mcp <subcommand>
```

Manage MCP (Model Context Protocol) server configurations. Running Phi itself as an MCP server moved to the `mcp-serve` plugin (`phi plugins install mcp-serve`, then `phi mcp-serve`); `phi mcp serve` prints that new spelling.

| Subcommand | Description |
|------------|-------------|
| *(none)* or `picker` | Interactive catalog picker — browse curated MCPs and install/enable/disable. |
| `catalog` | List curated MCPs (plain text, scriptable). |
| `install <name>` | Install a catalog entry (e.g. `phi mcp install deepwiki`). |
| `add <name> [--url URL] [--command CMD] [--auth oauth\|header] [--args ...]` | Add a custom MCP server with automatic tool discovery. `--args` passes the remaining argv to the stdio command, so put it last. |
| `remove <name>` (alias: `rm`) | Remove an MCP server from config. |
| `list` (alias: `ls`) | List configured MCP servers. |
| `test <name>` | Test connection to an MCP server. |
| `configure <name>` (alias: `config`) | Toggle tool selection for a server. |
| `login <name>` | Force re-authentication for an OAuth-based MCP server. |

See [MCP Config Reference](./mcp-config-reference.md), [Use MCP with Phi](../guides/use-mcp-with-phi.md), and [MCP Server Mode](../user-guide/features/mcp.md#running-phi-as-an-mcp-server).

## `phi connectors`

```bash
phi connectors <subcommand>
```

Manage hosted connector accounts (apps such as Gmail reached through the Nous tool gateway). Needs a Nous Portal sign-in. One app can have several named accounts; see [Multiple connector accounts](../user-guide/features/tool-gateway.md#multiple-connector-accounts).

| Subcommand | Description |
|------------|-------------|
| `list` | List connectors and whether each is connected. |
| `accounts [app] [--all]` | List accounts, for one app or all of them. `--all` includes retired accounts. |
| `connect <app> [--alias NAME] [--reconnect [--force]]` | Print the link to connect an account, then wait until it is connected or the deadline passes. Ctrl-C stops waiting. `--alias` names the account; a new name adds another account. `--reconnect` repairs the named account and deletes nothing; on an account that is already connected it says so and does nothing unless `--force` is given. |
| `rename <app> <name-or-label> --to <new>` | Rename an account. An unnamed account is matched by its app label. |
| `disconnect <app> [--alias NAME] [--yes]` | Remove an account. Asks to confirm unless you pass `--yes`. |

Rename needs a Nous Portal version that supports it. Until then it reports "This Nous Portal cannot rename connector accounts yet."

## `phi plugins`

```bash
phi plugins [subcommand]
```

Unified plugin management — general plugins, memory providers, and context engines in one place. Running `phi plugins` with no subcommand opens a composite interactive screen with two sections:

- **General Plugins** — multi-select checkboxes to enable/disable installed plugins
- **Provider Plugins** — single-select configuration for Memory Provider and Context Engine. Press ENTER on a category to open a radio picker.

| Subcommand | Description |
|------------|-------------|
| *(none)* | Composite interactive UI — general plugin toggles + provider plugin configuration. |
| `install <identifier> [--force] [--ref COMMIT_SHA] [--allow-removed]` | Install a plugin from the Phi plugin catalog (bare entry name), a Git URL, or `owner/repo` shorthand. Catalog names resolve to the reviewed 40-hex commit SHA and show declared capabilities. Source, checked-out revision, and a nested catalog-provenance block are recorded in the installer's `plugins/.install-metadata.json`; the `.phi-catalog.json` copy inside the plugin directory is only for convenience and is never trusted. Raw URLs are flagged as custom (unreviewed) sources. `--ref` selects a full-SHA custom pin and records the SHA actually checked out. `--allow-removed` (DANGEROUS) bypasses the removed-plugin blocklist at install and exempts that install from update, enable, and load-time kill-list checks. |
| `search [term] [--json]` | Search the Phi plugin catalog (matches entry names, descriptions, and declared tools; omit `term` to list everything). The catalog is curated in-repo (`plugin-catalog/`), refreshed from the live repo with a 6-hour cache, and falls back to the in-tree copy offline. Cataloged ≠ audited — admission reviews the entry, not the code. |
| `update <name>` | Re-pin catalog installs to the reviewed catalog SHA, or update a custom Git install from its recorded source/feed. PM validates active-plugin dependencies before code publication. Explicit custom pins move only with `install --force --ref <new-commit>`. |
| `update [--yes]` | With no name: list every installed plugin that has an update `update <name>` can apply (catalog re-pin or Git pull) plus the ones it skips and why, then ask `Update all N? [Y/n]` and update each through the single-plugin path (per-plugin consent prompts still apply). One failure does not stop the rest; exits 1 if any failed. Without a terminal nothing is updated unless `--yes` is passed; `--yes` keeps consent fail-closed (new capabilities stay ungranted). |
| `remove <name>` (aliases: `rm`, `uninstall`) | Remove an installed plugin. |
| `enable <name>` | Enable a disabled plugin. |
| `disable <name>` | Disable a plugin without removing it. |
| `list` (alias: `ls`) | List installed plugins with enabled/disabled status. |
| `doctor [path-or-id] [--ci]` | Validate a native plugin through the real manifest parser, loader, and registration path. `--ci` exits 1 on errors. |
| `pack install <path-or-url> [--force]` | Install a plugin pack (`phi-pack.yaml`) — a declarative set of plugins each pinned to an exact 40-character commit SHA. Shows a mandatory review screen (every plugin, source, pinned ref, declared capabilities), asks one confirmation for the pack contents, then runs ordinary pinned installs. Each plugin's declared capabilities still go through the standard per-plugin consent — a pack never bulk-grants. Partial failures are reported per plugin; exits non-zero when any plugin failed. Interactive only (no `--yes`). |
| `pack export [--enabled-only] [--name NAME]` | Emit a pack YAML on stdout from the current install: repo + exact SHA of each git-installed plugin plus sanitized non-secret `plugins.entries` config. Local-only plugins (no git provenance) are listed as warning comments, never as installable entries. Secrets, capability grants, and `allow_*` gates are always stripped. |
| `pack show <path-or-url>` | Dry-run: parse, validate, and display a pack without installing anything. |

Provider plugin selections are saved to `config.yaml`:
- `memory.provider` — active memory provider (empty = built-in only)
- `context.engine` — active context engine (`"compressor"` = built-in default)

General plugin disabled list is stored in `config.yaml` under `plugins.disabled`.
Git installs also record only their canonical source, exact installed revision, and
pin status in the profile-local `plugins/.install-metadata.json` sidecar. It does
not contain plugin config, environment values, secrets, or capability grants.

See [Plugins](../user-guide/features/plugins.md) and [Build a Phi Plugin](../developer-guide/plugins/index.md).

## `phi tools`

```bash
phi tools [--summary]
```

| Option | Description |
|--------|-------------|
| `--summary` | Print the current enabled-tools summary and exit. |

Without `--summary`, this launches the interactive per-platform tool configuration UI.

## `phi computer-use`

```bash
phi computer-use <subcommand>
```

Subcommands:

| Subcommand | Description |
|------------|-------------|
| `install` | Run the upstream cua-driver installer (macOS, Windows, and Linux). |
| `install --upgrade` | Re-run the installer even if cua-driver is already on PATH. The upstream script always pulls the latest release, so this performs an in-place upgrade. |
| `status` | Print whether `cua-driver` is on `$PATH` and which version is installed. |
| `doctor [--include CHECK] [--skip CHECK] [--json]` | Run cua-driver's health report and show its platform checks. |
| `permissions status [--json]` | Report macOS Accessibility and Screen Recording grants. |
| `permissions grant` | Ask macOS to grant Accessibility and Screen Recording to Cua Driver. |

`phi computer-use install` is the stable entry point for installing the
[cua-driver](https://github.com/trycua/cua) binary used by the
`computer_use` toolset. It runs the same upstream installer that
`phi tools` invokes when you first enable Computer Use, so it's safe
to use for re-running the install if the toolset toggle didn't trigger
it (for example, on returning-user setups).

If cua-driver is already present, Phi checks its version and runtime
manifest. A compatible 0.20.0 or newer installation is left in place. An old or
incomplete standard installation is repaired with the current upstream
installer. Phi never replaces a custom binary selected through
`PHI_CUA_DRIVER_CMD`; update that binary directly or remove the override.
`phi computer-use status` reports when repair is required.

The built-in `computer_use` toolset is the recommended Phi integration.
Registering raw Cua MCP tools is an alternative when you need Cua's low-level
tool vocabulary. `cua-driver skills install` detects Phi and links Cua's
skill pack into the Phi skills directory automatically.

Permission mode and capability-manifest approval
belong to runtime launch. In bounded mode Phi passes Cua's canonical
`--capability-manifest` and `--approve-capability-manifest` flags. Every MCP
transport owns a private lifecycle session inside its runtime. Public session
names label cursor and session state; they do not own or share the runtime.

`phi update` automatically re-runs the upstream installer at the end
of the update if cua-driver is on PATH, so most users will not need to
call `--upgrade` manually. Use it when upstream ships a fix you want
right now without waiting for the next Phi update.

## `phi pets`

```bash
phi pets <list|install|select|show|off|scale|remove|doctor>
```

[Petdex](https://github.com/crafter-station/petdex) is a public gallery of animated sprite pets for coding agents. Install one and Phi shows it reacting to agent activity across the CLI, TUI, and desktop app.

| Subcommand | Description |
|------------|-------------|
| `list` | Browse the petdex gallery. |
| `install` | Install a pet from the gallery. |
| `select` | Set the active pet (writes `display.pet.*`). |
| `show` | Animate the active pet in the terminal. |
| `off` | Disable the pet display. |
| `scale` | Resize the pet everywhere (`display.pet.scale`). |
| `remove` | Delete an installed pet. |
| `doctor` | Check pet setup + terminal graphics support. |

You can also generate a brand-new pet from a text description with the `/hatch` slash command. See [Pets](../user-guide/features/pets.md).

## `phi sessions`

```bash
phi sessions <subcommand>
```

Subcommands:

| Subcommand | Description |
|------------|-------------|
| `list` | List recent sessions. |
| `browse` | Interactive session picker with search and resume. Each row shows a lifecycle status tag (`done` / `intr` / `err` / `empty`, derived from the session's final message) and its message count. Press `d` on a highlighted row (while the search filter is empty) to delete that session after a y/N confirmation; while a filter is active, `d` types into the search instead. |
| `export <output> [--session-id ID]` | Export sessions to JSONL. |
| `delete <session-id>` | Delete one session. |
| `prune` | Delete sessions matching filters: time bounds `--older-than`/`--newer-than`/`--before`/`--after` (durations like `5h`/`2d`, bare days, or ISO timestamps); attributes `--source`, `--title`, `--model`, `--provider`, `--branch`, `--end-reason`, `--user`, `--chat-id`, `--chat-type`, `--cwd`; numeric bounds `--min/--max-messages`, `--min/--max-tokens`, `--min/--max-cost`, `--min/--max-tool-calls`; plus `--include-archived`, `--dry-run`, `--yes`. Default: older than 90 days. |
| `archive` | Bulk-archive (soft-hide, no deletion) sessions matching the same filters as `prune`. Requires at least one filter. |
| `stats` | Show session-store statistics. |
| `rename <session-id> <title>` | Set or change a session title. |
| `optimize` | Reclaim disk space: merge FTS5 index segments + VACUUM. Non-destructive — no session data changes. |
| `optimize-storage` | Migrate the full-text search index to the compact v23 external-content layout; on large databases this reclaims a large fraction of `state.db`. |
| `repair` | Repair a malformed `state.db` schema (e.g. `table messages_fts already exists`) so hidden sessions reappear; a backup is made first. |
| `repair-routing` | Re-attach gateway conversations stranded in session rows that lost their routing identity (a chat "jumping back in time" after a restart). Dry-run by default; `--apply` performs the adoptions (stop the gateway first); `--max-gap-seconds N` tunes the contiguity window. Only unambiguous cases are repaired. See [Sessions → Repair Stranded Gateway Sessions](../user-guide/sessions.md#repair-stranded-gateway-sessions). |
| `repair-prompts` | Report stored system prompts provably degraded by the pre-#122822 maintenance-compaction bug. Report-only by default; `--apply` clears verified rows so the next turn rebuilds them, `--json` is machine-readable (and non-interactive when combined with `--apply`), and an explicit `session_id` is a destructive override that can clear even a healthy prompt. Rows without a readable tools[] pin, or with a memory-only pin, are reported as unverifiable and left unchanged by the scan (a resumed memory-only session re-pins its full tool surface, after which a scan can clear it). Restart a running gateway after `--apply` so repaired rows take effect. See [Sessions → Repair Degraded Stored Prompts](../user-guide/sessions.md#repair-degraded-stored-prompts). |
| `repair-profiles` | Settle session, routing, Telegram-topic and voice-mode state that landed under the wrong profile (rows in another profile's store, labels disagreeing with the session key, parent links crossing profiles, index rows for deleted profiles). Dry-run by default; `--apply` performs the repairs after snapshotting every store (stop the gateway first); `--legacy-main rekey\|move` decides what `agent:main` rows inside a named profile's store are; `--json` for automation. See [Sessions → Repair State Crossed Between Profiles](../user-guide/sessions.md#repair-state-crossed-between-profiles). |
| `recover` | Offline, non-destructive recovery of a damaged `state.db` into a separate clean database. |
| `retitle-skills` | Regenerate titles for sessions opened with a `/skill`, using what the user actually typed; lists changes unless `--apply` is passed. |

## `phi insights`

```bash
phi insights [--days N] [--source platform]
```

| Option | Description |
|--------|-------------|
| `--days <n>` | Analyze the last `n` days (default: 30). |
| `--source <platform>` | Filter by source such as `cli`, `telegram`, or `discord`. |

## `phi import-agent`

```bash
phi plugins install agent-importers   # once; the command comes from this official plugin
phi import-agent [openclaw|claude-code|codex|cursor] [options]
```

Import an **OpenClaw** (`~/.openclaw`), **Claude Code** (`~/.claude`), **OpenAI Codex CLI** (`~/.codex`) or **Cursor** (`~/.cursor`) setup into Phi: instructions and rules become memory entries, `Bash(...)` permission rules become `command_allowlist`/`approvals.deny`, MCP servers land in `mcp_servers`, and skills are copied. Always previews first. API keys and credentials are never imported, except OpenClaw's allowlisted keys when you pass `--migrate-secrets`. `--sync` re-imports registered Claude Code, Codex and Cursor sources that changed. On a fresh install, `phi setup` offers to install the plugin and run the import for you when it finds one of these agents.

The command moved out of core into the official `agent-importers` plugin, together with `phi claw` (OpenClaw migration), whose spelling the plugin keeps. Without the plugin, `phi import-agent` and `phi claw` print the install line. See the **[import guide](../user-guide/import-from-other-agents.md)** for options and mapping tables.

### OpenClaw: `phi import-agent openclaw`

```bash
phi import-agent openclaw [options]    # same as the older spelling: phi claw migrate [options]
phi claw cleanup [--source <path>] [--dry-run] [--yes]
```

Migrate your OpenClaw setup to Phi. Reads from `~/.openclaw` (or a custom path) and writes to `~/.phi`. Automatically detects legacy directory names (`~/.clawdbot`, `~/.moltbot`) and config filenames (`clawdbot.json`, `moltbot.json`).

| Option | Description |
|--------|-------------|
| `--dry-run` | Preview what would be migrated without writing anything. |
| `--preset <name>` | Migration preset: `full` (all compatible settings) or `user-data` (excludes infrastructure config). Neither preset imports secrets — pass `--migrate-secrets` explicitly. |
| `--overwrite` | Overwrite existing Phi files on conflicts (default: refuse to apply when the plan has conflicts). |
| `--migrate-secrets` | Include API keys in migration. Required even under `--preset full`. |
| `--no-backup` | Skip the pre-migration zip snapshot of `~/.phi/` (by default a single restore-point archive is written to `~/.phi/backups/pre-migration-*.zip` before apply; restorable with `phi import`). |
| `--source <path>` | Custom OpenClaw directory (default: `~/.openclaw`). |
| `--workspace-target <path>` | Target directory for workspace instructions (AGENTS.md). |
| `--skill-conflict <mode>` | Handle skill name collisions: `skip` (default), `overwrite`, or `rename`. |
| `--yes` | Skip the confirmation prompt. |

`phi claw cleanup` renames leftover OpenClaw directories to `*.pre-migration` once you have migrated (OpenClaw stops working after this; rename them back to undo).

#### What gets migrated

The migration covers 30+ categories across persona, memory, skills, model providers, messaging platforms, agent behavior, session policies, MCP servers, TTS, and more. Items are either **directly imported** into Phi equivalents or **archived** for manual review.

**Directly imported:** SOUL.md, MEMORY.md, USER.md, AGENTS.md, skills (4 source directories), default model, custom providers, MCP servers, messaging platform tokens and allowlists (Telegram, Discord, Slack, WhatsApp, Signal, Matrix, Mattermost), agent defaults (reasoning effort, compression, human delay, timezone, sandbox), approval rules, TTS config, browser settings, tool settings, exec timeout, command allowlist, gateway config, and API keys from 3 sources.

**Archived for manual review:** Cron jobs, plugins, hooks/webhooks, memory backend (QMD), skills registry config, UI/identity, logging, multi-agent setup, channel bindings, IDENTITY.md, TOOLS.md, HEARTBEAT.md, BOOTSTRAP.md.

**API key resolution** checks three sources in priority order: config values → `~/.openclaw/.env` → `auth-profiles.json`. All token fields handle plain strings, env templates (`${VAR}`), and SecretRef objects.

For the complete config key mapping, SecretRef handling details, and post-migration checklist, see the **[full migration guide](../guides/migrate-from-openclaw.md)**.

#### Examples

```bash
# Preview what would be migrated
phi import-agent openclaw --dry-run

# Full migration (all compatible settings, no secrets)
phi import-agent openclaw --preset full

# Full migration including API keys
phi import-agent openclaw --preset full --migrate-secrets

# Migrate user data only (no secrets), overwrite conflicts
phi import-agent openclaw --preset user-data --overwrite

# Migrate from a custom OpenClaw path
phi import-agent openclaw --source /home/user/old-openclaw
```

## `phi serve`

```bash
phi serve [options]
```

Start the Phi **backend server** — the JSON-RPC/WebSocket gateway the [desktop app](../user-guide/desktop.md) and remote clients connect to. It is the same server `phi dashboard` runs, but **headless**: it never opens a browser UI. The desktop app launches its own `phi serve` backend; use this command directly when you want a headless backend on a remote host. Accepts the same `--host` / `--port` / `--insecure` / `--skip-build` / `--stop` / `--status` options as `phi dashboard` below (a non-loopback bind engages the same auth gate). Requires the `[web]` extra; the embedded Chat socket additionally needs `[pty]` on a POSIX host.

**Port conflicts:** if the requested port (default `9119`) is already held by another process (e.g. a second `phi serve` or the gateway), the command prints a machine-readable sentinel line `BACKEND_PORT_IN_USE port=<port>` to stdout, a human hint naming the likely holder, and exits with code **75** (`EX_TEMPFAIL`) instead of a generic error — so scripts and the desktop app can tell "port occupied" apart from "backend broken". Pass `--port 0` to bind a free ephemeral port (the successful boot announces the chosen port via `PHI_BACKEND_READY port=<port>`).

## `phi dashboard`

```bash
phi dashboard [options]
```

Launch the web dashboard to manage configuration, API keys, and sessions. For a headless backend, use [`phi serve`](#phi-serve). FastAPI, Uvicorn, and the platform PTY helper are core dependencies. The `web` extra adds exact HTTP-stack constraints and is selected by standard PM setup through `all`. If dependencies are damaged, run `phi pm repair`. The embedded Chat tab requires a POSIX PTY environment, such as Linux, macOS, or WSL2. See [Web Dashboard](../user-guide/features/web-dashboard.md).

| Option | Default | Description |
|--------|---------|-------------|
| `--port` | `9119` | Port to run the web server on |
| `--host` | `127.0.0.1` | Bind address |
| `--no-open` | — | Don't auto-open the browser |
| `--insecure` | off | **Deprecated / no-op.** Formerly bypassed auth on a non-loopback bind. Since the June 2026 hardening a public bind *always* requires an auth provider (password or OAuth). Bind `127.0.0.1` and tunnel to keep it local. |
| `--skip-build` | off | Skip the web UI build step and serve the existing `dist` directly. Useful for non-interactive contexts (Windows Scheduled Tasks, CI) where npm isn't available. Pre-build with `cd web && npm run build`. |
| `--isolated` | off | When launched from a named profile (`worker dashboard`), run a dedicated per-profile server instead of routing to the machine dashboard. |
| `--stop` | — | Stop the running `phi dashboard` / `phi serve` backend **of this Phi home** and exit (`-p <profile>` / `PHI_HOME` select which; backends of other profiles, other installs on the machine, and the shell you typed the command into are never touched — a backend whose owner cannot be read is left alone). SIGTERM, a 10s grace, then SIGKILL; a hosted Chat TUI that outlives its backend is stopped too (it would otherwise keep the deleted `state.db-wal` open and block the next start). Messaging-gateway bots started from the dashboard are not touched. |
| `--status` | — | List running `phi dashboard` processes and exit. |

### `phi dashboard register`

Register this install as a self-hosted dashboard with your Nous Portal account. Creates an OAuth client, writes `PHI_DASHBOARD_OAUTH_CLIENT_ID` into `~/.phi/.env`, and prints how to engage the login gate. Requires being logged in (`phi setup`).

| Option | Description |
|--------|-------------|
| `--name` | Human-readable label for the dashboard (default: auto-generated). |
| `--redirect-uri` | Public HTTPS OAuth redirect URI (e.g. `https://phi.example.com/auth/callback`). Omit for localhost-only use. |
| `--portal-url` | Override the Nous Portal base URL for registration (default: the portal you logged into). Also settable via `PHI_DASHBOARD_PORTAL_URL`. |

```bash
# Default — opens browser to http://127.0.0.1:9119
phi dashboard

# Custom port, no browser
phi dashboard --port 8080 --no-open

# From a profile alias — routes to the machine dashboard with the
# profile preselected in the sidebar switcher (attach if running)
worker dashboard
```

## `phi profile`

```bash
phi profile <subcommand>
```

Manage profiles — multiple isolated Phi instances, each with its own config, sessions, skills, and home directory.

| Subcommand | Description |
|------------|-------------|
| `list` | List all profiles. |
| `use <name>` | Set a sticky default profile. |
| `create <name> [--clone] [--clone-all] [--clone-from <source>] [--no-alias]` | Create a new profile. `--clone` copies config, `.env`, `SOUL.md`, skills, and the curated `MEMORY.md`/`USER.md` memory files from the active profile. `--clone-all` copies all state. `--clone-from` specifies a source profile and implies config clone unless paired with `--clone-all`. |
| `delete <name> [-y]` | Delete a profile. |
| `show <name>` | Show profile details (home directory, config, etc.). |
| `alias <name> [--remove] [--name NAME]` | Manage wrapper scripts for quick profile access. |
| `rename <old> <new>` | Rename a profile. |
| `export <name> [-o FILE]` | Export a profile to a `.tar.gz` archive (local backup). |
| `import <archive> [--name NAME]` | Import a profile from a `.tar.gz` archive (local restore). |
| `install <source> [--name N] [--alias] [--force] [-y]` | Install a profile distribution from a git URL or local directory. |
| `update <name> [--force-config] [-y]` | Re-pull a distribution; preserves user data (memories, sessions, auth). |
| `info <name>` | Show a profile's distribution manifest (version, requirements, source). |

Examples:

```bash
phi profile list
phi profile create work --clone
phi profile create work --clone --sync-imports   # also carry over the import-agent sync manifest
phi profile use work
phi profile alias work --name h-work
phi profile export work -o work-backup.tar.gz
phi profile import work-backup.tar.gz --name restored
phi profile install github.com/user/my-distro --alias
phi profile update work
phi -p work chat -q "Hello from work profile"
```

## `phi completion`

```bash
phi completion [bash|zsh|fish]
```

Print a shell completion script to stdout. Source the output in your shell profile for tab-completion of Phi commands, subcommands, and profile names.

Examples:

```bash
# Bash
phi completion bash >> ~/.bashrc

# Zsh
phi completion zsh >> ~/.zshrc

# Fish
phi completion fish > ~/.config/fish/completions/phi.fish
```

## `phi pm`

Manage pinned tools, Python dependency environments, and their diagnostics.
This command does not update the Phi application itself.

```bash
phi pm --help
phi pm doctor
phi pm status
phi pm repair
phi pm install
phi pm install chromium
```

For source development, run the setup script once, then activate the installed
environment with `source ./activate` or PowerShell `. .\activate.ps1`.
Use `deactivate` to restore the previous shell environment. See the
[developer workflow](./package-management.md#developer-workflow) for preparation,
daily commands, dependency refresh, and test environments.

See [Package management](./package-management.md) for every subcommand,
source-versus-bundle behavior, lazy-install policy, and maintainer commands.

## `phi update`

```bash
phi update [--gateway] [--check] [--plan] [--no-backup] [--backup] [--yes]
```

Updates an admitted source checkout and prepares dependencies through PM.
Use `--check` to compare with its configured source target without applying
the update. Desktop bundles, Docker, Nix, and Termux packages retain their
external update owner. See [Updating & Uninstalling](../getting-started/updating.md).

`phi update` follows this installation's update channel. A source checkout of the official repository defaults to `stable`, the latest published `vX.Y.Z` GitHub release at its exact commit; forks and mirrors default to `main`. To follow every commit on `main` instead, run `phi update --set-channel main`; `phi update --set-channel stable` switches back. On the `main` channel, a checkout on another branch may be switched to the update branch before pulling. Commit branch work before updating when you want to keep it outside the update autostash flow.

| Option | Description |
|--------|-------------|
| `--install-id` | Print this installation's identity and path, then exit. |
| `--set-channel CHANNEL` | Persist the update channel for this source installation without applying an update: `stable` (published releases) or `main` (every commit). Bundled applications have a fixed build channel and refuse channel changes. |
| `--channel CHANNEL` | Select a source channel for this invocation only (`stable` or `main`); nothing is saved. |
| `--branch NAME` | Select a source branch for this invocation; takes precedence over source channel selection. |
| `--gateway` | Internal mode used by the messaging `/update` command. Uses file-based IPC for prompts and progress streaming instead of reading from terminal stdin. Not a gateway restart flag. |
| `--check` | Check whether an update is available without pulling, installing dependencies, or restarting anything. |
| `--plan` | Print the update plan and exit without changing anything: install kind (git/Docker/Nix/apt), every running Phi service across all profiles with its supervisor and running code version, and how each will be restarted. On image- or package-managed installs, reports the correct external update command instead. Read-only. |
| `--no-backup` | Skip all pre-update backups for this run (both the quick state snapshot and the full zip), regardless of `updates.pre_update_backup`. |
| `--backup` | Force a **full** pre-update backup for this run: the quick state snapshot plus a complete zip of `PHI_HOME` (config, auth, sessions, skills, pairing data). The default mode is `quick` — a lightweight state snapshot only. Set the permanent mode via `updates.pre_update_backup: quick | full | off` in `config.yaml`. |
| `--yes`, `-y` | Assume yes for interactive prompts such as config migration and stash restore. API-key entry is skipped; run `phi config migrate` separately for those. |

Additional behavior:

- **Gateway restart.** After a successful update, Phi attempts to restart all running gateway profiles of the home being updated (its root and every `profiles/<name>` under it) automatically so they pick up the new code. Gateways and `phi-gateway*` services that belong to a different `PHI_HOME` on the same machine — another install, or a scratch home running `phi update` — are named in the output and left alone. Use `phi gateway restart` when you want to restart a gateway without applying an update.
- **Restart-phase recovery.** If the in-process restart phase aborts while importing the freshly pulled tree, supervised gateway profiles are retried through a clean Python process. Only restarts independently confirmed by systemd (`systemctl --user is-active`) are reported as verified; a relaunch that merely exited 0 is recorded as `relaunch_attempted` and the restart stays owed (a `gateway_restart` follow-up; the update itself still exits 0 because the code is in place). Manual gateways and serve/dashboard runtimes are never killed without a relaunch authority; they are recorded as skipped with a reason and remain in the incomplete-update report with the exact restart command.
- **Update receipts + fleet version check.** Every run writes a machine-readable receipt to `~/.phi/logs/update_receipts/` in the root Phi home, even from a sticky profile (pre-update fleet plan, steps, skips with reasons, restart outcome, follow-ups; `latest.json` points at the newest and reads `running` while an update is in progress). After the restart phase the updater verifies each live gateway's running code against the updated checkout and prints a per-profile version matrix. A gateway still on pre-update code does not fail the update once the new code is in place: the update prints a `⚠` line with the exact restart command, exits 0, records a `gateway_restart` follow-up, and keeps the restart owed — every CLI start warns about it and the next `phi update` retries it.
- **Local source changes.** For git installs, dirty tracked files and untracked files are auto-stashed before branch checkout or pull (`git stash push --include-untracked`). Interactive terminal updates ask before restoring the stash. Non-interactive updates restore it by default; set `updates.non_interactive_local_changes: discard` only on managed installs where local source edits should be thrown away after a successful pull. If stash restore conflicts or the pull fails, the stash is left in place for manual recovery.
- **npm lockfile churn.** Before stashing or switching branches, Phi makes a best-effort cleanup of tracked `package-lock.json` diffs produced by npm install/build steps. Commit or manually stash intentional lockfile edits before running `phi update`.
- **Pairing data snapshot.** Even when `--backup` is off, `phi update` takes a lightweight snapshot of `~/.phi/pairing/` and the Feishu comment rules before `git pull`. You can roll it back with `phi backup restore --state pre-update` if a pull rewrites a file you were editing.
- **Legacy `phi.service` warning.** If Phi detects a pre-rename `phi.service` systemd unit (instead of the current `phi-gateway.service`), it prints a one-time migration hint so you can avoid flap-loop issues.
- **Exit codes.** `0` on success, `1` on pull/install/post-install errors, `2` on unexpected working-tree changes that block `git pull`.

## Maintenance commands

| Command | Description |
|---------|-------------|
| `phi --version` | Print version information. |
| `phi update` | Pull latest changes and reinstall dependencies. |

| `phi uninstall [--full] [--gui] [--data] [--dry-run] [--yes]` | Remove owned source-install files. `--gui` selects source-built desktop removal; `--full` also removes data. `--data` removes user data without deleting package-owned code. Sealed installs use their package owner for application removal. `--dry-run` previews the scope; `--yes` skips confirmation. |

## See also

- [Slash Commands Reference](./slash-commands.md)
- [CLI Interface](../user-guide/cli.md)
- [Sessions](../user-guide/sessions.md)
- [Skills System](../user-guide/features/skills.md)
- [Skins & Themes](../user-guide/features/skins.md)
