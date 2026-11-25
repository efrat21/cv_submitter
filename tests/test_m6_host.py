from __future__ import annotations

import asyncio
import json
import subprocess
import sys
import warnings
from types import SimpleNamespace

import pytest

from job_agent import agent_host
from job_agent.agent_host import (
    MCPToolBridge,
    ModelReply,
    OpenAICompatibleProvider,
    ToolCall,
    chat_turn,
)
from job_agent.database import JobDatabase
from job_agent.evaluation_harness import run_regression_evaluation


PROFILE = {"name": "Test", "skills": {"Python": ["Built Python services"]}}
PREFERENCES = {"target_roles": ["Engineer"], "work_models": ["Remote"]}


class FakeProvider:
    def __init__(self, replies):
        self.replies = iter(replies)
        self.tool_results = []

    def complete(self, messages, tools):
        assert tools
        return next(self.replies)

    def append_tool_turn(self, messages, reply, results):
        self.tool_results.extend(results)
        messages.extend(
            {"role": "tool", "content": result} for result in results
        )


class FakeBridge:
    def __init__(self, calls=None):
        self.bindings = {"jobs_db__db_stats": ("jobs_db", "db_stats", {})}
        self.calls = []
        self.tool_calls = calls or []

    def model_tools(self):
        return [{"type": "function"}]

    async def call(self, name, arguments):
        self.calls.append((name, arguments))
        return '{"total_jobs": 3}'


def test_chat_uses_only_tool_bridge_and_retains_conversation_once() -> None:
    bridge = FakeBridge()
    provider = FakeProvider(
        [
            ModelReply(
                "",
                [ToolCall("jobs_db__db_stats", {}, "call-1")],
                {},
            ),
            ModelReply("There are 3 jobs.", [], {}),
        ]
    )
    history = [{"role": "user", "content": "previous"}]

    answer = asyncio.run(
        chat_turn(
            "How many jobs?",
            history=history,
            provider=provider,
            bridge=bridge,
        )
    )

    assert answer == "There are 3 jobs."
    assert bridge.calls == [("jobs_db__db_stats", {})]
    assert provider.tool_results == ['{"total_jobs": 3}']
    assert [message["role"] for message in history] == [
        "user",
        "user",
        "tool",
        "assistant",
    ]


