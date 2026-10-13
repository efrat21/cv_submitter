"""Milestone 2: the APPLY / SKIP decision agent.

Flow per job:
    profile + preferences + match_result
        -> prompt -> Ollama (JSON-schema constrained, temperature 0)
        -> parse + validate (retry with the error message on failure)
        -> deterministic guardrails (Python has the final say)
        -> FinalDecision
"""
import json
import logging
from typing import List, Tuple

from ollama import Client

from ..models import (
    LLM_DECISION_SCHEMA,
    CandidatePreferences,
    CandidateProfile,
    FinalDecision,
    LLMDecision,
    MatchResult,
)
from .prompts import SYSTEM_PROMPT, build_user_prompt

log = logging.getLogger(__name__)


def apply_guardrails(
    llm: LLMDecision, prefs: CandidatePreferences, match: MatchResult, min_confidence: int
) -> Tuple[str, List[str]]:
    """Deterministic rules that can only make the agent MORE conservative.

    Returns (final_decision, list_of_override_reasons).
    """
    decision = llm.decision
    overrides: List[str] = []

    if decision == "APPLY":
        if llm.hard_blockers:
            overrides.append(f"hard blockers: {'; '.join(llm.hard_blockers)}")
        if llm.role_fit == "weak":
            overrides.append("role_fit is weak")
        if llm.seniority_fit in ("too_senior", "too_junior"):
            overrides.append(f"seniority_fit is {llm.seniority_fit}")
        if llm.location_fit == "bad":
            overrides.append("location_fit is bad")
        if llm.confidence < min_confidence:
            overrides.append(f"confidence {llm.confidence} < {min_confidence}")
        if (
            prefs.max_required_years is not None
            and match.required_years is not None
            and match.required_years > prefs.max_required_years
        ):
            overrides.append(
                f"job requires {match.required_years}y > max {prefs.max_required_years}y"
            )
        title = match.job.title.lower()
        for bad in prefs.avoid_roles:
            if bad.lower() in title:
                overrides.append(f"title matches avoid_role '{bad}'")
        work_model = match.job.work_model.lower()
        if work_model and prefs.work_models and work_model not in [
            w.lower() for w in prefs.work_models
        ]:
            overrides.append(f"work model '{match.job.work_model}' not in preferences")

        if overrides:
            decision = "SKIP"

    return decision, overrides


class DecisionAgent:
    def __init__(
        self,
        model: str = "qwen2.5:7b",
        host: str = "http://localhost:11434",
        min_confidence: int = 70,
        max_retries: int = 2,
        num_ctx: int = 8192,
        temperature: float = 0.0,
    ):
        self.client = Client(host=host)
        self.model = model
        self.min_confidence = min_confidence
        self.max_retries = max_retries
        self.num_ctx = num_ctx
        self.temperature = temperature

    # ------------------------------------------------------------------ LLM
    def _chat(self, messages: List[dict]) -> str:
        response = self.client.chat(
            model=self.model,
            messages=messages,
            format=LLM_DECISION_SCHEMA,  # constrain output to our schema
            options={"temperature": self.temperature, "num_ctx": self.num_ctx},
        )
        return response["message"]["content"]

    def _ask_llm(self, profile, prefs, match) -> LLMDecision:
        messages = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": build_user_prompt(profile, prefs, match)},
        ]
        last_error = None
        for attempt in range(self.max_retries + 1):
            raw = self._chat(messages)
            try:
                return LLMDecision.from_dict(json.loads(raw))
            except ValueError as e:  # includes json.JSONDecodeError
                last_error = e
                log.warning("Invalid LLM output (attempt %d): %s", attempt + 1, e)
                messages += [
                    {"role": "assistant", "content": raw},
                    {
                        "role": "user",
                        "content": f"Your output was invalid: {e}\n"
                        "Return corrected JSON only.",
                    },
                ]
        raise ValueError(f"LLM failed to produce valid JSON: {last_error}")

    # --------------------------------------------------------------- public
    def decide(
        self,
        profile: CandidateProfile,
        prefs: CandidatePreferences,
        match: MatchResult,
    ) -> FinalDecision:
        base = dict(job_url=match.job.url, title=match.job.title, company=match.job.company)
        try:
            llm = self._ask_llm(profile, prefs, match)
        except Exception as e:  # noqa: BLE001 - fail SAFE: never apply on error
            log.error("Decision failed for %s: %s", match.job.url, e)
            return FinalDecision(
                **base, decision="SKIP", confidence=0, rationale="Agent error", error=str(e)
            )

        decision, overrides = apply_guardrails(llm, prefs, match, self.min_confidence)
        rationale = llm.rationale
        if overrides:
            rationale += f" [Overridden to SKIP: {'; '.join(overrides)}]"

        return FinalDecision(
            **base,
            decision=decision,
            confidence=llm.confidence,
            rationale=rationale,
            overrides=overrides,
            llm=llm,
        )