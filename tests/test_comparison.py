import unittest

from core.comparison import agreement_summary, build_table, explain_differences, to_csv, to_markdown
from core.scenario_loader import load_scenario
from core.schema import AgentDecision


def decision(name, category, confidence, step, evidence=("numpy==3.0.1",)):
    return AgentDecision(
        agent_name=name,
        failure_category=category,
        evidence=list(evidence),
        likely_cause="",
        next_step=f"{step}. Human action required",
        verification_checklist=[],
        reasoning="",
        confidence=confidence,
    )


class TestComparison(unittest.TestCase):
    def setUp(self):
        self.scenario, _ = load_scenario("B")
        self.decisions = [
            decision("Simple Reflex Agent", "DEPENDENCY_FAILURE", 0.9, "Pin numpy"),
            decision("Learning Agent", "DEPENDENCY_FAILURE", 0.5, "Check the lockfile"),
            decision("LLM Agent", "AMBIGUOUS", 0.7, "Pin numpy", evidence=["made up"]),
        ]

    def test_table_has_one_row_per_agent_with_grounding(self):
        table = build_table(self.decisions, self.scenario)
        self.assertEqual(len(table), 3)
        self.assertEqual(list(table["Evidence grounded"]), ["1/1", "1/1", "0/1"])

    def test_agreement_summary_names_the_dissenter(self):
        summary = agreement_summary(self.decisions)
        self.assertEqual(summary["majority_category"], "DEPENDENCY_FAILURE")
        self.assertEqual(summary["agreeing"], 2)
        self.assertEqual(summary["dissenting"], {"LLM Agent": "AMBIGUOUS"})
        self.assertFalse(summary["unanimous"])

    def test_explanation_covers_category_confidence_and_steps(self):
        text = " ".join(explain_differences(self.decisions))
        self.assertIn("LLM Agent chose AMBIGUOUS", text)
        self.assertIn("Confidence ranges from 0.50", text)
        self.assertIn("2 different next steps", text)

    def test_exports_include_every_agent(self):
        markdown = to_markdown(self.decisions, self.scenario, title="Scenario B")
        csv_text = to_csv(self.decisions, self.scenario)
        for item in self.decisions:
            self.assertIn(item.agent_name, markdown)
            self.assertIn(item.agent_name, csv_text)


if __name__ == "__main__":
    unittest.main()
