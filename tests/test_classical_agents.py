
import unittest

from core.scenario_loader import load_scenario
from agents.simple_reflex import SimpleReflexAgent
from agents.model_based_reflex import ModelBasedReflexAgent


EXPECTED_CATEGORIES = {
    "A": "TEST_FAILURE",
    "B": "DEPENDENCY_FAILURE",
    "C": "DEPLOYMENT_HEALTH_FAILURE",
    "D": "NO_FAILURE",
    "E": "AMBIGUOUS",
}


class TestClassicalReflexAgents(unittest.TestCase):
    def setUp(self):
        self.agents = [
            SimpleReflexAgent(),
            ModelBasedReflexAgent(),
        ]

    def test_agents_classify_all_scenarios_correctly(self):
        for scenario_id, expected_category in EXPECTED_CATEGORIES.items():
            scenario, _ = load_scenario(scenario_id)

            for agent in self.agents:
                with self.subTest(
                    agent=agent.name,
                    scenario=scenario_id,
                ):
                    decision = agent.decide(scenario)

                    self.assertEqual(
                        decision.failure_category,
                        expected_category,
                    )

    def test_agents_return_valid_decision_structure(self):
        for scenario_id in EXPECTED_CATEGORIES:
            scenario, _ = load_scenario(scenario_id)

            for agent in self.agents:
                with self.subTest(
                    agent=agent.name,
                    scenario=scenario_id,
                ):
                    decision = agent.decide(scenario)

                    self.assertIsInstance(decision.agent_name, str)
                    self.assertIsInstance(decision.evidence, list)
                    self.assertIsInstance(decision.likely_cause, str)
                    self.assertIsInstance(decision.next_step, str)
                    self.assertIsInstance(
                        decision.verification_checklist, list
                    )
                    self.assertIsInstance(decision.reasoning, str)
                    self.assertIsInstance(decision.details, dict)

    def test_confidence_is_within_valid_range(self):
        for scenario_id in EXPECTED_CATEGORIES:
            scenario, _ = load_scenario(scenario_id)

            for agent in self.agents:
                with self.subTest(
                    agent=agent.name,
                    scenario=scenario_id,
                ):
                    decision = agent.decide(scenario)

                    self.assertIsNotNone(decision.confidence)
                    self.assertGreaterEqual(decision.confidence, 0.0)
                    self.assertLessEqual(decision.confidence, 1.0)

    def test_recommendations_require_human_action(self):
        for scenario_id in EXPECTED_CATEGORIES:
            scenario, _ = load_scenario(scenario_id)

            for agent in self.agents:
                with self.subTest(
                    agent=agent.name,
                    scenario=scenario_id,
                ):
                    decision = agent.decide(scenario)

                    self.assertTrue(
                        decision.next_step.strip().endswith(
                            "Human action required"
                        )
                    )

    def test_expected_category_is_hidden_from_agents(self):
        for scenario_id in EXPECTED_CATEGORIES:
            scenario, _ = load_scenario(scenario_id)

            self.assertNotIn("expected_category", scenario)

            for agent in self.agents:
                decision = agent.decide(scenario)
                self.assertIsNotNone(decision)


if __name__ == "__main__":
    unittest.main()
