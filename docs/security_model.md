# Security Model

- Cover-letter generation uses Google Gemini. The candidate profile and job
  details are sent to Gemini by default from the daily workflow and MCP tool;
  neither path asks for per-generation confirmation. Use
  `job-agent daily --no-remote-letters` to disable daily cloud letter generation.
- The interactive chat model remains local Ollama by default. Remote chat
  providers require the separate `JOB_AGENT_ALLOW_REMOTE_AGENT_DATA=true`
  opt-in and may receive chat and MCP tool-result data.
- Generated cover letters are drafts. Application review and calendar actions
  retain their human confirmation steps, and the system does not submit
  applications.
