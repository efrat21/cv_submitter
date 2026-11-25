# Roadmap

## M6 - Agent host, scheduling, evaluation, and hardening

- Interactive `job-agent chat` connects to the jobs DB, workflow, and tracking
  MCP servers using a fixed tool allowlist.
- Local Ollama is the default chat model. A remote OpenAI-compatible endpoint
  requires explicit environment opt-in.
- `job-agent daily` runs job preparation without review or remote cover letters
  by default, then syncs read-only email and prints the local digest. Windows
  Task Scheduler uses this mode.
- `job-agent evaluate-regressions` measures model decisions against human
  history without modifying stored decisions; legacy agent rejections are
  reported separately.
- Application review and calendar creation continue to require MCP elicitation
  confirmation. Cover-letter generation in chat asks before sending data to
  Gemini.
