# Architecture

## M6 agent host

`job_agent.agent_host` is the thin orchestration layer. Interactive mode
connects over stdio to the jobs database, workflow, and tracking MCP servers.
The host exposes a fixed tool allowlist and provides no shell or arbitrary-file
access. Job descriptions and email contents returned from tools are untrusted
data; the model prompt and the tool allowlist constrain their influence.

The default chat provider is local Ollama. An OpenAI-compatible provider is
optional and requires `JOB_AGENT_ALLOW_REMOTE_AGENT_DATA=true` for a remote
endpoint. In that case, conversation and tool-result content can leave the
machine. The daily task does not use this chat provider.

Daily mode runs the existing discovery/evaluation routine without review and
generates cover letters with Gemini by default. Candidate profile and job
details are sent to Gemini without a per-letter confirmation; use
`--no-remote-letters` to skip them. Each run also backfills missing letters for
previously recommended jobs without re-evaluating them. It then uses the
tracking MCP server to sync read-only email and print a local digest.
Application submission, email sending, and calendar writes are not part of
unattended preparation; MCP confirmation tools remain interactive.

`job-agent evaluate-regressions` re-evaluates stored jobs without persisting
decisions. Human `APPLIED`/`SKIPPED` decisions are measured separately from
legacy `NOT_RECOMMENDED` agent outcomes, which are consistency checks rather
than independent human labels.
