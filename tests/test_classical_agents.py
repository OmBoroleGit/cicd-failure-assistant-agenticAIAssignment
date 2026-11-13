
import shutil
import tempfile
import unittest
from pathlib import Path

from core.scenario_loader import load_scenario
from agents.simple_reflex import SimpleReflexAgent
from agents.model_based_reflex import ModelBasedReflexAgent
from agents.goal_based import GoalBasedAgent
from agents.utility_based import UtilityBasedAgent, CANDIDATE_STEPS
from agents.learning_agent import LearningAgent, SEED_FILE

EXPECTED_CATEGORIES = {
    "A": "TEST_FAILURE",
    "B": "DEPENDENCY_FAILURE",
    "C": "DEPLOYMENT_HEALTH_FAILURE",
    "D": "NO_FAILURE",
    "E": "AMBIGUOUS",
}

class TestClassicalAgents(unittest.TestCase):
    def setUp(self):
        self.agents = [
            SimpleReflexAgent(),
            ModelBasedReflexAgent(),
            GoalBasedAgent(),
            UtilityBasedAgent(),
            LearningAgent(),
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

class TestGoalBasedAgent(unittest.TestCase):
    def test_plan_starts_with_pipeline_check(self):
        agent = GoalBasedAgent()

        for scenario_id in EXPECTED_CATEGORIES:
            scenario, _ = load_scenario(scenario_id)

            with self.subTest(scenario=scenario_id):
                plan = agent.decide(scenario).details["plan"]

                self.assertGreater(len(plan), 0)
                self.assertEqual(plan[0], "check_pipeline_status")

    def test_scenario_e_plan_reviews_run_history(self):
        scenario, _ = load_scenario("E")

        plan = GoalBasedAgent().decide(scenario).details["plan"]

        self.assertIn("review_run_history", plan)

class TestUtilityBasedAgent(unittest.TestCase):
    def test_every_candidate_step_is_scored(self):
        scenario, _ = load_scenario("A")

        scores = UtilityBasedAgent().decide(scenario).details["utility_scores"]

        self.assertEqual(len(scores), len(CANDIDATE_STEPS))

    def test_winner_has_highest_utility(self):
        agent = UtilityBasedAgent()

        for scenario_id in EXPECTED_CATEGORIES:
            scenario, _ = load_scenario(scenario_id)

            with self.subTest(scenario=scenario_id):
                details = agent.decide(scenario).details
                best = max(row["utility"] for row in details["utility_scores"])
                winner_row = next(
                    row for row in details["utility_scores"]
                    if row["step"] == details["winner"]
                )

                self.assertEqual(winner_row["utility"], best)

class TestLearningAgent(unittest.TestCase):
    def setUp(self):
        # Work on a temporary copy so the real experience.json never changes.
        self.temp_dir = Path(tempfile.mkdtemp())
        self.experience_path = self.temp_dir / "experience.json"
        shutil.copyfile(SEED_FILE, self.experience_path)
        self.agent = LearningAgent(experience_path=self.experience_path)
        self.scenario, _ = load_scenario("E")

    def tearDown(self):
        shutil.rmtree(self.temp_dir)

    def test_update_is_saved_to_disk(self):
        action = self.agent.decide(self.scenario).details["chosen_action"]
        before = self.agent.decide(self.scenario).details["experience_counts"][action]["failures"]

        self.agent.update("AMBIGUOUS", action, success=False)

        # A new agent reading the same file must see the new count.
        new_agent = LearningAgent(experience_path=self.experience_path)
        after = new_agent.decide(self.scenario).details["experience_counts"][action]["failures"]

        self.assertEqual(after, before + 1)

    def test_negative_feedback_changes_the_choice(self):
        first_choice = self.agent.decide(self.scenario).details["chosen_action"]

        for _ in range(4):
            self.agent.update("AMBIGUOUS", first_choice, success=False)

        new_choice = self.agent.decide(self.scenario).details["chosen_action"]

        self.assertNotEqual(new_choice, first_choice)

    def test_reset_restores_seed_counts(self):
        first_choice = self.agent.decide(self.scenario).details["chosen_action"]
        self.agent.update("AMBIGUOUS", first_choice, success=False)

        self.agent.reset_experience()

        self.assertEqual(
            self.experience_path.read_text(encoding="utf-8"),
            SEED_FILE.read_text(encoding="utf-8"),
        )

if __name__ == "__main__":
    unittest.main()
