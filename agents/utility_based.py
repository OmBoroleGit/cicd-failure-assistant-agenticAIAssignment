"""Utility-Based Agent.

Scores every candidate next step with
utility = P(resolves issue) x impact - time cost - risk.
P comes from how much evidence in the scenario supports each failure
category. The agent recommends the step with the highest utility.
"""

from agents.base import BaseAgent
from core.schema import AgentDecision

# Candidate next steps: which category each one fixes, and its scores.
# impact, time_cost and risk are hand-set on a 0-10 scale.
CANDIDATE_STEPS = [
    {
        "step": "Re-run the flaky test several times in a controlled way",
        "fixes": "AMBIGUOUS",
        "impact": 6, "time_cost": 1, "risk": 0.5,
    },
    {
        "step": "Compare the failing tests with the recent code change "
                "and fix it locally",
        "fixes": "TEST_FAILURE",
        "impact": 9, "time_cost": 4, "risk": 0.5,
    },
    {
        "step": "Pin an available version of the failing package "
                "in the requirements file",
        "fixes": "DEPENDENCY_FAILURE",
        "impact": 9, "time_cost": 2, "risk": 1,
    },
    {
        "step": "Roll back the recent configuration change "
                "and re-check the health endpoints",
        "fixes": "DEPLOYMENT_HEALTH_FAILURE",
        "impact": 9, "time_cost": 2, "risk": 2,
    },
    {
        "step": "Approve the release with no changes",
        "fixes": "NO_FAILURE",
        "impact": 5, "time_cost": 0, "risk": 1,
    },
    {
        "step": "Escalate for a full manual investigation",
        "fixes": "ANY",
        "impact": 9, "time_cost": 8, "risk": 0.5,
    },
]

# A full manual investigation almost always finds the cause.
ESCALATION_SUCCESS = 0.9

CATEGORIES = [
    "TEST_FAILURE",
    "DEPENDENCY_FAILURE",
    "DEPLOYMENT_HEALTH_FAILURE",
    "AMBIGUOUS",
    "NO_FAILURE",
]

CAUSES = {
    "TEST_FAILURE": "A recent source code change broke the failing unit tests.",
    "DEPENDENCY_FAILURE": "A required package version is unavailable or incompatible.",
    "DEPLOYMENT_HEALTH_FAILURE": "A recent configuration change made the deployed service unhealthy.",
    "AMBIGUOUS": "The failure is intermittent; most likely a flaky test.",
    "NO_FAILURE": "All stages, tests and health checks passed.",
}

CHECKLISTS = {
    "TEST_FAILURE": [
        "Failing tests pass locally.",
        "Full unit test suite passes in the pipeline.",
        "No new test failures appear.",
    ],
    "DEPENDENCY_FAILURE": [
        "Dependency installation stage passes.",
        "No 'No matching distribution' errors in the build log.",
        "Build and unit tests run and pass.",
    ],
    "DEPLOYMENT_HEALTH_FAILURE": [
        "/health returns HTTP 200.",
        "/ready returns HTTP 200.",
        "No ERROR lines after deployment in the log.",
    ],
    "AMBIGUOUS": [
        "The test passes on several repeated runs.",
        "No timeout errors in the test log.",
        "Pipeline is no longer marked unstable.",
    ],
    "NO_FAILURE": [
        "All pipeline stages passed.",
        "All tests passed.",
        "Health checks return HTTP 200.",
    ],
}

