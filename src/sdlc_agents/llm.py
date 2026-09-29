"""Provider-agnostic LLM client and usage helpers."""

from __future__ import annotations

import asyncio
from typing import Any, Protocol, Sequence

import httpx
from langchain.chat_models import init_chat_model
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage
from tenacity import retry, retry_if_exception, stop_after_attempt, wait_exponential

from .config import Settings


class LLMClient(Protocol):
    def invoke(
        self,
        messages: Sequence[BaseMessage],
        tools: list[Any] | None = None,
    ) -> AIMessage:
        ...


class ChatModelClient:
    """Adapter that exposes a small injectable interface over a LangChain model."""

    def __init__(self, model: BaseChatModel):
        self.model = model

    def invoke(
        self,
        messages: Sequence[BaseMessage],
        tools: list[Any] | None = None,
    ) -> AIMessage:
        bound_model = self.model.bind_tools(tools) if tools else self.model
        return bound_model.invoke(list(messages))


def _retryable_exception(exception: BaseException) -> bool:
    name = type(exception).__name__.lower()
    return isinstance(exception, (TimeoutError, asyncio.TimeoutError, httpx.TimeoutException)) or "ratelimit" in name


def get_llm(settings: Settings | None = None) -> LLMClient:
    """Create the configured provider client with bounded transient retries."""

    active_settings = settings or Settings()
    api_key = (
        active_settings.anthropic_api_key
        if active_settings.llm_provider == "anthropic"
        else active_settings.openai_api_key
    )
    model = init_chat_model(
        active_settings.llm_model,
        model_provider=active_settings.llm_provider,
        api_key=api_key,
        temperature=active_settings.llm_temperature,
    )
    client = ChatModelClient(model)
    raw_invoke = client.invoke

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=0.5, min=0.5, max=4),
        retry=retry_if_exception(_retryable_exception),
        reraise=True,
    )
    def invoke_with_retry(messages: Sequence[BaseMessage], tools: list[Any] | None = None) -> AIMessage:
        return raw_invoke(messages, tools)

    client.invoke = invoke_with_retry  # type: ignore[method-assign]
    return client


def extract_usage(ai_message: AIMessage) -> tuple[int, int]:
    """Return input and output token counts from LangChain usage metadata."""

    usage = ai_message.usage_metadata or {}
    return int(usage.get("input_tokens", 0)), int(usage.get("output_tokens", 0))