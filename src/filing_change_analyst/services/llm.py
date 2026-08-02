"""Thin, guarded wrapper around the Messages API.

Targets DeepSeek by default, which serves an Anthropic-compatible endpoint,
so the `anthropic` SDK is used against either provider unchanged. The one
behavioural difference that matters is structured output — see `structured`.

Design rules enforced here:

* The model is **optional**. Every caller must work when :attr:`LlmClient.available`
  is False.
* Output is **schema-constrained** — the model returns JSON validated against a
  Pydantic model before anything downstream sees it.
* Filing text is passed as **untrusted data** inside delimited blocks, with
  instruction-like strings redacted first.
* Every call is logged (model, prompt version, latency, tokens) without ever
  logging the API key.
"""

from __future__ import annotations

import logging
import time
from typing import TypeVar

from pydantic import BaseModel, ValidationError

from ..config import get_settings
from ..models import LlmRunLog

log = logging.getLogger(__name__)

T = TypeVar("T", bound=BaseModel)

PROMPT_VERSION = "2026-07-30.1"

_TOOL_NAME = "record_analysis"


def _tool_input(resp: object) -> dict | None:
    """Return the input of the first ``tool_use`` block, or None.

    A compatible endpoint may return text alongside, or instead of, the forced
    tool call.
    """
    for block in getattr(resp, "content", None) or []:
        if getattr(block, "type", None) == "tool_use":
            payload = getattr(block, "input", None)
            if isinstance(payload, dict):
                return payload
    return None


class LlmUnavailable(RuntimeError):
    """Raised when a model call is attempted without a configured key."""


class LlmClient:
    """Structured-output client. Never raises into the UI — callers get logs."""

    def __init__(self, api_key: str | None = None) -> None:
        self.settings = get_settings()
        self._api_key = api_key if api_key is not None else self.settings.api_key
        self._client = None
        self.logs: list[LlmRunLog] = []

    @property
    def available(self) -> bool:
        return bool(self._api_key and self._api_key.strip())

    @property
    def model(self) -> str:
        return self.settings.llm_model

    def _anthropic(self):  # type: ignore[no-untyped-def]
        if self._client is None:
            import anthropic

            self._client = anthropic.Anthropic(
                api_key=self._api_key,
                base_url=self.settings.llm_base_url,
                timeout=self.settings.llm_timeout,
                max_retries=self.settings.llm_max_retries,
            )
        return self._client

    # ------------------------------------------------------------------ #

    def structured(
        self,
        *,
        system: str,
        user: str,
        schema: type[T],
        purpose: str,
        max_tokens: int | None = None,
    ) -> tuple[T | None, LlmRunLog]:
        """Run one schema-constrained call.

        Returns ``(parsed, run_log)``. ``parsed`` is ``None`` on any failure —
        network error, timeout, refusal, truncation or schema-validation
        failure — so a bad model response degrades to the deterministic path
        instead of surfacing junk.

        The schema rides a forced tool call rather than
        ``output_config.format``, which DeepSeek ignores — sending it that way
        returns unconstrained prose that fails validation on every request.
        """
        started = time.perf_counter()
        if not self.available:
            entry = LlmRunLog(
                model=self.model,
                prompt_version=PROMPT_VERSION,
                purpose=purpose,
                latency_ms=0,
                ok=False,
                error="No API_KEY configured; AI synthesis is disabled.",
            )
            self.logs.append(entry)
            return None, entry

        error = ""
        parsed: T | None = None
        input_tokens = output_tokens = None
        try:
            resp = self._anthropic().messages.create(
                model=self.model,
                max_tokens=max_tokens or self.settings.llm_max_tokens,
                system=system,
                output_config={"effort": self.settings.llm_effort},
                messages=[{"role": "user", "content": user}],
                # Thinking mode rejects a forced tool_choice on both providers,
                # and the forced call is what carries the schema.
                thinking={"type": "disabled"},
                tools=[
                    {
                        "name": _TOOL_NAME,
                        "description": (
                            "Record the analysis. Every field is required; use the "
                            "supplied evidence and metric values only."
                        ),
                        "input_schema": schema.model_json_schema(),
                    }
                ],
                tool_choice={"type": "tool", "name": _TOOL_NAME},
            )
            usage = getattr(resp, "usage", None)
            input_tokens = getattr(usage, "input_tokens", None)
            output_tokens = getattr(usage, "output_tokens", None)
            stop = getattr(resp, "stop_reason", None)
            if stop == "refusal":
                error = "The model declined to answer this request."
            elif stop == "max_tokens":
                error = "The model response was truncated before it produced valid JSON."
            else:
                payload = _tool_input(resp)
                if payload is None:
                    error = "The model returned no structured tool call."
                else:
                    # A forced tool call constrains the shape; it does not
                    # guarantee it.
                    parsed = schema.model_validate(payload)
        except ValidationError as exc:
            error = f"Model output failed schema validation: {exc.error_count()} error(s)."
        except Exception as exc:  # noqa: BLE001 - degrade, never crash the app
            error = f"{type(exc).__name__}: {exc}"

        entry = LlmRunLog(
            model=self.model,
            prompt_version=PROMPT_VERSION,
            purpose=purpose,
            latency_ms=int((time.perf_counter() - started) * 1000),
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            ok=parsed is not None,
            error=error,
        )
        if error:
            log.warning("LLM call '%s' failed: %s", purpose, error)
        self.logs.append(entry)
        return parsed, entry
