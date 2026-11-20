"""Build results/comparison_table.md.

The five classical agents are deterministic, so they are re-run on every
scenario: their decisions always match the current code and the current
Learning Agent experience file. The LLM Agent's decisions are taken from the
recorded runs in results/decisions_*.json, because each LLM run takes one to
two minutes and its output can vary between runs.

Usage:
    python3 -m scripts.build_comparison_report
"""

import json
from pathlib import Path

from agents.goal_based import GoalBasedAgent
from agents.learning_agent import LearningAgent
from agents.model_based_reflex import ModelBasedReflexAgent
from agents.simple_reflex import SimpleReflexAgent
from agents.utility_based import UtilityBasedAgent
from core.comparison import to_markdown
from core.evidence_check import check_evidence
from core.scenario_loader import load_scenario
from core.schema import AgentDecision

ROOT = Path(__file__).resolve().parent.parent
RESULTS = ROOT / "results"
SCENARIOS = ["A", "B", "C", "D", "E"]

ANALYSIS = {
    "A": (
        "All six agents identify the unit test regression. The differences are in confidence "
        "and specificity. The Utility-Based Agent is fully confident (1.0) because every signal "
        "points to one category, while the Learning Agent is lowest (0.83) because its confidence "
        "comes from the stored success rate of its chosen action, not from the evidence itself. "
        "The classical agents recommend a general 'compare the failing tests with the recent change' "
        "step. The LLM Agent is the most specific: because it read the change summary, it names "
        "`pricing/discount.py` as the file to fix."
    ),
    "B": (
        "All six agents identify the dependency failure. The reflex agents give a general instruction "
        "to resolve the dependency issue, while the Goal-Based, Utility-Based and Learning agents all "
        "converge on pinning an available package version: the Goal-Based Agent because its plan "
        "checked the package versions, the Utility-Based Agent because pinning has high impact at low "
        "cost, and the Learning Agent because pinning has the best past success rate. The LLM Agent "
        "did not use native tool calls here, so it selected tools through structured output instead; "
        "it then cited the exact `numpy==3.0.1` error lines and named numpy in its recommendation."
    ),
    "C": (
        "All six agents identify the post-deployment health failure, but they split on the action. "
        "The Utility-Based and Learning agents recommend rolling back the configuration change: "
        "rollback scores highest on utility once the category is certain, and it has the best past "
        "success rate (0.73). The reflex agents and the Goal-Based Agent recommend investigating the "
        "configuration and health checks first. The LLM Agent connects the failing readiness probe "
        "('database connection pool unavailable') to the recent database configuration change, which "
        "is the most direct causal link of the six."
    ),
    "D": (
        "All six agents correctly report no failure, which shows that none of them invents a problem "
        "when the evidence is clean. The recommended actions differ only in how cautious they are: "
        "approving the release (Goal-Based, Utility-Based, Learning) versus continuing to monitor "
        "(Simple Reflex) or checking production monitoring (LLM)."
    ),
    "E": (
        "This is the scenario designed to separate the agents. All six classify it as AMBIGUOUS, and "
        "confidence is lower here than in any other scenario (0.67 to 0.90). The Simple Reflex Agent "
        "reacts to the retry status in the current run (FLAKY_TEST_RULE); the Model-Based Reflex Agent "
        "additionally uses the test's failure history; both report 0.70 instead of the 0.95 they give "
        "in the clear-cut scenarios, because their flaky-test rules carry less certainty. The "
        "Goal-Based Agent reports 0.90, as in every scenario, because its plan still reached the goal "
        "once the retry evidence was found. The Utility-Based Agent is least confident (0.67): that is "
        "the probability of the ambiguous category, since two of the three evidence signals point to "
        "it and one points to a test failure. The Learning Agent reports 0.78 and recommends checking "
        "the flaky test for timing or network dependence, because that action has the best past "
        "success rate (6 successes out of 7 in the seed data); after four 'did not work' updates it "
        "switches to re-running the test (see `results/learning_feedback_demo.txt`). In the recorded "
        "run the LLM Agent cites `\"retry_passed\": true` as evidence, but its recommendation also "
        "mentions the recent documentation change, which the evidence does not link to the timeout; "
        "this is a known limitation of small local models."
    ),
}


