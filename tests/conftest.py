from collections.abc import Sequence

from langchain_core.messages import AIMessage, BaseMessage


class ScriptedLLM:
    """Offline LLM test double that returns queued AI messages."""

    def __init__(self, responses: Sequence[AIMessage]):
        self.responses = list(responses)

    def invoke(self, messages: Sequence[BaseMessage], tools=None) -> AIMessage:
        if not self.responses:
            raise AssertionError("ScriptedLLM has no queued response")
        return self.responses.pop(0)