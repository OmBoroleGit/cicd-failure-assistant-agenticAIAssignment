"""Comparison of the six agents' decisions for one scenario.

Builds the comparison table, summarises how far the agents agree, and
explains each difference in terms of the agent's decision mechanism.
"""

from collections import Counter
from typing import Any

import pandas as pd

from core.evidence_check import check_evidence
from core.schema import AgentDecision

MECHANISMS = {
    "Simple Reflex Agent": "condition-action rules applied to the current run only, with no memory",
    "Model-Based Reflex Agent": "rules applied to an internal state built from run history and recent changes",
    "Goal-Based Agent": "a breadth-first search for the shortest diagnostic plan that reaches the goal",
    "Utility-Based Agent": "a utility score (P(resolves) x impact - time cost - risk) for each candidate step",
    "Learning Agent": "success and failure counts from past outcomes stored in its experience file",
    "LLM Agent": "a local language model that investigates with tools and cites the lines it read",
}


def _mechanism(agent_name: str) -> str:
    return MECHANISMS.get(agent_name, "its own decision procedure")


def _mechanism_detail(decision: AgentDecision) -> str:
    """A short, concrete description of what drove this particular decision."""
    details = decision.details or {}
    name = decision.agent_name

    if name == "Simple Reflex Agent" and details.get("rule_fired"):
        return f"rule {details['rule_fired']} fired on the current run"
    if name == "Model-Based Reflex Agent" and details.get("rule_fired"):
        return f"rule {details['rule_fired']} fired on its internal state"
    if name == "Goal-Based Agent" and details.get("plan"):
        return f"its shortest plan was {details['plan']}"
    if name == "Utility-Based Agent" and details.get("winner"):
        return f"the highest-utility step was '{details['winner']}'"
    if name == "Learning Agent" and details.get("chosen_action"):
        return f"'{details['chosen_action']}' had the best past success rate"
    if name == "LLM Agent" and details.get("tool_calls") is not None:
        tools = ", ".join(dict.fromkeys(call["tool"] for call in details["tool_calls"])) or "no tools"
        mode = details.get("tool_mode", "native")
        return f"it called {tools} ({mode} tool selection)"
    return _mechanism(name)


def build_table(decisions: list[AgentDecision], scenario: dict | None = None) -> pd.DataFrame:
    """One row per agent. Adds an evidence-grounding column when the scenario is given."""
    rows = []
    for decision in decisions:
        row = {
            "Agent": decision.agent_name,
            "Category": decision.failure_category,
            "Confidence": decision.confidence,
            "Next step": decision.next_step,
            "Evidence items": len(decision.evidence),
        }
        if scenario is not None:
            check = check_evidence(decision, scenario)
            row["Evidence grounded"] = f"{check['grounded_count']}/{check['total']}"
        rows.append(row)
    return pd.DataFrame(rows)


def agreement_summary(decisions: list[AgentDecision]) -> dict[str, Any]:
    """How many agents agree on the most common category, and who differs."""
    counts = Counter(decision.failure_category for decision in decisions)
    majority, majority_count = counts.most_common(1)[0] if counts else ("", 0)
    dissenting = {
        decision.agent_name: decision.failure_category
        for decision in decisions
        if decision.failure_category != majority
    }
    total = len(decisions)
    text = f"{majority_count} of {total} agents agree on {majority}."
    if dissenting:
        text += " Different: " + ", ".join(f"{name} ({cat})" for name, cat in dissenting.items()) + "."
    return {
        "majority_category": majority,
        "agreeing": majority_count,
        "total": total,
        "unanimous": majority_count == total,
        "dissenting": dissenting,
        "text": text,
    }


def explain_differences(decisions: list[AgentDecision]) -> list[str]:
    """Explain, point by point, why the agents' decisions differ."""
    if not decisions:
        return []

    summary = agreement_summary(decisions)
    points = [summary["text"]]

    # 1. Category disagreements.
    for decision in decisions:
        if decision.failure_category != summary["majority_category"]:
            points.append(
                f"{decision.agent_name} chose {decision.failure_category} instead of "
                f"{summary['majority_category']} because {_mechanism_detail(decision)}; "
                f"it decides using {_mechanism(decision.agent_name)}."
            )

    # 2. Confidence spread.
    scored = [d for d in decisions if d.confidence is not None]
    if len(scored) >= 2:
        high = max(scored, key=lambda d: d.confidence)
        low = min(scored, key=lambda d: d.confidence)
        if high.confidence - low.confidence >= 0.1:
            points.append(
                f"Confidence ranges from {low.confidence:.2f} ({low.agent_name}) to "
                f"{high.confidence:.2f} ({high.agent_name}). {low.agent_name} is less certain "
                f"because it relies on {_mechanism(low.agent_name)}, while {high.agent_name} "
                f"relies on {_mechanism(high.agent_name)}."
            )

    # 3. Different recommended next steps.
    distinct_steps = {d.next_step for d in decisions}
    if len(distinct_steps) > 1:
        points.append(
            f"The agents recommend {len(distinct_steps)} different next steps, because each "
            "mechanism ranks actions differently:"
        )
        for decision in decisions:
            step = decision.next_step.replace(". Human action required", "").rstrip(".")
            points.append(f"- {decision.agent_name}: \"{step}\" ({_mechanism_detail(decision)}).")

    return points


def to_markdown(decisions: list[AgentDecision], scenario: dict | None = None, title: str = "") -> str:
    """Comparison table plus explanation as Markdown, for export and results files."""
    table = build_table(decisions, scenario)
    table["Next step"] = table["Next step"].str.replace("|", "/", regex=False)

    header = "| " + " | ".join(table.columns) + " |"
    divider = "| " + " | ".join("---" for _ in table.columns) + " |"
    body = [
        "| " + " | ".join("" if pd.isna(value) else str(value) for value in row) + " |"
        for row in table.itertuples(index=False)
    ]

    parts = []
    if title:
        parts.append(f"## {title}\n")
    parts.append("\n".join([header, divider, *body]))
    parts.append("\n**Why the decisions differ**\n")
    parts.extend(
        point if point.startswith("- ") else f"\n{point}"
        for point in explain_differences(decisions)
    )
    return "\n".join(parts) + "\n"


def to_csv(decisions: list[AgentDecision], scenario: dict | None = None) -> str:
    """Comparison table as CSV text, for a download button."""
    return build_table(decisions, scenario).to_csv(index=False)
