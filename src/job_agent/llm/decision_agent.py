"""Milestone 2: the APPLY / SKIP decision agent.

Flow per job:
    profile + preferences + match_result (+ your decision history)
        -> prompt -> Ollama (JSON-schema constrained, temperature 0)
        -> parse + validate (retry with the error message on failure)
        -> deterministic guardrails (Python has the final say)
        -> FinalDecision
"""
import json
import logging
import re
import time
from typing import Any, Dict, List, Optional, Tuple

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

History = List[Dict[str, Any]]  # rows from JobDatabase.get_feedback_history()


# ---------------------------------------------------------------- history

def _norm(text: Optional[str]) -> str:
    return " ".join((text or "").lower().split())


def _tokens(text: str) -> set:
    return set(re.findall(r"[a-zа-я0-9+#.]{2,}", (text or "").lower()))


def _row_tokens(row: Dict[str, Any]) -> set:
    tokens = _tokens(row.get("title") or "")
    try:
        tokens |= _tokens(" ".join(json.loads(row.get("tags_json") or "[]")))
    except (ValueError, TypeError):
        pass
    return tokens


def select_examples(history: History, match: MatchResult, per_class: int = 4) -> History:
    """Pick the most similar past APPLIED and SKIPPED jobs (title + tag overlap).

    Ties keep recency order (history is newest-first and sorted() is stable),
    so with no overlap you simply get your most recent decisions.
    """
    job = match.job
    target = _tokens(job.title or "") | _tokens(" ".join(job.tags or []))
    picked: History = []
    for action in ("APPLIED", "SKIPPED"):
        rows = [h for h in history if h.get("action") == action]

        def score(row: Dict[str, Any]) -> float:
            toks = _row_tokens(row)
            union = target | toks
            return len(target & toks) / len(union) if union else 0.0

        picked += sorted(rows, key=lambda r: -score(r))[:per_class]
    return picked


# ------------------------------------------------------------- guardrails

def apply_guardrails(
    llm: LLMDecision,
    prefs: CandidatePreferences,
    match: MatchResult,
    min_confidence: int,
    history: Optional[History] = None,
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
        req_years = (
            min(match.required_years)
            if isinstance(match.required_years, (list, tuple)) and match.required_years
            else match.required_years
        )
        if (
            prefs.max_required_years is not None
            and req_years is not None
            and float(req_years) > prefs.max_required_years
        ):
            overrides.append(
                f"job requires {req_years}y > max {prefs.max_required_years}y"
            )
        title = (match.job.title or "").lower()
        for bad in prefs.avoid_roles:
            if bad.lower() in title:
                overrides.append(f"title matches avoid_role '{bad}'")
        work_model = (match.job.work_model or "").lower()
        if work_model and prefs.work_models and work_model not in [
            w.lower() for w in prefs.work_models
        ]:
            overrides.append(f"work model '{match.job.work_model}' not in preferences")

        # Learned from your history: identical posting already decided
        # (e.g. the same role re-posted for several cities).
        for h in history or []:
            if _norm(h.get("company")) == _norm(match.job.company) and _norm(
                h.get("title")
            ) == _norm(match.job.title):
                verb = "applied to" if h.get("action") == "APPLIED" else "skipped"
                overrides.append(f"you already {verb} the same company+title")
                break

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
        timeout: float = 300.0,
        keep_alive: str = "30m",
    ):
        self.client = Client(host=host, timeout=timeout)
        self.model = model
        self.min_confidence = min_confidence
        self.max_retries = max_retries
        self.num_ctx = num_ctx
        self.temperature = temperature
        self.keep_alive = keep_alive  # keep the model loaded between jobs

    # ------------------------------------------------------------------ LLM

    def _chat(self, messages: List[dict]) -> str:
        start = time.perf_counter()
        response = self.client.chat(
            model=self.model,
            messages=messages,
            format=LLM_DECISION_SCHEMA,
            options={"temperature": self.temperature, "num_ctx": self.num_ctx},
            keep_alive=self.keep_alive,
        )
        elapsed = time.perf_counter() - start
        content = response["message"]["content"]

        try:
            prompt_tokens = response["prompt_eval_count"]
        except Exception:  # noqa: BLE001
            prompt_tokens = None
        # Ollama silently truncates prompts that exceed num_ctx
        if prompt_tokens and prompt_tokens >= self.num_ctx - 64:
            log.warning(
                "Prompt used %d of %d context tokens: it was probably truncated. "
                "Raise num_ctx or shorten the job description.",
                prompt_tokens,
                self.num_ctx,
            )

        print(
            f"[TIMING] LLM call {elapsed:.1f}s | model={self.model} | "
            f"prompt_tokens={prompt_tokens} | response_chars={len(content)}",
            flush=True,
        )
        return content

    def _ask_llm(self, profile, prefs, match, history: Optional[History]) -> LLMDecision:
        examples = select_examples(history or [], match)
        user_prompt = build_user_prompt(profile, prefs, match, past_decisions=examples)

        messages = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt},
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
        history: Optional[History] = None,
    ) -> FinalDecision:
        base = dict(job_url=match.job.url, title=match.job.title, company=match.job.company)
        try:
            llm = self._ask_llm(profile, prefs, match, history)
        except Exception as e:  # noqa: BLE001 - fail SAFE: never apply on error
            log.error("Decision failed for %s: %s", match.job.url, e)
            return FinalDecision(
                **base, decision="SKIP", confidence=0, rationale="Agent error", error=str(e)
            )

        decision, overrides = apply_guardrails(
            llm, prefs, match, self.min_confidence, history
        )
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