# User Deployment and Onboarding Plan

## Goal

Prepare the current local job-search assistant for distribution to individual
Windows users. The first release should include a launchable `.exe` and
chat-guided setup, without changing the existing human-controlled application
review, email, or calendar behavior.

The initial product is console-first: launching the app opens its interactive
chat in a terminal. A graphical interface is a separate future decision, not a
requirement for the first distributable.

## User-facing setup routines

Provide three explicit entry points in chat: **Full setup**, **Email and
calendar setup**, and **Add job websites**. Show the choices on first launch
and make them available later from a setup/help command. Each routine should
explain its purpose, show progress, confirm what will be saved, and allow the
user to cancel without leaving a partially applied configuration.

At every step, offer **Explain this step**. The explanation answers both:

- **How:** what the app will ask for, what the user needs to provide, and what
  action the app will take.
- **Why:** which workflow benefits and what data or permission is involved.

Optional steps offer **Skip for now** and explain which features will remain
unavailable. Required values are validated before advancing. Never treat
skipping, cancellation, or a failed external authorization as successful
setup.

### Routine A: Full setup for a new job seeker

1. **Introduce the workflow and privacy boundaries.** Explain local profile and
   job storage, the read-only Gmail integration, calendar event confirmation,
   optional remote cover-letter generation, and that applications are never
   submitted automatically. Offer step-by-step setup or exit.
2. **Ask for the candidate's name.** Explain it is used to personalize
   application drafts and form-prefill. Require a non-empty value; allow edit
   or cancel.
3. **Ask for the candidate's email address.** Validate its basic format and
   explain it is used to prefill application forms and optionally connect to
   the user's Google account. Do not infer or silently select a Google account.
4. **Configure email and calendar (optional).** Offer the dedicated
   email/calendar routine below. Describe the separate Gmail read-only and
   Calendar event scopes before consent. Allow Gmail, Calendar, both, or neither
   where the existing integrations support independent setup. The user must
   complete Google's consent flow; the app must not collect account passwords.
5. **Configure job websites.** Ask for listing-page URLs one at a time, explain
   how URLs are used for job discovery, and validate HTTPS, hostname, and
   adapter support before saving. Allow adding multiple URLs, testing/previewing
   each URL, and skipping website setup.
6. **Review and save.** Summarize name, email, enabled integrations, granted
   permissions, and websites. Clearly distinguish configured from skipped or
   failed items. Ask for confirmation before writing the final configuration.
   Offer to change a value or cancel.
7. **Finish with a useful next action.** Confirm setup and offer to search jobs,
   view the daily workflow, or revisit setup. Do not start a search, Gmail sync,
   or calendar write without the user's choice.

### Routine B: Add or update email and calendar only

1. Explain this routine does not change candidate details or job websites.
2. Ask which integration to configure: Gmail, Calendar, both, or return.
3. For each selected service, explain the exact scope and data/action:
   - Gmail uses `gmail.readonly` to read recent messages for application
     tracking; it does not send mail, mark messages read, or alter labels.
   - Calendar uses `calendar.events` to create a private interview event only
     after a separate, explicit confirmation. Events have no attendees and do
     not send invitations.
4. Explain the Google OAuth client-file prerequisite in plain language and
   guide the user to select/provide the client configuration. Do not ask for
   client secrets or tokens in chat; store credential files locally.
5. Start the selected Google consent flow. Report success, cancellation, or
   errors individually. Do not report the routine as complete for a failed or
   cancelled integration; allow retry or skip that service.
6. Test the authorized service with the least-invasive available check and
   summarize enabled integrations. Never sync email or create a calendar event
   merely as a setup test.

### Routine C: Add job websites only

1. Explain that this routine changes only the list of job listing URLs.
2. Accept one or more HTTPS listing URLs. For each, validate syntax, supported
   domain/adapter, and that it is a listing page rather than an arbitrary
   destination. Reject unsupported URLs with an actionable explanation; do not
   browse or scrape an unrecognized host automatically.
3. Show the normalized URL and detected website. Let the user remove or edit
   entries, add another, or skip.
4. Preview/test only after user confirmation; use existing adapter safety
   limits and do not submit forms or bypass anti-bot controls.
5. Summarize current and newly added URLs, then ask before saving. Preserve
   previously configured URLs unless the user explicitly removes them.

## Application and configuration design

- Keep first release console-based, using the existing `job-agent chat` host
  and MCP tool boundaries. Add a dedicated onboarding workflow rather than
  relying on the language model to remember required setup steps.
- Persist a versioned per-user configuration outside the installation
  directory. Separate editable preferences (name, email, websites) from OAuth
  client files, access tokens, logs, and the jobs database. Do not store user
  data in a directory that an update or uninstall replaces.
- Reuse `data/daily_urls.txt` or migrate its entries deliberately; do not
  silently overwrite existing URLs. Resolve all data paths from the user's
  writable data directory, not the executable's install directory or the
  current working directory.
- Keep secrets out of configuration summaries, logs, chat transcripts, crash
  reports, and support bundles. Restrict local credential-file permissions
  where Windows permits and document how to revoke Google access and remove
  local data.
- Keep Gmail and Calendar scopes separate, request only scopes for integrations
  selected by the user, and make remote data processing (including Gemini
  cover-letter generation or a remote chat provider) an explicit, informed
  opt-in.
