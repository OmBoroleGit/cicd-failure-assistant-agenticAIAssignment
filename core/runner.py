
from agents.simple_reflex import SimpleReflexAgent
from agents.model_based_reflex import ModelBasedReflexAgent
from agents.goal_based import GoalBasedAgent
from agents.utility_based import UtilityBasedAgent
from agents.learning_agent import LearningAgent
from agents.llm_agent import LLMAgent

from core.scenario_loader import load_scenario
from core.schema import AgentDecision


def run_all_agents(scenario_id: str) -> list[AgentDecision]:
    """
    Load one scenario and pass the same scenario data
    to all six agents.

    Returns:
        A list containing one AgentDecision per agent.
    """
    scenario, _expected_category = load_scenario(scenario_id)

    agents = [
        SimpleReflexAgent(),
        ModelBasedReflexAgent(),
        GoalBasedAgent(),
        UtilityBasedAgent(),
        LearningAgent(),
        LLMAgent(),
    ]

    decisions = []

    for agent in agents:
        decision = agent.decide(scenario)
        decisions.append(decision)

    return decisions
