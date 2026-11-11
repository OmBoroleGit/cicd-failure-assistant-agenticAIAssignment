
import json
from pathlib import Path


SCENARIO_DIR = Path(__file__).resolve().parent.parent / "data" / "scenarios"

SCENARIO_FILES = {
    "A": "scenario_a_unit_tests.json",
    "B": "scenario_b_dependency.json",
    "C": "scenario_c_deployment.json",
    "D": "scenario_d_normal.json",
    "E": "scenario_e_ambiguous.json",
}


def load_scenario(scenario_id: str) -> tuple[dict, str]:
    """
    Load a scenario and separate its expected category.

    Returns:
        A tuple containing:
        - Scenario data without expected_category.
        - Expected category for testing and evaluation only.
    """
    scenario_id = scenario_id.upper()

    if scenario_id not in SCENARIO_FILES:
        raise ValueError(
            f"Unknown scenario ID: {scenario_id}. "
            f"Available scenarios: {list(SCENARIO_FILES)}"
        )

    file_path = SCENARIO_DIR / SCENARIO_FILES[scenario_id]

    with file_path.open("r", encoding="utf-8") as file:
        data = json.load(file)

    expected_category = data.pop("expected_category", None)

    if expected_category is None:
        raise ValueError(
            f"Scenario {scenario_id} is missing expected_category"
        )

    return data, expected_category