- Support restart and resume after interrupted OAuth or onboarding. Saving one
  successfully configured service must not require reauthorizing another.

## Windows executable and distribution

1. **Choose and prove the packaging approach.** Prototype a Windows x64 frozen
   build from the locked dependencies. Compare a PyInstaller one-folder
   distribution/installer with a single-file executable; prefer the approach
   that reliably launches the bundled Python runtime, Playwright Chromium, and
   child MCP processes. Do not promise a one-file portable `.exe` until those
   runtime and browser assets work on a clean machine.
2. **Define the user entry point.** Ship a signed or clearly attributable
   `job-agent.exe` (or installer-created shortcut) that opens the chat in a
   visible console, runs first-launch onboarding when needed, and returns
   actionable errors. Also expose a direct way to relaunch onboarding and
   repair/update setup.
3. **Bundle runtime assets intentionally.** Include Python dependencies, MCP
   server entry points, migrations/default files, and the Playwright browser
   runtime or a documented first-run browser installation. Verify browser
   licensing/redistribution and size before choosing to bundle Chromium.
4. **Keep user data out of the bundle.** Store the database, candidate
   configuration, OAuth client file/tokens, logs, generated letters, and
   browser state under a per-user writable application-data directory.
   Upgrades must preserve data; uninstall must state whether user data is
   retained and provide a separate explicit removal option.
5. **Build reproducibly.** Pin the build environment and packaging tool,
   generate versioned artifacts, record checksums, and produce a clean install
   test on a Windows machine/VM that has no Python, `uv`, or repository
   checkout. Document upgrades, uninstall, supported Windows versions, and
   troubleshooting.
6. **Release safely.** Start with a signed, versioned beta installer or
   downloadable package, publish release notes and privacy/permission
   explanations, and provide a rollback path. Do not ask users to disable
   antivirus or Windows security controls to install the app.

## Delivery phases and acceptance criteria

### Phase 1 — Product and data-path readiness

- Inventory every read/write path, environment variable, subprocess, browser
  asset, OAuth file, and generated artifact used by chat and daily workflows.
- Specify a per-user data root, configuration schema/versioning, migration
  behavior, reset/export behavior, and error recovery.
- Decide the initial distribution format, supported Windows versions, update
  strategy, and whether Chromium is bundled or installed on first use.

**Exit:** a documented file/data lifecycle and a clean-machine packaging
prototype can launch the existing chat without relying on repository-relative
paths.

### Phase 2 — Deterministic onboarding and configuration

- Implement the three routines above as explicit, testable application flows.
- Reuse existing credential handling, adapter registry, and consent boundaries;
  add no arbitrary shell, filesystem, or browser access to the chat model.
- Add safe validation, resumability, cancellation, explanations, optional skips,
  configuration review, and explicit save confirmation.

**Exit:** every routine can be completed, skipped, cancelled, resumed, or
retried, with no silent permission grants, lost existing website URLs, or
success-shaped failure responses.

### Phase 3 — Executable packaging

- Package the console host and subprocess MCP servers; confirm process cleanup,
  resource lookup, logs, and error reporting in frozen mode.
- Verify Playwright/Chromium, SQLite initialization/migrations, OAuth browser
  callbacks, and all writable paths from a non-admin account.
- Produce a versioned Windows artifact and test install, upgrade, rollback, and
  uninstall behavior.

**Exit:** a user on a clean supported Windows system can install and launch
`job-agent.exe`, complete setup, close/reopen the app, and retain settings and
data without Python or repository tooling.

### Phase 4 — User acceptance and release

- Test onboarding with fresh, partially configured, and existing-user
  profiles, including cancelled OAuth, revoked tokens, invalid URLs, network
  failures, and interrupted setup.
- Verify the established safeguards: no automatic application submission,
  no Gmail mutation, no unconfirmed calendar writes, and no unexpected remote
  transfer.
- Publish setup/help instructions, privacy and permission details, supported
  system requirements, known limitations, and a support/diagnostic process that
  excludes secrets and message contents.

**Exit:** release checklist, clean-machine acceptance results, and rollback plan
are reviewed before public distribution.

## Risks and decisions to resolve before implementation

- **Adapter support:** the adapter registry currently supports DEV.BG,
  Jobs.bg, and LinkedIn; accepting a URL must not imply that every board is
  supported. Define whether unsupported hosts are rejected or added in a later
  adapter-development flow.
- **Google OAuth distribution:** confirm the OAuth consent-screen configuration
  and verification requirements for external users, and decide how the OAuth
  client configuration is provisioned without embedding a private client secret
  in a publicly distributed executable.
- **Frozen subprocesses:** the chat host starts MCP servers as child processes.
  Packaging must prove that server launch, stdio transport, shutdown, and
  diagnostics work outside a source checkout.
- **Browser size and updates:** decide whether Chromium is bundled or installed
  on first use, and how browser updates remain compatible with Playwright.
- **AI provider and costs:** onboarding must accurately explain which data is
  processed locally and which is sent to Google Gemini or any opted-in remote
  chat endpoint. Decide whether remote letter generation remains disabled by
  default for a consumer release.
- **Release trust:** establish publisher identity, code-signing approach,
  artifact integrity checks, and a user-facing update channel before a broad
  release.
