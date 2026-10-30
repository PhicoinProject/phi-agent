# Optional Skills

Official optional skills bundled with Phi that are **not activated by default**.

These skills ship with the phi-agent repository but are not copied to
`~/.phi/skills/` during setup. They are discoverable via the Skills Hub:

```bash
phi skills browse               # browse all skills, official shown first
phi skills browse --source official  # browse only official optional skills
phi skills search <query>       # finds optional skills labeled "official"
phi skills install <identifier> # copies to ~/.phi/skills/ and activates
```

## Why optional?

Some skills are useful but not broadly needed by every user:

- **Niche integrations** — specific paid services, specialized tools
- **Experimental features** — promising but not yet proven
- **Heavyweight dependencies** — require significant setup (API keys, installs)

By keeping them optional, we keep the default skill set lean while still
providing curated, tested, official skills for users who want them.