def test_mcp_bridge_rejects_non_allowlisted_tool_and_audits_success(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bridge = MCPToolBridge(["jobs_db", "workflow", "tracking"])
    calls = []

    class Session:
        async def call_tool(self, name, *, arguments):
            calls.append((name, arguments))
            return SimpleNamespace(
                structuredContent={"count": 1},
                content=[],
                isError=False,
            )

    audited = []
    bridge.sessions["jobs_db"] = Session()
    bridge.bindings["jobs_db__db_stats"] = ("jobs_db", "db_stats", {})
    monkeypatch.setattr(agent_host, "_audit_tool_call", lambda *args: audited.append(args))

    async def run():
        with pytest.raises(PermissionError):
            await bridge.call("jobs_db__shell", {})
        return await bridge.call("jobs_db__db_stats", {})

    result = asyncio.run(run())
    assert json.loads(result) == {"count": 1}
    assert calls == [("db_stats", {})]
    assert audited == [
        ("jobs_db__shell", "denied"),
        ("jobs_db__db_stats", "success"),
    ]


def test_cover_letter_mcp_tool_requires_consent_before_provider_use(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from job_agent.mcp_servers import host

    db = JobDatabase(tmp_path / "jobs.db")
    monkeypatch.setattr(host, "_open_db", lambda: JobDatabase(db.path))
    monkeypatch.setattr(
        host,
        "build_review_packet",
        lambda job_url, database: {
            "job": {"title": "Engineer", "company": "Example"},
        },
    )
    provider_calls = []
    monkeypatch.setattr(
        host,
        "generate_letter",
        lambda *args, **kwargs: provider_calls.append((args, kwargs)),
    )

    class CancelledContext:
        async def elicit(self, message, schema):
            assert "sends the candidate profile and job details" in message
            return SimpleNamespace(action="cancel", data=None)

    try:
        result = asyncio.run(
            host.generate_cover_letter(
                "https://jobs.example/1", CancelledContext()
            )
        )
        assert result["generated"] is False
        assert result["external_data_transfer"] is False
        assert provider_calls == []
        assert db.connection.execute(
            "SELECT approved FROM audit_log "
            "WHERE event_type = 'cover_letter.external_transfer_declined'"
        ).fetchone() == (0,)
    finally:
        db.close()


def test_chat_trace_keeps_content_out_of_local_run_log(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    trace_path = tmp_path / "trace.jsonl"
    monkeypatch.setenv("JOB_AGENT_TRACE_PATH", str(trace_path))
    bridge = FakeBridge()
    provider = FakeProvider([ModelReply("Done.", [], {})])

    answer = asyncio.run(
        chat_turn(
            "Search for role for person@example.test",
            history=[],
            provider=provider,
            bridge=bridge,
            trace_id="run-1",
        )
    )

    trace = trace_path.read_text(encoding="utf-8")
    assert answer == "Done."
    assert "person@example.test" not in trace
    assert '"event": "user.input"' in trace
    assert '"event": "model.completed"' in trace
    assert '"sha256"' in trace


def test_openai_compatible_remote_requires_explicit_data_opt_in(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("JOB_AGENT_ALLOW_REMOTE_AGENT_DATA", raising=False)
    with pytest.raises(PermissionError, match="Remote model use is disabled"):
        OpenAICompatibleProvider(
            base_url="https://models.example/v1", client=object()
        )

    monkeypatch.setenv("JOB_AGENT_ALLOW_REMOTE_AGENT_DATA", "true")
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        provider = OpenAICompatibleProvider(
            base_url="https://models.example/v1", client=object()
        )
    assert provider.model


def test_remote_ollama_endpoint_requires_explicit_data_opt_in(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("JOB_AGENT_ALLOW_REMOTE_AGENT_DATA", raising=False)
    with pytest.raises(PermissionError, match="Remote model use is disabled"):
        agent_host.OllamaProvider(host="https://models.example")


def test_daily_mode_prepares_without_review_then_syncs_and_digests(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    prepared = []

    class Bridge:
        def __init__(self, servers):
            assert servers == ["tracking"]

        def connect(self):
            from contextlib import asynccontextmanager

            @asynccontextmanager
            async def context():
                yield self

            return context()

        async def call(self, name, arguments):
            if name == "tracking__sync_application_emails":
                return '{"synced": 2}'
            assert name == "tracking__get_daily_application_digest"
            return "Daily digest"

    monkeypatch.setattr(
        agent_host,
        "_run_job_preparation",
        lambda name, email, **kwargs: prepared.append((name, email, kwargs)),
    )
    monkeypatch.setattr(agent_host, "MCPToolBridge", Bridge)

    result = asyncio.run(agent_host.daily_mode(name="Candidate", email="a@example.test"))
    assert prepared == [("Candidate", "a@example.test", {"allow_remote_letters": False})]
    assert result == {"email_sync": '{"synced": 2}', "digest": "Daily digest"}


def test_daily_job_prep_never_sends_letters_without_explicit_opt_in(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    commands = []
    monkeypatch.setattr(
        agent_host.subprocess,
        "run",
        lambda command, **kwargs: commands.append(command)
        or SimpleNamespace(returncode=0),
    )

    agent_host._run_job_preparation("Candidate", "person@example.test")
    assert "--no-review" in commands[0]
    assert "--no-cover-letters" in commands[0]

    agent_host._run_job_preparation(
        "Candidate", "person@example.test", allow_remote_letters=True
    )
    assert "--no-cover-letters" not in commands[1]


def test_cli_package_module_is_runnable() -> None:
    result = subprocess.run(
        [sys.executable, "-m", "job_agent.cli", "--help"],
        capture_output=True,
        check=False,
        text=True,
    )
    assert result.returncode == 0
    assert "evaluate-regressions" in result.stdout


def test_mcp_stdio_bridge_connects_to_real_jobs_server(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("JOB_AGENT_DB_PATH", str(tmp_path / "jobs.db"))
    monkeypatch.setattr(agent_host, "_audit_tool_call", lambda *_: None)
    bridge = MCPToolBridge(["jobs_db", "workflow", "tracking"])

    async def run():
        async with bridge.connect():
            assert "jobs_db__db_stats" in bridge.bindings
            assert "workflow__generate_cover_letter" in bridge.bindings
            assert "tracking__confirm_interview_calendar_event" in bridge.bindings
            result = await bridge.call("jobs_db__db_stats", {})
            return json.loads(result)

    result = asyncio.run(run())
    assert result["total_jobs"] == 0


def test_real_cover_letter_tool_cancellation_blocks_external_transfer(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    job_url = "https://jobs.example/recommended"
    db_path = tmp_path / "jobs.db"
    db = JobDatabase(db_path)
    db.save_job(
        {
            "url": job_url,
            "title": "Engineer",
            "company": "Example",
            "description": "Python role",
            "tags": ["Python"],
        }
    )
    db.record_evaluation(
        job_url,
        verdict="APPLY",
        rationale="Relevant experience",
        model="test",
        confidence=90,
        overrides=[],
        details={},
    )
    db.close()
    monkeypatch.setenv("JOB_AGENT_DB_PATH", str(db_path))
    monkeypatch.setattr(agent_host, "_audit_tool_call", lambda *_: None)
    bridge = MCPToolBridge(
        ["workflow"],
        input_fn=lambda _: "n",
    )

    async def run():
        async with bridge.connect():
            return await bridge.call(
                "workflow__generate_cover_letter",
                {"job_url": job_url},
            )

    result = json.loads(asyncio.run(run()))
    assert result["generated"] is False
    assert result["external_data_transfer"] is False
    db = JobDatabase(db_path)
    try:
        assert db.connection.execute(
            "SELECT approved FROM audit_log "
            "WHERE event_type = 'cover_letter.external_transfer_declined'"
        ).fetchone() == (0,)
    finally:
        db.close()


def test_regression_harness_excludes_current_row_and_separates_legacy_decisions(
    tmp_path,
) -> None:
    db = JobDatabase(tmp_path / "jobs.db")
    db.save_job(
        {
            "url": "https://jobs.example/applied",
            "title": "Engineer",
            "company": "A",
            "description": "Python work",
            "tags": ["Python"],
        }
    )
    db.record_action("https://jobs.example/applied", "APPLIED")
    db.save_job(
        {
            "url": "https://jobs.example/skipped",
            "title": "Other Engineer",
            "company": "B",
            "description": "Java work",
            "tags": ["Java"],
        }
    )
    db.record_action("https://jobs.example/skipped", "SKIPPED")
    db.save_job(
        {
            "url": "https://jobs.example/legacy",
            "title": "Legacy Role",
            "company": "C",
            "description": "Old decision",
        }
    )
    db.record_action("https://jobs.example/legacy", "NOT_RECOMMENDED")

    class Agent:
        model = "test"

        def __init__(self):
            self.histories = []

        def decide(self, profile, preferences, match, *, history):
            self.histories.append((match.job.url, history))
            return SimpleNamespace(
                decision="APPLY" if "applied" in match.job.url else "SKIP"
            )

    agent = Agent()
    try:
        result = run_regression_evaluation(
            db,
            agent=agent,
            profile_data=PROFILE,
            preferences_data=PREFERENCES,
        )
        assert result["human_reference"]["cases"] == 2
        assert result["human_reference"]["correct"] == 2
        assert result["legacy_agent_consistency"]["cases"] == 1
        assert result["database_modified"] is False
        assert all(
            row.get("url") != evaluated_url
            for evaluated_url, history in agent.histories
            for row in history
        )
        assert db.get_action("https://jobs.example/applied") == "APPLIED"
    finally:
        db.close()
