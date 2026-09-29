"""Usage tracking and agent-node metrics."""

from __future__ import annotations

import contextvars
import time
from dataclasses import dataclass, field
from functools import wraps
from typing import Any, Callable, TypeVar

from langchain_core.messages import AIMessage

from ..llm import extract_usage
from .db import MetricsDB

F = TypeVar("F", bound=Callable[..., Any])
tracker_context: contextvars.ContextVar["UsageTracker | None"] = contextvars.ContextVar(
    "sdlc_usage_tracker", default=None
)


def calculate_cost(
    tokens_in: int,
    tokens_out: int,
    input_per_1k: float,
    output_per_1k: float,
) -> float:
    return (tokens_in / 1000 * input_per_1k) + (tokens_out / 1000 * output_per_1k)


@dataclass
class UsageTracker:
    tokens_in: int = 0
    tokens_out: int = 0
    tool_calls: int = 0
    schema_retries: int = 0
    hit_cap: bool = False
    confidence: float | None = None
    details: dict[str, Any] = field(default_factory=dict)

    def record_message(self, message: AIMessage) -> None:
        input_tokens, output_tokens = extract_usage(message)
        self.tokens_in += input_tokens
        self.tokens_out += output_tokens

    def cost(self, input_per_1k: float, output_per_1k: float) -> float:
        return calculate_cost(self.tokens_in, self.tokens_out, input_per_1k, output_per_1k)


def get_current_tracker() -> UsageTracker | None:
    return tracker_context.get()


def tracked_node(
    agent: str,
    db: MetricsDB | None = None,
    model: str = "",
    pricing: dict[str, dict[str, float]] | None = None,
) -> Callable[[F], F]:
    """Track one node invocation while preserving the wrapped function's API."""

    def decorator(function: F) -> F:
        @wraps(function)
        def wrapper(state: Any, *args: Any, **kwargs: Any) -> Any:
            tracker = UsageTracker()
            token = tracker_context.set(tracker)
            started = time.perf_counter()
            outcome = "pass"
            try:
                result = function(state, *args, **kwargs)
                return result
            except Exception:
                outcome = "fail"
                raise
            finally:
                tracker_context.reset(token)
                if db is not None:
                    run_id = getattr(state, "run_id", None)
                    if run_id:
                        prices = (pricing or {}).get(model, {})
                        db.insert_agent_run(
                            run_id=run_id,
                            agent=agent,
                            attempt=db.count_agent_runs(run_id, agent) + 1,
                            latency_ms=(time.perf_counter() - started) * 1000,
                            tokens_in=tracker.tokens_in,
                            tokens_out=tracker.tokens_out,
                            cost_estimate=tracker.cost(
                                prices.get("input_per_1k", 0.0),
                                prices.get("output_per_1k", 0.0),
                            ),
                            outcome=outcome,
                            schema_retries=tracker.schema_retries,
                            tool_calls=tracker.tool_calls,
                            hit_iteration_cap=int(tracker.hit_cap),
                            confidence=tracker.confidence,
                            detail_json=tracker.details,
                        )

        return wrapper  # type: ignore[return-value]

    return decorator