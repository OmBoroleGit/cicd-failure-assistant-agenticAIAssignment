"""Offline runner checks and optional live six-agent integration tests."""

from copy import deepcopy
import math
from numbers import Real
import os

import pytest

import core.runner as runner
from core.schema import AgentDecision


EXPECTED = {
    "A": "TEST_FAILURE",
    "B": "DEPENDENCY_FAILURE",
    "C": "DEPLOYMENT_HEALTH_FAILURE",
    "D": "NO_FAILURE",
    "E": "AMBIGUOUS",
}

AGENT_CLASSES = (
    "SimpleReflexAgent",
    "ModelBasedReflexAgent",
    "GoalBasedAgent",
    "UtilityBasedAgent",
    "LearningAgent",
    "LLMAgent",
)

ALLOWED_CATEGORIES = set(EXPECTED.values())


@pytest.mark.parametrize("scenario_id", tuple(EXPECTED))
def test_loader_excludes_expected_answer(scenario_id):
    scenario, expected = runner.load_scenario(scenario_id)
    assert isinstance(scenario, dict) and scenario
    assert "expected_category" not in scenario
    assert expected == EXPECTED[scenario_id]


def _substitute_class(name, token, baseline, calls, constructed):
    class SubstituteAgent:
        def __init__(self):
            constructed.append(name)

        def decide(self, scenario):
            assert scenario == baseline, f"Different input for {name}"
            assert "expected_category" not in scenario
            calls.append((name, deepcopy(scenario)))
            return token

    return SubstituteAgent


@pytest.mark.parametrize("scenario_id", tuple(EXPECTED))
def test_runner_routes_one_equal_input_to_all_six_agents(
    scenario_id, monkeypatch
):
    """Check actual runner routing using substitute agents."""
    scenario, expected = runner.load_scenario(scenario_id)
    baseline = deepcopy(scenario)
    loader_calls = []
    calls = []
    constructed = []
    tokens = [object() for _ in AGENT_CLASSES]

    def tracked_loader(selected_id):
        loader_calls.append(selected_id)
        return scenario, expected

    monkeypatch.setattr(runner, "load_scenario", tracked_loader)

    for name, token in zip(AGENT_CLASSES, tokens):
        monkeypatch.setattr(
            runner,
            name,
            _substitute_class(
                name, token, baseline, calls, constructed
            ),
        )

    decisions = runner.run_all_agents(scenario_id)

    assert loader_calls == [scenario_id]
    assert constructed == list(AGENT_CLASSES)
    assert [name for name, _ in calls] == list(AGENT_CLASSES)
    assert all(received == baseline for _, received in calls)
    assert scenario == baseline, "Runner changed the scenario"
    assert isinstance(decisions, list) and len(decisions) == 6
    assert all(
        actual is token
        for actual, token in zip(decisions, tokens)
    )


def _assert_nonempty_text(value, label):
    assert isinstance(value, str) and value.strip(), (
        f"Missing {label}"
    )


def _assert_valid_decision(decision):
    assert isinstance(decision, AgentDecision)
    _assert_nonempty_text(decision.agent_name, "agent_name")
    assert decision.failure_category in ALLOWED_CATEGORIES

    for field in ("likely_cause", "next_step", "reasoning"):
        _assert_nonempty_text(getattr(decision, field), field)

    assert isinstance(decision.evidence, list)
    assert decision.evidence, "No evidence provided"

    for item in decision.evidence:
        _assert_nonempty_text(item, "evidence item")

    checklist = decision.verification_checklist
    assert isinstance(checklist, list)
    assert 3 <= len(checklist) <= 5

    for item in checklist:
        _assert_nonempty_text(item, "checklist item")

    confidence = decision.confidence
    if confidence is not None:
        assert isinstance(confidence, Real)
        assert not isinstance(confidence, bool)
        assert math.isfinite(confidence)
        assert 0 <= confidence <= 1

    assert isinstance(decision.details, dict)
    assert not decision.details.get("error"), (
        decision.details.get("error")
    )


def _observe_decide(original, name, baseline, calls, results):
    def observed(self, scenario):
        assert scenario == baseline, (
            f"Different input at entry to {name}"
        )
        assert "expected_category" not in scenario

        calls.append((name, deepcopy(scenario)))
        before = deepcopy(scenario)

        decision = original(self, scenario)

        assert scenario == before, (
            f"{name}.decide() mutated its input"
        )
        results[name] = decision
        return decision

    return observed


@pytest.mark.skipif(
    os.environ.get("RUN_LIVE_LLM") != "1",
    reason="Requires Ollama/model; enable with RUN_LIVE_LLM=1",
)
@pytest.mark.parametrize("scenario_id", tuple(EXPECTED))
def test_live_six_agents_receive_equal_input_and_return_valid_decisions(
    scenario_id, monkeypatch
):
    """Execute all six actual agents and observe their inputs."""
    scenario, _ = runner.load_scenario(scenario_id)
    baseline = deepcopy(scenario)
    calls = []
    results = {}

    for name in AGENT_CLASSES:
        agent_class = getattr(runner, name)
        monkeypatch.setattr(
            agent_class,
            "decide",
            _observe_decide(
                agent_class.decide,
                name,
                baseline,
                calls,
                results,
            ),
        )

    decisions = runner.run_all_agents(scenario_id)

    assert [name for name, _ in calls] == list(AGENT_CLASSES)
    assert all(received == baseline for _, received in calls)
    assert isinstance(decisions, list) and len(decisions) == 6

    assert all(
        actual is results[name]
        for name, actual in zip(AGENT_CLASSES, decisions)
    )

    for decision in decisions:
        _assert_valid_decision(decision)

    assert len({d.agent_name for d in decisions}) == 6

    llm = results["LLMAgent"]
    tool_calls = llm.details.get("tool_calls", [])
    assert isinstance(tool_calls, list)

    tools = set()
    for call in tool_calls:
        assert isinstance(call, dict)
        _assert_nonempty_text(call.get("tool"), "tool name")
        assert call.get("output") is not None, (
            "Missing tool output"
        )
        tools.add(call["tool"])

    assert len(tools) >= 2, (
        f"Expected at least two distinct tools; got {tools}"
    )
