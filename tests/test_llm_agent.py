"""Tests for the LLM agent.

The logic tests use a scripted fake chat model, so they run in seconds on
any machine without Ollama. The live test runs the real local model and only
runs when RUN_LLM_TESTS=1 is set and Ollama is reachable, because each live
run takes one to two minutes.
"""

import json
import os
import unittest
import urllib.request

from langchain_core.messages import AIMessage

from agents.llm_agent import CATEGORIES, LLMAgent, number_tool_output_lines
from core.evidence_check import check_evidence
from core.scenario_loader import load_scenario

NUMPY_ERROR = "ERROR No matching distribution found for numpy==3.0.1"


class FakeChatModel:
    """Returns pre-written replies in order, like a scripted LLM."""

    def __init__(self, replies):
        self.replies = list(replies)

    def bind_tools(self, tools):
        return self

    def invoke(self, messages):
        reply = self.replies.pop(0)
        if isinstance(reply, Exception):
            raise reply
        return reply


def tool_request(*names):
    return AIMessage(
        content="",
        tool_calls=[{"name": name, "args": {}, "id": str(i)} for i, name in enumerate(names)],
    )


def assessment(category, evidence_lines):
    return AIMessage(content=json.dumps({
        "failure_category": category,
        "evidence_lines": evidence_lines,
        "likely_cause": "numpy 3.0.1 does not exist",
        "next_step": "Pin numpy to an available version",
        "verification_checklist": ["Dependencies install", "Pipeline is green"],
        "reasoning": "The logs show the numpy install error.",
        "confidence": 0.9,
    }))


def numpy_line_numbers(scenario, tool_names):
    """Line numbers the agent will show the model for these tools' outputs."""
    from tools.pipeline_tools import TOOLS_BY_NAME, set_scenario

    set_scenario(scenario)
    calls = [{"tool": name, "output": TOOLS_BY_NAME[name].invoke({})} for name in tool_names]
    lines = number_tool_output_lines(calls)
    return [i for i, line in enumerate(lines, 1) if NUMPY_ERROR in line]


class TestLLMAgentLogic(unittest.TestCase):
    def setUp(self):
        self.scenario, _ = load_scenario("B")
        self.tools = ["get_pipeline_status", "read_build_logs"]
        self.lines = numpy_line_numbers(self.scenario, self.tools)

    def test_native_tool_calling_with_grounded_evidence(self):
        model = FakeChatModel([
            tool_request(*self.tools),
            AIMessage(content="done"),
            assessment("DEPENDENCY_FAILURE", self.lines),
        ])
        decision = LLMAgent(llm=model).decide(self.scenario)

        self.assertEqual(decision.failure_category, "DEPENDENCY_FAILURE")
        self.assertEqual(decision.details["tool_mode"], "native")
        self.assertGreaterEqual(decision.details["tool_call_count"], 2)
        self.assertTrue(any(NUMPY_ERROR in item for item in decision.evidence))
        self.assertTrue(check_evidence(decision, self.scenario)["all_grounded"])
        self.assertTrue(decision.next_step.endswith("Human action required"))

    def test_structured_selection_when_model_skips_tools(self):
        model = FakeChatModel([
            AIMessage(content="It is probably a test failure."),
            AIMessage(content='{"next_tool": "get_pipeline_status"}'),
            AIMessage(content='{"next_tool": "read_build_logs"}'),
            AIMessage(content='{"next_tool": "done"}'),
            assessment("DEPENDENCY_FAILURE", self.lines),
        ])
        decision = LLMAgent(llm=model).decide(self.scenario)

        self.assertEqual(decision.details["tool_mode"], "structured")
        self.assertEqual([c["tool"] for c in decision.details["tool_calls"]], self.tools)
        self.assertTrue(check_evidence(decision, self.scenario)["all_grounded"])

    def test_repeated_tool_calls_are_not_duplicated(self):
        model = FakeChatModel([
            tool_request("get_pipeline_status"),
            tool_request("read_build_logs", "get_dependency_info"),
            tool_request("read_build_logs", "get_dependency_info"),
            assessment("DEPENDENCY_FAILURE", [1]),
        ])
        decision = LLMAgent(llm=model).decide(self.scenario)
        tools = [c["tool"] for c in decision.details["tool_calls"]]
        self.assertEqual(len(tools), len(set(tools)))

    def test_out_of_range_evidence_lines_are_ignored(self):
        model = FakeChatModel([
            tool_request(*self.tools),
            AIMessage(content="done"),
            assessment("DEPENDENCY_FAILURE", [0, 9999]),
        ])
        decision = LLMAgent(llm=model).decide(self.scenario)
        self.assertEqual(decision.evidence, [])

    def test_unusable_assessment_falls_back_safely(self):
        model = FakeChatModel([
            tool_request(*self.tools),
            AIMessage(content="done"),
            AIMessage(content="not json"),
            AIMessage(content='{"failure_category": "BROKEN"}'),
        ])
        decision = LLMAgent(llm=model).decide(self.scenario)
        self.assertEqual(decision.failure_category, "AMBIGUOUS")
        self.assertIn("usable assessment", decision.reasoning)

    def test_unreachable_model_falls_back_safely(self):
        model = FakeChatModel([ConnectionError("Ollama is not running")])
        decision = LLMAgent(llm=model).decide(self.scenario)
        self.assertEqual(decision.failure_category, "AMBIGUOUS")
        self.assertIn("LLM call failed", decision.reasoning)


def ollama_available():
    try:
        urllib.request.urlopen("http://localhost:11434/api/tags", timeout=2)
        return True
    except Exception:
        return False


@unittest.skipUnless(
    os.getenv("RUN_LLM_TESTS") == "1" and ollama_available(),
    "Live LLM test: set RUN_LLM_TESTS=1 and start Ollama to run it.",
)
class TestLLMAgentLive(unittest.TestCase):
    def test_live_model_on_dependency_scenario(self):
        scenario, expected = load_scenario("B")
        decision = LLMAgent().decide(scenario)

        self.assertIn(decision.failure_category, CATEGORIES)
        self.assertGreaterEqual(decision.details["tool_call_count"], 2)
        self.assertTrue(check_evidence(decision, scenario)["all_grounded"])
        self.assertEqual(decision.failure_category, expected)


if __name__ == "__main__":
    unittest.main()
