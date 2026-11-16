import unittest

from agents.goal_based import GoalBasedAgent
from agents.learning_agent import LearningAgent
from agents.model_based_reflex import ModelBasedReflexAgent
from agents.simple_reflex import SimpleReflexAgent
from agents.utility_based import UtilityBasedAgent
from core.evidence_check import check_evidence
from core.scenario_loader import load_scenario
from core.schema import AgentDecision

SCENARIOS = ["A", "B", "C", "D", "E"]


def make_decision(evidence, tool_calls=None):
    return AgentDecision(
        agent_name="Test Agent",
        failure_category="AMBIGUOUS",
        evidence=evidence,
        likely_cause="",
        next_step="",
        verification_checklist=[],
        reasoning="",
        details={"tool_calls": tool_calls or []},
    )


class TestEvidenceCheck(unittest.TestCase):
    def test_classical_agents_cite_only_grounded_evidence(self):
        agents = [
            SimpleReflexAgent(),
            ModelBasedReflexAgent(),
            GoalBasedAgent(),
            UtilityBasedAgent(),
            LearningAgent(),
        ]
        for scenario_id in SCENARIOS:
            scenario, _ = load_scenario(scenario_id)
            for agent in agents:
                with self.subTest(scenario=scenario_id, agent=agent.name):
                    result = check_evidence(agent.decide(scenario), scenario)
                    self.assertTrue(result["all_grounded"], result["items"])

    def test_log_line_is_grounded(self):
        scenario, _ = load_scenario("B")
        line = "[2026-11-09 09:20:11] ERROR No matching distribution found for numpy==3.0.1"
        result = check_evidence(make_decision([line]), scenario)
        self.assertTrue(result["all_grounded"])

    def test_invented_evidence_is_not_grounded(self):
        scenario, _ = load_scenario("B")
        result = check_evidence(make_decision(["test_unit_1: failed"]), scenario)
        self.assertFalse(result["all_grounded"])
        self.assertEqual(result["grounded_ratio"], 0.0)

    def test_mixed_evidence_gives_partial_ratio(self):
        scenario, _ = load_scenario("B")
        evidence = ["numpy==3.0.1", "payment processing logic changed"]
        result = check_evidence(make_decision(evidence), scenario)
        self.assertEqual(result["grounded_count"], 1)
        self.assertEqual(result["grounded_ratio"], 0.5)

    def test_tool_output_lines_count_as_sources(self):
        scenario, _ = load_scenario("C")
        tool_calls = [{"tool": "get_pipeline_status", "output": '{\n  "status_code": 503,\n}'}]
        result = check_evidence(make_decision(['"status_code": 503,'], tool_calls), scenario)
        self.assertTrue(result["all_grounded"])

    def test_no_evidence_is_not_all_grounded(self):
        scenario, _ = load_scenario("D")
        result = check_evidence(make_decision([]), scenario)
        self.assertFalse(result["all_grounded"])
        self.assertEqual(result["total"], 0)


if __name__ == "__main__":
    unittest.main()
