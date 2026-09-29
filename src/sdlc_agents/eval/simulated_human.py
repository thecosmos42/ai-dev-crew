"""Deterministic human answers for offline graph evaluation."""


class SimulatedHuman:
    def __init__(self, script: dict[str, list[str]]):
        self.script = script

    def answer(self, interrupt_value: dict) -> str:
        agent = interrupt_value["agent"]
        round_number = int(interrupt_value["round"])
        answers = self.script.get(agent, [])
        return answers[round_number] if round_number < len(answers) else "I don't know."