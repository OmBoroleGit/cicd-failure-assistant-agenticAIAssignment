"""Run the LLM agent on one scenario and print its decision."""

import sys
import time

from agents.llm_agent import LLMAgent
from core.scenario_loader import load_scenario

scenario_id = sys.argv[1] if len(sys.argv) > 1 else "B"
print(f"Loading scenario {scenario_id}...", flush=True)
scenario, expected = load_scenario(scenario_id)

print("Calling the LLM agent (this can take a minute)...", flush=True)
start = time.time()
decision = LLMAgent().decide(scenario)

print(f"Finished in {time.time() - start:.1f} s")
print("Expected :", expected)
print("LLM said :", decision.failure_category, "| confidence", decision.confidence)
print("Tools    :", [call["tool"] for call in decision.details["tool_calls"]])
print("Evidence :", decision.evidence)
print("Next step:", decision.next_step)
print("Reasoning:", decision.reasoning)
