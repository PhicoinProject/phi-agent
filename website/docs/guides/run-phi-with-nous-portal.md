---
sidebar_position: 1
title: "Run Phi Agent with Nous Portal"
description: "Start-to-finish walkthrough: subscribe, set up, switch models, enable gateway tools, and verify routing"
---

# Run Phi Agent with Nous Portal

This guide walks you through running Phi Agent on a [Nous Portal](https://portal.nousresearch.com) subscription end to end — from signing up to verifying that every tool routes correctly. If you just want the overview of what the Portal is and what's in the subscription, see the [Nous Portal integration page](../integrations/nous-portal.md). This page is the task script.

## Prerequisites

- Phi Agent installed ([Quickstart](../getting-started/quickstart.md))
- A web browser on the machine you're setting up (or SSH port forwarding — see [OAuth over SSH](./oauth-over-ssh.md))
- About 5 minutes

You do **not** need: an OpenAI key, an Anthropic key, a web search account, a FAL account, a Browser Use account, or any other per-vendor credential. That's the whole point.

## 1. Get a subscription

Open [portal.nousresearch.com/manage-subscription](https://portal.nousresearch.com/manage-subscription), sign up, and pick a plan.

Already subscribed? Skip to step 2.

## 2. Run the one-shot setup

```bash
phi setup --portal
```

This single command does five things:

1. Opens your browser to portal.nousresearch.com for OAuth login
2. Stores the refresh token at `~/.phi/auth.json`
3. Sets `model.provider: nous` in `~/.phi/config.yaml`
4. Picks a default agentic model (`anthropic/claude-sonnet-4.6` or similar)
5. Turns on the Tool Gateway for web search, image generation, TTS, and browser automation

When it finishes, you're back at your terminal ready to chat.

### What if I'm SSH'd into a server?

OAuth needs a browser, but the loopback callback runs on the machine where Phi is running. Two options:

```bash
# Option A: SSH port forwarding (preferred)
ssh -N -L 8642:127.0.0.1:8642 user@remote-host    # in a local terminal
phi setup --portal                              # on the remote, open the printed URL in your local browser

# Option B: device-code login (works from Cloud Shell, Codespaces, EC2 Instance Connect)
phi auth add nous --type oauth
# Then re-run `phi setup --portal` to wire the provider + gateway
```

See [OAuth over SSH / Remote Hosts](./oauth-over-ssh.md) for the full walkthrough including ProxyJump chains, mosh/tmux, and ControlMaster gotchas.

## 3. Verify it worked

```bash
phi portal info
```

You should see:

```
  Nous Portal
  ───────────
  Auth:    ✓ logged in
  Portal:  https://portal.nousresearch.com
  Model:   ✓ using Nous as inference provider

  Tool Gateway
  ────────────
  Web search & extract  via Nous Portal
  Image generation      via Nous Portal
  Text-to-speech        via Nous Portal
  Browser automation    via Nous Portal
```

If any line shows something other than "via Nous Portal" or the auth line says "not logged in", jump to [Troubleshooting](#troubleshooting) below.

## 4. Run your first conversation

```bash
phi chat
```

Try something that exercises both the model and the Tool Gateway:

```
Hey, search the web for "Phi Agent release notes" and summarize the top 3 hits.
```

You should see Phi call `web_search` (through the gateway) and respond with a summary. If the search runs and the response makes sense, you're done — the Portal is wired up end to end.

## 5. Pick the model you actually want

`phi setup --portal` lets you pick a model during setup, but the whole point of the subscription is access to the full catalog — switch any time with `/model` mid-session:

```bash
/model anthropic/claude-sonnet-4.6     # best general-purpose agentic
/model openai/gpt-5.4                  # strong reasoning + tool calling
/model google/gemini-2.5-pro           # huge context window
/model deepseek/deepseek-v3.2          # cost-effective coder
/model anthropic/claude-opus-4.6       # heavyweight for hard problems
```

Or pop the picker to browse:

```bash
/model
```

Pick a different default permanently:

```bash
# in your terminal, outside any session
phi config set model.default anthropic/claude-sonnet-4.6
```

## 6. (Optional) Customize Tool Gateway routing

The gateway is opt-in per tool, not all-or-nothing. If you already have a Browserbase account and want to keep using it while routing web search and image generation through Nous, that's supported:

```bash
phi tools
# → Web search       → "Nous Subscription"     (recommended)
# → Image generation → "Nous Subscription"     (recommended)
# → Browser          → "Browserbase"           (your existing key)
# → TTS              → "Nous Subscription"     (recommended)
```

These rows appear in `phi tools` even before you've logged into Nous Portal — if you pick "Nous Subscription" without an active session, Phi runs the Portal login inline (without changing your inference provider or your other tools).

Verify your mix with:

```bash
phi portal tools
```

You'll see per-tool routing — `via Nous Portal` for the ones routed through the subscription, and the partner name (`browserbase`, `firecrawl`, etc.) for the ones using your own keys.

## 7. (Optional) Enable voice mode

Because the Tool Gateway includes OpenAI TTS, [voice mode](../user-guide/features/voice-mode.md) works without a separate OpenAI key:

```bash
phi setup tts
# → pick "Nous Subscription" for TTS
# → pick a speech-to-text backend (local faster-whisper is free, no setup)
```

Then in any messaging-platform session (Telegram, Discord, Signal, etc.), send a voice message and Phi will transcribe it, respond, and reply with synthesized voice — all on your Portal subscription.

## 8. (Optional) Cron + always-on workflows

The Portal subscription works for [cron jobs](../user-guide/features/cron.md) and [batch processing](../user-guide/features/batch-processing.md) the same way it works for interactive chat — the OAuth refresh token is reused automatically. No additional setup; just schedule cron jobs and they'll bill against your subscription.

```bash
phi cron create "0 9 * * *" \
  "Search the web for top AI news and summarize the 5 most important stories" \
  --name "Daily AI news"
```

The cron job runs unattended, calls the model + web search + summarization all through your Portal subscription.

## Profiles and multi-user setups

If you use [Phi profiles](../user-guide/profiles.md) (e.g. a separate config per project), each profile is an independent credential island: a profile that has never signed in to the Portal fails closed instead of adopting another profile's session. Sign in once per profile with `phi -p <name> portal` — when a shared Portal session already exists on the machine it offers to import it without a browser round-trip, and from then on the shared token store keeps that profile's token current. See [Profile setup](../integrations/nous-portal.md#profile-setup).

For team setups where multiple humans share a machine, each human has their own Portal account → each home directory holds its own `~/.phi/auth.json` → no token sharing across users. This is the right boundary.

## Troubleshooting

### `phi portal info` shows "not logged in" after `phi setup --portal`

The OAuth flow didn't complete. Re-run it:

```bash
phi portal
```

If your browser doesn't open or the callback fails, you're likely on a remote/headless host — see [OAuth over SSH](./oauth-over-ssh.md) for the port-forwarding workarounds.

### "Model: currently openrouter" (or some other provider) instead of "using Nous as inference provider"

Your local config drifted. The OAuth worked but `model.provider` is still pointing at a different provider. Fix:

```bash
phi config set model.provider nous
```

Or interactively:

```bash
phi model
# pick Nous Portal
```

Re-verify with `phi portal info`.

### Tool Gateway tools showing partner names instead of "via Nous Portal"

Per-tool config is overriding the gateway. Run:

```bash
phi tools
# pick "Nous Subscription" for any tool you want gateway-routed
```

Some users intentionally mix — e.g. routing web through Nous but using their own Browserbase key for browser. If that's intentional, leave it alone. If not, this command fixes it.

### "Re-authentication required" mid-session

Your Portal refresh token was invalidated (password change, manual revoke, session expiry). The token is now quarantined locally so Phi doesn't replay it endlessly. Just log in again:

```bash
phi auth add nous
```

The quarantine clears automatically on successful re-login.

### Model I want isn't in the `/model` picker

The Portal catalog draws on OpenRouter's model list (300+) plus models served through proprietary or secondary providers. If a model is missing, try typing the OpenRouter-style slug directly:

```bash
/model anthropic/claude-opus-4.6
/model openai/o1-2025-12-17
```

If a model is genuinely unavailable, [open an issue](https://github.com/PhicoinProject/phi-agent/issues) — most gaps are routing config we can update.

### Billing not appearing on my Portal account

`phi portal info` will tell you whether you're actually routing through the Portal or some other provider. Common causes:

- `model.provider` set to `openrouter`/`anthropic`/etc. instead of `nous`
- An OAuth refresh failure that fell back to a different configured provider
- Multiple Phi profiles where you're using the wrong one (check `phi profile list`)

### Want to revoke and start clean

```bash
phi auth logout nous       # wipes the local refresh token
# Then re-run setup or remove the subscription from the Portal web UI
```

## What this gets you, in plain numbers

| Without Portal | With Portal |
|----------------|-------------|
| 1× OpenRouter / Anthropic / OpenAI key in `.env` | 1× OAuth refresh token, no `.env` keys |
| 1× web search key | Web routed through gateway |
| 1× FAL key for image gen | Image gen routed through gateway |
| 1× Browser Use / Browserbase key for browser | Browser routed through gateway |
| 1× OpenAI key for TTS / voice mode | TTS routed through gateway |
| 5 separate dashboards, top-ups, invoices | 1 subscription, 1 invoice |
| Cross-machine: replicate all 5 keys | Cross-machine: re-OAuth once |

That's the deal. If you're using more than two of those backends anyway, the subscription pays for itself.

## See also

- **[Nous Portal integration page](../integrations/nous-portal.md)** — Overview of what's in the subscription
- **[Tool Gateway](../user-guide/features/tool-gateway.md)** — Full details on every gateway-routed tool
- **[Subscription proxy](../user-guide/features/subscription-proxy.md)** — Use your Portal subscription from non-Phi tools
- **[Voice mode](../user-guide/features/voice-mode.md)** — Set up voice conversations on the Portal subscription
- **[OAuth over SSH](./oauth-over-ssh.md)** — Remote / headless login patterns
- **[Profiles](../user-guide/profiles.md)** — Share one Portal login across multiple Phi configurations
