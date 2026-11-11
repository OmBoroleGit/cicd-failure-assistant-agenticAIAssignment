
import unittest

from core.schema import AgentDecision


class TestAgentDecision(unittest.TestCase):
    def setUp(self):
        self.decision = AgentDecision(
            agent_name="Simple Reflex",
            failure_category="TEST_FAILURE",
            evidence=["3 tests failed"],
            likely_cause="A code change caused test failures.",
            next_step="Inspect the failed tests. Human action required",
            verification_checklist=[
                "Review failed tests",
                "Run the test suite again",
            ],
            reasoning="The current pipeline data reports failed tests.",
            confidence=0.95,
        )

    def test_decision_creation(self):
        self.assertEqual(self.decision.agent_name, "Simple Reflex")
        self.assertEqual(self.decision.failure_category, "TEST_FAILURE")

    def test_to_dict_returns_dictionary(self):
        result = self.decision.to_dict()

        self.assertIsInstance(result, dict)
        self.assertEqual(result["failure_category"], "TEST_FAILURE")

    def test_required_fields_are_present(self):
        result = self.decision.to_dict()

        required_fields = {
            "agent_name",
            "failure_category",
            "evidence",
            "likely_cause",
            "next_step",
            "verification_checklist",
            "reasoning",
            "confidence",
            "details",
        }

        self.assertEqual(set(result.keys()), required_fields)

    def test_confidence_value(self):
        self.assertGreaterEqual(self.decision.confidence, 0.0)
        self.assertLessEqual(self.decision.confidence, 1.0)

    def test_details_defaults_to_empty_dictionary(self):
        self.assertEqual(self.decision.details, {})

    def test_to_dict_preserves_evidence_and_checklist(self):
        result = self.decision.to_dict()

        self.assertEqual(result["evidence"], ["3 tests failed"])
        self.assertEqual(
            result["verification_checklist"],
            ["Review failed tests", "Run the test suite again"],
        )


if __name__ == "__main__":
    unittest.main()
