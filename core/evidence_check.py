"""Evidence grounding check.

Verifies that every evidence item an agent cites actually appears in the data
it received: the scenario itself, or (for the LLM agent) the outputs of the
tools it called. An evidence item is grounded when, after normalising
whitespace, it is a substring of at least one of those source texts.
"""

import json
import re
from typing import Any

from core.schema import AgentDecision


def _normalise(text: str) -> str:
    return re.sub(r"\s+", " ", str(text)).strip()


def collect_source_texts(scenario: dict, decision: AgentDecision | None = None) -> list[str]:
    """Return every text the agent could have quoted as evidence.

    This includes every string and number in the scenario (searched
    recursively), each line of multi-line strings such as build logs, and
    the outputs of any tools the agent called.
    """
    texts: list[str] = []

    def walk(value: Any) -> None:
        if isinstance(value, dict):
            for key, item in value.items():
                texts.append(str(key))
                walk(item)
        elif isinstance(value, list):
            for item in value:
                walk(item)
        elif isinstance(value, bool) or value is None:
            texts.append(json.dumps(value))
        elif isinstance(value, (int, float)):
            texts.append(str(value))
        elif isinstance(value, str):
            texts.append(value)
            texts.extend(value.splitlines())

    walk(scenario)

    if decision is not None:
        for call in decision.details.get("tool_calls", []) or []:
            output = str(call.get("output", ""))
            texts.append(output)
            texts.extend(output.splitlines())

    return [_normalise(text) for text in texts if str(text).strip()]


def check_evidence(decision: AgentDecision, scenario: dict) -> dict[str, Any]:
    """Check whether each evidence item of a decision is grounded in the data.

    Returns:
        A dict with:
        - items: list of {"evidence": str, "grounded": bool}
        - grounded_count / total
        - grounded_ratio: 0.0 to 1.0 (1.0 when there is no evidence to check)
        - all_grounded: True when every item is grounded and at least one exists
    """
    sources = collect_source_texts(scenario, decision)

    items = []
    for evidence in decision.evidence:
        needle = _normalise(evidence)
        grounded = bool(needle) and any(needle in source for source in sources)
        items.append({"evidence": evidence, "grounded": grounded})

    total = len(items)
    grounded_count = sum(item["grounded"] for item in items)
    return {
        "agent_name": decision.agent_name,
        "items": items,
        "grounded_count": grounded_count,
        "total": total,
        "grounded_ratio": grounded_count / total if total else 1.0,
        "all_grounded": total > 0 and grounded_count == total,
    }
