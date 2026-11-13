"""Read-only tools that expose the selected scenario to the LLM agent.

Every tool returns a JSON string built from the same scenario dictionary
that the classical agents receive. No tool modifies data, changes code,
or triggers a deployment.
"""

import copy
import json
from typing import Any

from langchain_core.tools import tool

_current_scenario: dict[str, Any] = {}


def set_scenario(scenario: dict[str, Any]) -> None:
    """Load the scenario that the tools will read from."""
    global _current_scenario
    _current_scenario = copy.deepcopy(scenario)


def _to_json(data: Any) -> str:
    return json.dumps(data, indent=2, ensure_ascii=False)


@tool
def get_pipeline_status() -> str:
    """Get the pipeline run status: stage results, deployment health checks and recent run history."""
    return _to_json(
        {
            "pipeline_status": _current_scenario.get("pipeline_status", {}),
            "deployment_health": _current_scenario.get("deployment_health", {}),
            "run_history": _current_scenario.get("run_history", []),
        }
    )


@tool
def read_build_logs() -> str:
    """Read the raw build and test log text of the current pipeline run."""
    return _current_scenario.get("build_logs", "")


@tool
def get_test_results() -> str:
    """Get unit test totals and the list of failed tests, including retry results."""
    return _to_json(_current_scenario.get("test_results", {}))


@tool
def get_recent_change_summary() -> str:
    """Get the recent commits since the last successful run: commit id, files changed and message."""
    return _to_json(_current_scenario.get("recent_changes", []))


@tool
def get_dependency_info() -> str:
    """Get required and resolved package versions and their install status."""
    return _to_json(_current_scenario.get("dependencies", {}))


ALL_TOOLS = [
    get_pipeline_status,
    read_build_logs,
    get_test_results,
    get_recent_change_summary,
    get_dependency_info,
]

TOOLS_BY_NAME = {t.name: t for t in ALL_TOOLS}
