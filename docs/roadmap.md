# Roadmap

## User deployment and onboarding

- See [User Deployment and Onboarding Plan](deployment_and_onboarding_plan.md)
  for the Windows `.exe` release plan and the three guided setup routines.

## M6 - Agent host, scheduling, evaluation, and hardening

- Interactive `job-agent chat` connects to the jobs DB, workflow, and tracking
  MCP servers using a fixed tool allowlist.
- Local Ollama is the default chat model. A remote OpenAI-compatible endpoint
  requires explicit environment opt-in.
- `job-agent daily` runs job preparation without review and generates
  cover letters with Gemini by default, then syncs read-only email and prints
  the local digest. Candidate/job data is sent to Gemini without per-letter
  confirmation; `--no-remote-letters` disables this. Windows Task Scheduler
  uses this mode.
- `job-agent evaluate-regressions` measures model decisions against human
  history without modifying stored decisions; legacy agent rejections are
  reported separately.
- Application review and calendar creation continue to require MCP elicitation
  confirmation. Cover-letter generation in chat sends candidate/job data to
  Gemini without per-generation confirmation.