class UtilityBasedAgent(BaseAgent):
    """Recommends the next step with the highest expected utility."""

    name = "Utility-Based Agent"

    def decide(self, scenario: dict) -> AgentDecision:
        signals, evidence = self._collect_signals(scenario)

        # Step 1: turn evidence counts into probabilities.
        total = sum(len(found) for found in signals.values())
        probabilities = {
            category: round(len(signals[category]) / total, 2) if total else 0.0
            for category in CATEGORIES
        }

        # Step 2: score every candidate step.
        scores = []
        for candidate in CANDIDATE_STEPS:
            if candidate["fixes"] == "ANY":
                p = ESCALATION_SUCCESS
            else:
                p = probabilities[candidate["fixes"]]

            utility = p * candidate["impact"] - candidate["time_cost"] - candidate["risk"]
            scores.append({**candidate, "p_resolves": p, "utility": round(utility, 2)})

        scores.sort(key=lambda row: row["utility"], reverse=True)
        winner = scores[0]

        # Step 3: the winning step decides the category.
        if winner["fixes"] == "ANY":
            category = "AMBIGUOUS"
            confidence = 0.3
        else:
            category = winner["fixes"]
            confidence = probabilities[category]

        score_lines = "; ".join(
            f"{row['step']} = {row['utility']}" for row in scores
        )
        reasoning = (
            "Utility = P(resolves issue) x impact - time cost - risk. "
            f"Evidence gives these probabilities: {probabilities}. "
            f"Scores: {score_lines}. "
            f"Winner: '{winner['step']}' with utility {winner['utility']}."
        )

        return AgentDecision(
            agent_name=self.name,
            failure_category=category,
            evidence=evidence[category],
            likely_cause=CAUSES[category],
            next_step=f"{winner['step']}. Human action required",
            verification_checklist=CHECKLISTS[category],
            reasoning=reasoning,
            confidence=confidence,
            details={
                "probabilities": probabilities,
                "utility_scores": scores,
                "winner": winner["step"],
            },
        )

    @staticmethod
    def _collect_signals(scenario: dict) -> tuple[dict, dict]:
        """Count the signals that support each category, with evidence."""
        stages = scenario["pipeline_status"]["stages"]
        tests = scenario["test_results"]
        packages = scenario["dependencies"]["packages"]
        health = scenario["deployment_health"]
        history = scenario["run_history"]
        logs = scenario["build_logs"].splitlines()

        changed_files = [
            file for commit in scenario["recent_changes"] for file in commit["files"]
        ]
        code_files = [
            file for file in changed_files
            if file.endswith(".py") and not file.startswith("tests/")
        ]
        retried = [f for f in tests["failures"] if f.get("retry_passed")]

        signals = {category: [] for category in CATEGORIES}
        evidence = {category: [] for category in CATEGORIES}

        def add(category: str, signal: str, items: list[str]) -> None:
            signals[category].append(signal)
            evidence[category].extend(items)

        # Signals for TEST_FAILURE
        if tests["failed"] > 0:
            add("TEST_FAILURE", "tests failed",
                [f["message"] for f in tests["failures"]])
        if stages["unit_tests"]["status"] == "failed":
            add("TEST_FAILURE", "unit test stage failed",
                [line.strip() for line in logs if "FAILED" in line])
        if tests["failed"] > 0 and code_files:
            add("TEST_FAILURE", "source code changed", code_files)

        # Signals for DEPENDENCY_FAILURE
        broken = [p for p in packages if p["status"] in ("not_found", "conflict")]
        if broken:
            add("DEPENDENCY_FAILURE", "package unavailable",
                [p["name"] for p in broken])
        if stages["dependency_install"]["status"] == "failed":
            add("DEPENDENCY_FAILURE", "install stage failed",
                [line.strip() for line in logs if "ERROR" in line])
        if scenario["dependencies"]["lockfile_changed"]:
            add("DEPENDENCY_FAILURE", "dependency files changed",
                [f for f in changed_files if "requirements" in f or "lock" in f])

        # Signals for DEPLOYMENT_HEALTH_FAILURE
        if health["overall_status"] == "unhealthy":
            add("DEPLOYMENT_HEALTH_FAILURE", "deployment unhealthy",
                [c["detail"] for c in health["checks"] if not c["passed"]])
        server_errors = [line.strip() for line in logs if "HTTP 5" in line]
        if server_errors:
            add("DEPLOYMENT_HEALTH_FAILURE", "server error in logs", server_errors)
        config_files = [f for f in changed_files if f.startswith("config/")]
        if health["overall_status"] == "unhealthy" and config_files:
            add("DEPLOYMENT_HEALTH_FAILURE", "config changed", config_files)

        # Signals for AMBIGUOUS (flaky test)
        if retried:
            add("AMBIGUOUS", "test passed on retry",
                [f["test_name"] for f in retried])
        names = [f["test_name"] for f in tests["failures"]]
        failed_runs = [
            run["run_id"] for run in history
            if any(name in run["failed_tests"] for name in names)
        ]
        if len(failed_runs) >= 2:
            add("AMBIGUOUS", "test failed in several runs", failed_runs)

        # Signal for NO_FAILURE
        all_passed = all(s["status"] == "passed" for s in stages.values())
        if all_passed and health["overall_status"] == "healthy" and not tests["failures"]:
            add("NO_FAILURE", "everything passed",
                [line.strip() for line in logs if "successfully" in line])

        return signals, evidence
