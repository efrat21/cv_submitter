# Chat Model Benchmark: Ollama and Colibri

**Test date:** 2026-11-25  
**Scope:** One local `job-agent chat` tool-call trial on one Windows laptop. These are practical trial results, not a general model benchmark.

## Summary

Ollama completed the test request in **159.1 seconds**. Colibri did not complete it: the first two attempts were manually stopped after five minutes, and a third attempt timed out after **1,819.3 seconds**. The Colibri endpoint started and exposed its OpenAI-compatible API, but the chat-agent request did not finish.

This laptop is not a good Colibri choice when the goal is faster chat-agent responses. The Colibri results are failures to complete, not token-throughput measurements or proof that Colibri is slower on other hardware.

## Test setup

- **Machine:** ASUS Vivobook X7600PC; about 16 GB system RAM; NVIDIA GeForce RTX 3050 Laptop GPU with 4 GB VRAM; Intel Iris Xe; 8 CPU cores reported by Colibri.
- **Chat app:** `uv run job-agent chat`, using the full jobs, workflow, and tracking MCP tool set.
- **Request:** “Use the db_stats tool to tell me how many jobs are in the tracker.”
- **Database:** A temporary empty database for each run. The user's jobs database was not used for these tool calls.
- **Ollama model:** `qwen2.5:7b`.
- **Colibri:** v2.2.0, Inkling-2-Mini UD-IQ2_XXS (about 9.1 GB download), served locally as `inkling-2-mini-colibri`.
- **Colibri provider settings:** `JOB_AGENT_AGENT_PROVIDER=openai-compatible`, `JOB_AGENT_AGENT_BASE_URL=http://127.0.0.1:8000/v1`, `JOB_AGENT_AGENT_MODEL=inkling-2-mini-colibri`.

The project already supports this provider in [agent_host.py](../src/job_agent/agent_host.py), so no application-code changes were needed.

## Results

| Runtime and settings | Wall time | Outcome |
|---|---:|---|
| Ollama `qwen2.5:7b`, default chat settings | 159.1 s | Success. The agent called `jobs_db__db_stats` and answered that the empty tracker had no jobs. |
| Colibri, CPU backend, 8192 context | Stopped at 300 s | No response. Colibri was reading the prompt when the client was cancelled. |
| Colibri, Vulkan, 8192 context | Stopped at 300 s | No response. The RTX 3050 initialized, but the request did not finish within the test window. |
| Colibri, Vulkan, 4096 context, 128-token server output cap | 1,819.3 s | Failed. The OpenAI client raised `APITimeoutError` (`httpx2.ReadTimeout`); Colibri's log said the client left while the engine was reading the prompt. No tool call completed. |

For the Ollama run, the agent trace recorded approximately **34.3 s** for the tool-call decision, **0.3 s** for the database tool, and **105.9 s** for the final response. The 159.1-second wall time also includes CLI and MCP startup.

## Interpretation and caveats

- Colibri's Vulkan build did initialize on the RTX 3050. At 4096 context, its startup log reported an expert cache of about **726 MiB** (256 experts). The model could not keep all experts in VRAM.
- During the Colibri trials, `qwen2.5:7b` was still reported by Ollama as loaded at about **5.4 GB**. Available system RAM varied from roughly **0.6 to 2.7 GB** during the trials. This is a material test limitation and likely contributed to memory pressure; the results do not isolate Colibri's best-case performance.
- The final Colibri attempt used a lower context and a 128-token cap, but still did not complete. The cap was a test-only server setting; the application's OpenAI client timeout/retry settings were unchanged.
- The runs used the same user request and an isolated database, but this was not a controlled apples-to-apples throughput test: only Ollama completed, and the Colibri runs had different server settings and memory pressure.
- Candidate and job data were not sent to a remote model. The Colibri server was stopped after testing; the model files remain installed locally.

## Recommendation

Keep Ollama as the chat-agent runtime on this laptop. Colibri's OpenAI-compatible API is connectable, but this model and hardware did not deliver a usable chat-agent response in the trial. A smaller already-installed Ollama model is a more promising next latency experiment.
