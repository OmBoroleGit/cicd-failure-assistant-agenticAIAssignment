"""Learning Agent.

Picks the next step with the best past success rate, using
smoothed success rate = (successes + 1) / (successes + failures + 2)
from data/experience.json. update() records user feedback and saves it,
so the agent's future choices change with experience. reset_experience()
restores the seeded counts for repeatable demos.
"""

import json
import shutil
from pathlib import Path

from agents.base import BaseAgent
from agents.utility_based import CAUSES, CHECKLISTS
from core.schema import AgentDecision

EXPERIENCE_FILE = Path(__file__).resolve().parent.parent / "data" / "experience.json"
SEED_FILE = Path(__file__).resolve().parent.parent / "data" / "experience_seed.json"

def success_rate(counts: dict) -> float:
    """Smoothed success rate: (s + 1) / (s + f + 2)."""
    s = counts["successes"]
    f = counts["failures"]
    return round((s + 1) / (s + f + 2), 2)

class LearningAgent(BaseAgent):
    """Chooses the action that has worked best in the past."""

    name = "Learning Agent"

    def __init__(
        self,
        experience_path: Path = EXPERIENCE_FILE,
        seed_path: Path = SEED_FILE,
    ) -> None:
        self.experience_path = experience_path
        self.seed_path = seed_path

    def decide(self, scenario: dict) -> AgentDecision:
        category, evidence = self._detect_category(scenario)
        data = self._load()
        actions = data["experience"][category]

        # Score every known action for this category by its past success rate.
        rates = {action: success_rate(counts) for action, counts in actions.items()}
        best_action =max(rates, key=rates.get)

        count_lines = "; ".join(
            f"'{action}': {counts['successes']} of "
            f"{counts['successes'] + counts['failures']} successes "
            f"(rate {rates[action]})"
            for action, counts in actions.items()
        )

        reasoning = (
            f"Detected category {category}. "
            f"Stored experience for this category: {count_lines}. "
            f"Chose '{best_action}' because it has the best smoothed "
            "success rate (s+1)/(s+f+2). "
            f"{self._describe_last_update(data, category)}"
        )

        return AgentDecision(
            agent_name=self.name,
            failure_category=category,
            evidence=evidence,
            likely_cause=CAUSES[category],
            next_step=f"{best_action}. Human action required",
            verification_checklist=CHECKLISTS[category],
            reasoning=reasoning,
            confidence=rates[best_action],
            details={
                "experience_counts": actions,
                "success_rates": rates,
                "chosen_action": best_action,
                "last_update": data["last_update"],
            },
        )

    def update(self, category: str, action: str, success: bool) -> None:
        """Record feedback for one action and save it to disk."""
        data = self._load()
        counts = data["experience"][category].setdefault(
            action, {"successes": 0, "failures": 0}
        )
        rate_before = success_rate(counts)

        if success:
            counts["successes"] += 1
        else:
            counts["failures"] += 1

        data["last_update"] = {
            "category": category,
            "action": action,
            "success": success,
            "rate_before": rate_before,
            "rate_after": success_rate(counts),
        }
        self._save(data)

    def reset_experience(self) -> None:
        """Restore the experience file to the original seeded counts."""
        shutil.copyfile(self.seed_path, self.experience_path)

    def _load(self) -> dict:
        with self.experience_path.open("r", encoding="utf-8") as file:
            return json.load(file)

    def _save(self, data: dict) -> None:
        with self.experience_path.open("w", encoding="utf-8") as file:
            json.dump(data, file, indent=2)

    @staticmethod
    def _describe_last_update(data: dict, category: str) -> str:
        last = data["last_update"]
        if not last or last["category"] != category:
            return "No feedback recorded yet for this category."
        result = "worked" if last["success"] else "did not work"
        return (
            f"Last feedback: '{last['action']}' {result}, so its rate "
            f"moved from {last['rate_before']} to {last['rate_after']}."
        )

    @staticmethod
    def _detect_category(scenario: dict) -> tuple[str, list[str]]:
        """Simple checks to find the category; learning picks the action."""
        tests = scenario["test_results"]
        packages = scenario["dependencies"]["packages"]
        health = scenario["deployment_health"]
        logs = scenario["build_logs"].splitlines()

        broken = [p for p in packages if p["status"] in ("not_found", "conflict")]
        if broken:
            return "DEPENDENCY_FAILURE", [
                line.strip() for line in logs if "No matching distribution" in line
            ] or [p["name"] for p in broken]

        if health["overall_status"] == "unhealthy":
            return "DEPLOYMENT_HEALTH_FAILURE", [
                c["detail"] for c in health["checks"] if not c["passed"]
            ]

        retried = [f for f in tests["failures"] if f.get("retry_passed")]
        if retried:
            return "AMBIGUOUS", [f["test_name"] for f in retried] + [
                f["message"] for f in retried
            ]

        if tests["failed"] > 0:
            return "TEST_FAILURE", [f["message"] for f in tests["failures"]]

        return "NO_FAILURE", [line.strip() for line in logs if "successfully" in line]
