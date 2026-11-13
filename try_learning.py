from core.scenario_loader import load_scenario
from agents.learning_agent import LearningAgent

scenario, _ = load_scenario("E")
agent = LearningAgent()

# Pretend the user clicks "did not work" 4 times on the agent's choice.
for click in range(1, 5):
    decision = agent.decide(scenario)
    chosen = decision.details["chosen_action"]
    print(f"Run {click}: chose '{chosen}' (rate {decision.confidence})")
    agent.update("AMBIGUOUS", chosen, success=False)

decision = agent.decide(scenario)
print("\nAfter feedback, it now chooses:", decision.details["chosen_action"])
print("\nReasoning:", decision.reasoning)
