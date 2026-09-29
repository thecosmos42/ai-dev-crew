"""Shared bounded tool loop for structured agent terminals."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from typing import Any, TypeVar

from langchain_core.messages import (
    AIMessage,
    BaseMessage,
    HumanMessage,
    SystemMessage,
    ToolMessage,
)
from langchain_core.tools import BaseTool, StructuredTool
from pydantic import BaseModel, ValidationError

from ..llm import LLMClient
from ..metrics.tracker import UsageTracker

T = TypeVar("T", bound=BaseModel)


class SchemaRetriesExhausted(RuntimeError):
    """Raised when a terminal tool never produces a valid payload."""


TerminalValidator = Callable[[BaseModel], None]


def run_tool_loop(
    llm: LLMClient,
    system: str,
    user: str,
    tools: Sequence[BaseTool],
    terminal_models: dict[str, type[BaseModel]],
    max_iters: int,
    tracker: UsageTracker,
    terminal_validators: dict[str, TerminalValidator] | None = None,
    max_schema_retries: int = 2,
) -> BaseModel | None:
    """Run tool calls until a validated terminal payload or an iteration cap."""

    messages: list[BaseMessage] = [SystemMessage(content=system), HumanMessage(content=user)]
    tool_map = {tool.name: tool for tool in tools}
    terminal_validators = terminal_validators or {}
    terminal_tools = [
        StructuredTool.from_function(
            func=lambda **kwargs: "terminal tool handled by the agent loop",
            name=name,
            description=f"Submit the final {name} payload.",
            args_schema=model,
        )
        for name, model in terminal_models.items()
    ]

    for iteration in range(max_iters):
        if iteration == max_iters - 1:
            messages.append(HumanMessage(content="You must call the terminal tool now."))
        response = llm.invoke(messages, list(tools) + terminal_tools)
        tracker.record_message(response)
        messages.append(response)
        tool_calls = response.tool_calls
        if not tool_calls:
            messages.append(HumanMessage(content="Call a tool. When finished, call the terminal tool."))
            continue

        for tool_call in tool_calls:
            name = tool_call.get("name", "")
            args = tool_call.get("args", {})
            call_id = tool_call.get("id", name)
            tracker.tool_calls += 1
            if name in terminal_models:
                try:
                    result = terminal_models[name].model_validate(args)
                    validator = terminal_validators.get(name)
                    if validator is not None:
                        validator(result)
                except (ValidationError, ValueError) as exc:
                    tracker.schema_retries += 1
                    if tracker.schema_retries > max_schema_retries:
                        raise SchemaRetriesExhausted(str(exc)) from exc
                    messages.append(
                        ToolMessage(
                            content=f"Your submission was rejected: {exc}. Fix only what is wrong and call the tool again.",
                            tool_call_id=call_id,
                        )
                    )
                    continue
                tracker.details["terminal_tool"] = name
                return result

            tool = tool_map.get(name)
            if tool is None:
                result_text = f"ERROR: unknown tool {name}"
            else:
                try:
                    result_text = str(tool.invoke(args))
                except Exception as exc:
                    result_text = f"ERROR: tool {name} failed: {exc}"
            messages.append(ToolMessage(content=result_text, tool_call_id=call_id))

    tracker.hit_cap = True
    return None