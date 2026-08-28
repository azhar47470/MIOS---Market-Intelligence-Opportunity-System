# Configuration

The platform uses checked-in JSON configuration for provider endpoints and environment
variables for secrets.

Do not commit real API keys, webhook URLs, tokens, passwords, or generated `.env` files.

Required environment variables:

- `TWELVE_DATA_API_KEY`
- `FRED_API_KEY`
- `NEWSAPI_KEY`
- `GROQ_API_KEY`
- `GEMINI_API_KEY`
- `DISCORD_WEBHOOK_URL`
- `FINNHUB_API_KEY` (news feed only)

Provider endpoints and polling intervals are configured in `config/platform.json`.
Discord notification formatting and alert rules are configured in
`config/notifications.discord.json`.

The LLM fallback chain lives under `ai_reasoning.providers` in `config/platform.json`: an
ordered list of `{provider, enabled, models}` entries. List order is try-order across
providers; `models` is try-order within a provider (Gemini currently lists several model
variants; Groq lists one). A provider can be disabled without deleting it by setting
`"enabled": false`. There is no separate provider-specific config format — this extends the
same checked-in JSON convention as everything else, not a parallel YAML file.

Version 1 remains a market intelligence decision-support platform. Configuration must not
introduce trade execution, broker integration, portfolio tracking, or multi-user behavior.

Run commands are documented in `README.md`.
