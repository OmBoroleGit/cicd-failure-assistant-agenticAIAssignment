
from abc import ABC, abstractmethod

from core.schema import AgentDecision


class BaseAgent(ABC):
    """Base interface implemented by all six agents."""

    name: str = "Base"

    @abstractmethod
    def decide(self, scenario: dict) -> AgentDecision:
        """
        Receive the shared scenario dictionary and return
        a standard AgentDecision.
        
        The scenario must not contain expected_category.
        """
        raise NotImplementedError
