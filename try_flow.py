from core.scenario_loader import load_scenario
from agents.simple_reflex import SimpleReflexAgent
from agents.model_based_reflex import ModelBasedReflexAgent

scenario, answer = load_scenario("E")          # try A, B, C, D, E
print("Answer key (agents never see this):", answer)

for agent in [SimpleReflexAgent(), ModelBasedReflexAgent()]:
    d = agent.decide(scenario)
    print("\n---", d.agent_name)
    print("Category :", d.failure_category)
    print("Rule     :", d.details.get("rule_fired"))
    print("Evidence :", d.evidence)
    print("Next step:", d.next_step)
