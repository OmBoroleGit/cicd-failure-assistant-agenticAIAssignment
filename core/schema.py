
from dataclasses import asdict, dataclass, field
from typing import Any, Literal


FailureCategory = Literal[
    "TEST_FAILURE",
    "DEPENDENCY_FAILURE",
    "DEPLOYMENT_HEALTH_FAILURE",
    "NO_FAILURE",
    "AMBIGUOUS",
]


@dataclass
class AgentDecision:
    """Standard output shared by all six agents."""

    agent_name: str
    failure_category: FailureCategory
    evidence: list[str]
    likely_cause: str
    next_step: str
    verification_checklist: list[str]
    reasoning: str
    confidence: float | None = None
    details: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Convert the decision into a dictionary."""
        return asdict(self)