CLASSICAL_AGENTS = [
    SimpleReflexAgent,
    ModelBasedReflexAgent,
    GoalBasedAgent,
    UtilityBasedAgent,
    LearningAgent,
]


def recorded_llm_decision(scenario_id: str) -> AgentDecision:
    data = json.loads((RESULTS / f"decisions_{scenario_id}.json").read_text())
    for item in data["decisions"]:
        if item["agent_name"] == "LLM Agent":
            return AgentDecision(**item)
    raise ValueError(f"No recorded LLM Agent decision for scenario {scenario_id}")


def decisions_for(scenario_id: str, scenario: dict) -> list[AgentDecision]:
    """Fresh classical decisions plus the recorded LLM decision, in UI order."""
    decisions = [agent().decide(scenario) for agent in CLASSICAL_AGENTS]
    decisions.append(recorded_llm_decision(scenario_id))
    return decisions


def main() -> None:
    runs = {}
    for scenario_id in SCENARIOS:
        scenario, expected = load_scenario(scenario_id)
        runs[scenario_id] = (scenario, expected, decisions_for(scenario_id, scenario))

    agents = [d.agent_name for d in runs["A"][2]]
    lines = [
        "# Comparison of Agent Decisions",
        "",
        "Generated by `scripts/build_comparison_report.py`. The five classical agents are "
        "deterministic and are re-run on the current code and experience data; the LLM Agent's "
        "decisions come from the recorded runs in `results/decisions_*.json`. All six agents "
        "received the same scenario data.",
        "",
        "## Summary: category per agent and scenario",
        "",
        "| Agent | " + " | ".join(f"{s} (expected {runs[s][1]})" for s in SCENARIOS) + " |",
        "| --- | " + " | ".join("---" for _ in SCENARIOS) + " |",
    ]

    correct = grounded = total = 0
    for index, agent in enumerate(agents):
        cells = []
        for scenario_id in SCENARIOS:
            scenario, expected, decisions = runs[scenario_id]
            decision = decisions[index]
            ok = decision.failure_category == expected
            correct += ok
            total += 1
            grounded += check_evidence(decision, scenario)["all_grounded"]
            cells.append(f"{decision.failure_category} {'✓' if ok else '✗'}")
        lines.append(f"| {agent} | " + " | ".join(cells) + " |")

    scores_e = [d.confidence for d in runs["E"][2] if d.confidence is not None]
    low_e, high_e = min(scores_e), max(scores_e)

    lines += [
        "",
        f"- Correct categories: **{correct} of {total}** decisions.",
        f"- Evidence fully grounded (every evidence item found in the data the agent received): "
        f"**{grounded} of {total}** decisions.",
        "",
        "## Overall: why the decisions differ",
        "",
        "Because the five scenarios each contain clear signals, the agents agree on the failure "
        "category in every scenario. Their decision mechanisms show up in three other places:",
        "",
        "1. **Confidence.** Rule-based agents report fixed confidence per rule, the Utility-Based Agent "
        "reports the probability of the winning category, the Learning Agent reports the past success "
        "rate of its chosen action, and the LLM reports its own estimate. Confidence is lowest in the "
        f"ambiguous scenario E ({low_e:.2f} to {high_e:.2f}), where the evidence is mixed.",
        "2. **Recommended next step.** Each mechanism ranks actions differently: rules map to a fixed "
        "action, the Goal-Based Agent follows its plan, the Utility-Based Agent trades benefit against "
        "cost and risk, and the Learning Agent follows past outcomes. This is clearest in scenario C, "
        "where some agents recommend a rollback and others an investigation.",
        "3. **Specificity.** The classical agents recommend general actions, while the LLM Agent reads "
        "the raw tool output and names concrete files, packages and errors (`pricing/discount.py`, "
        "`numpy==3.0.1`, the database connection pool).",
        "",
    ]

    for scenario_id in SCENARIOS:
        scenario, expected, decisions = runs[scenario_id]
        lines.append(to_markdown(decisions, scenario, f"Scenario {scenario_id}: {scenario['name']}"))
        lines += ["**Analysis**", "", ANALYSIS[scenario_id], "", "---", ""]

    output = RESULTS / "comparison_table.md"
    output.write_text("\n".join(lines))
    print(f"Wrote {output.relative_to(ROOT)}: {correct}/{total} correct, {grounded}/{total} grounded.")


if __name__ == "__main__":
    main()
