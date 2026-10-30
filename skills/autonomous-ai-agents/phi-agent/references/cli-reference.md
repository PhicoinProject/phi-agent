# Phi CLI Reference

Live sources when anything looks stale: `phi --help`, `phi <command> --help`,
https://github.com/PhicoinProject/phi-agent/blob/main/website/docs/reference/cli-commands

### Global Flags

```
phi [flags] [command]        (no subcommand = interactive chat)

  --version, -V             Show version
  -z, --oneshot PROMPT      One-shot: print ONLY the final response (for scripts/pipes)
  -m MODEL  --provider P    Model/provider override for this invocation
  -t, --toolsets LIST       Comma-separated toolsets for this invocation
  --resume, -r SESSION      Resume session by ID or title
  --continue, -c [NAME]     Resume by name, or most recent session
  --worktree, -w            Isolated git worktree mode (parallel agents)
  --skills, -s SKILL        Preload skills (comma-separate or repeat)
  --profile, -p NAME        Use a named profile
  --yolo                    Skip dangerous command approval
  --tui / --cli             Force the Ink TUI / classic REPL
  --ignore-rules            Skip AGENTS.md/SOUL.md/memory/skill injection
  --safe-mode               Disable ALL customizations (troubleshooting)
  --pass-session-id         Include session ID in system prompt
```

### Chat

```
phi chat [flags]
  -q, --query TEXT          Single query, non-interactive
  --image PATH              Attach a local image to a single query
  -Q, --quiet               Suppress banner, spinner, tool previews
  --checkpoints             Enable filesystem checkpoints (/rollback)
  --max-turns N             Cap tool-calling iterations
  --source TAG              Session source tag (default: cli)
```
(plus the global flags above)

### Configuration

```
phi setup [section]      Wizard (model|tts|terminal|gateway|tools|agent)
phi model                Interactive model/provider picker
phi fallback [add|remove|list]  Fallback provider chain
phi config [show|edit|get|set|unset|path|env-path|check|migrate]
phi login / logout       OAuth sign-in / clear stored auth
phi doctor [--fix]       Check dependencies and config
phi status [--full]      Component summary (--full: every section)
```

### Tools & Skills

```
phi tools [list|enable NAME|disable NAME]   Per-platform toolsets (curses UI with no args)

phi skills list|browse|search QUERY|inspect ID
phi skills install ID    Hub identifier OR a direct https://…/SKILL.md URL
phi skills config        Enable/disable skills per platform
phi skills check|update|uninstall|publish PATH
phi skills tap add REPO  Add a GitHub repo as a skill source
phi bundles              Skill bundles (one /<name> alias loads several skills)
```

### MCP Servers

```
phi mcp add NAME (--url or --command) | remove | list | test NAME
phi mcp catalog | install NAME     Curated catalog install
phi mcp configure NAME             Toggle tool selection
phi mcp-serve                      Run Phi as an MCP server (mcp-serve plugin)
```
Details (transport, tool discovery, catalog): `references/native-mcp.md`.

### Gateway (Messaging Platforms)

```
phi gateway run|install|start|stop|restart|status|setup
```

20+ platforms: Telegram, Discord, Slack, WhatsApp (Baileys + Business Cloud API), iMessage (Photon — `phi photon setup`), Signal, Email, SMS, Matrix, Mattermost, Teams, LINE, SimpleX, ntfy, Google Chat, Home Assistant, DingTalk, Feishu, WeCom, Weixin, API Server, Webhooks. Open WebUI connects via the API Server adapter. Most adapters ship under `plugins/platforms/`.
Docs: https://github.com/PhicoinProject/phi-agent/blob/main/website/docs/user-guide/messaging/

### Sessions

```
phi sessions list|browse|rename ID TITLE|delete ID|export OUT|prune|stats
```

### Cron / Webhooks

```
phi cron list|create SCHED|edit ID|pause|resume|run ID|remove|status
    Schedules: '30m', 'every 2h', '0 9 * * *', ISO timestamp
phi webhook subscribe NAME|list|remove NAME|test NAME
```
Webhook payloads/routes: `references/webhooks.md`.

### Profiles

```
phi profile list|create NAME (--clone|--clone-all|--clone-from)|use|show|delete
phi profile rename A B | alias NAME | export NAME | import FILE
phi profile migrate-identity A B   Retry a completed rename's session/routing identity migration
```

### Credentials & Pools

```
phi auth                 Interactive credential manager
phi auth add [PROVIDER]  Add OAuth or API-key credential (nous, openai-codex, qwen-oauth, …)
phi auth list|remove P IDX|reset PROVIDER|status
```
Multiple credentials per provider form a pool that rotates automatically and skips exhausted keys.

### Other

```
phi desktop / gui        Native desktop app
phi dashboard            Web admin panel + embedded chat (--stop / --status)
phi proxy                OpenAI-compatible local proxy backed by an OAuth provider
phi portal               Quick setup / sign in via Nous Portal
phi kanban <verb>        Multi-agent work-queue board
phi project              Named multi-folder workspaces
phi skin list|use|set    Switch/tweak skins (see references/themes.md)
phi pets <verb>          Pet mascots (see references/petdex.md)
phi memory setup|status|off|reset   Memory provider
phi secrets bitwarden|onepassword   External secret stores
phi moa                  Mixture-of-Agents slots
phi hooks / security / backup / import / checkpoints / console
phi logs [-f] [errors]   View agent/error logs
phi send                 One-off message through a gateway platform
phi pairing / plugins / insights / journey / computer-use
phi acp                  ACP server (IDE integration)
phi completion bash|zsh|fish
phi update / uninstall
```

Plugin- and provider-supplied subcommands (e.g. `phi photon setup`) only appear once their plugin is installed/active. Importing from OpenClaw, Claude Code, Codex CLI or Cursor (`phi import-agent <agent>`, plus the older `phi claw migrate|cleanup`) comes from the `agent-importers` plugin; a fresh `phi setup` that finds one of those agents offers to install it.

### Where to Find Things

| Looking for... | Location |
|---|---|
| Config options | `phi config edit` · [Configuration docs](https://github.com/PhicoinProject/phi-agent/blob/main/website/docs/user-guide/configuration) |
| Tools / toolsets | `phi tools list` · [Tools reference](https://github.com/PhicoinProject/phi-agent/blob/main/website/docs/reference/tools-reference) |
| Skills catalog | `phi skills browse` · [Skills catalog](https://github.com/PhicoinProject/phi-agent/blob/main/website/docs/reference/skills-catalog) |
| Provider setup | `phi model` · [Providers guide](https://github.com/PhicoinProject/phi-agent/blob/main/website/docs/integrations/providers) |
| Env variables | `phi config env-path` · [Env vars reference](https://github.com/PhicoinProject/phi-agent/blob/main/website/docs/reference/environment-variables) |
| Gateway logs | `~/.phi/logs/gateway.log` (or `phi logs`) |
| Sessions | `phi sessions browse` (reads state.db) |
