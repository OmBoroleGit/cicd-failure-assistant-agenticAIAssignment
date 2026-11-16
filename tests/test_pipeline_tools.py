import copy
import json
import unittest

from core.scenario_loader import load_scenario
from tools.pipeline_tools import ALL_TOOLS, TOOLS_BY_NAME, set_scenario


class TestPipelineTools(unittest.TestCase):
    def setUp(self):
        self.scenario, _ = load_scenario("B")
        set_scenario(self.scenario)

    def call(self, name):
        return TOOLS_BY_NAME[name].invoke({})

    def test_five_tools_are_available(self):
        self.assertEqual(
            sorted(t.name for t in ALL_TOOLS),
            sorted([
                "get_pipeline_status",
                "read_build_logs",
                "get_test_results",
                "get_recent_change_summary",
                "get_dependency_info",
            ]),
        )

    def test_pipeline_status_returns_stages_health_and_history(self):
        data = json.loads(self.call("get_pipeline_status"))
        self.assertEqual(data["pipeline_status"], self.scenario["pipeline_status"])
        self.assertEqual(data["deployment_health"], self.scenario["deployment_health"])
        self.assertEqual(data["run_history"], self.scenario["run_history"])

    def test_build_logs_are_returned_as_raw_text(self):
        self.assertEqual(self.call("read_build_logs"), self.scenario["build_logs"])

    def test_json_tools_return_their_slice(self):
        self.assertEqual(json.loads(self.call("get_test_results")), self.scenario["test_results"])
        self.assertEqual(json.loads(self.call("get_recent_change_summary")), self.scenario["recent_changes"])
        self.assertEqual(json.loads(self.call("get_dependency_info")), self.scenario["dependencies"])

    def test_tools_are_read_only(self):
        before = copy.deepcopy(self.scenario)
        for tool in ALL_TOOLS:
            tool.invoke({})
        self.assertEqual(self.scenario, before)

    def test_tools_do_not_expose_the_expected_answer(self):
        for tool in ALL_TOOLS:
            self.assertNotIn("expected_category", tool.invoke({}))


if __name__ == "__main__":
    unittest.main()
