"""LLM Agent (local Ollama model with tool calling via LangChain)."""

from agents.base import BaseAgent
from core.schema import AgentDecision


class LLMAgent(BaseAgent):
    name = "LLM Agent"

    def decide(self, scenario: dict) -> AgentDecision:
        return AgentDecision(
            agent_name=self.name,
            failure_category="AMBIGUOUS",
            evidence=[],
            likely_cause="LLM agent not yet implemented.",
            next_step="No recommendation yet. Human action required",
            verification_checklist=["Implement the LLM agent."],
            reasoning="Placeholder so the runner and UI can run end to end.",
            confidence=None,
        )
