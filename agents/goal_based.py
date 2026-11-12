"""Goal-Based Agent.

Goal: identify the root cause with enough evidence. The agent searches
(breadth-first search) over diagnostic actions, each with preconditions
and effects, and picks the shortest plan that proves one failure category.
"""

from collections import deque

from agents.base import BaseAgent
from core.schema import AgentDecision


# Each diagnostic action: which facts must already be known (preconditions).
ACTIONS = {
    "check_pipeline_status": [],
    "read_build_logs": ["pipeline_checked"],
    "get_test_results": ["pipeline_checked"],
    "check_dependencies": ["pipeline_checked"],
    "get_recent_changes": ["pipeline_checked"],
    "check_deployment_health": ["pipeline_checked"],
    "review_run_history": ["tests_checked"],
}

# The goal: a category is proven when all of its facts are known.
GOALS = {
    "DEPENDENCY_FAILURE": [
        "install_stage_failed",
        "dependency_error_in_logs",
        "dependency_broken",
    ],
    "TEST_FAILURE": [
        "test_stage_failed",
        "tests_failed",
        "source_code_changed",
    ],
    "DEPLOYMENT_HEALTH_FAILURE": [
        "all_stages_passed",
        "deployment_unhealthy",
        "config_changed",
    ],
    "AMBIGUOUS": [
        "test_passed_on_retry",
        "test_failed_before",
    ],
    "NO_FAILURE": [
        "all_stages_passed",
        "all_tests_passed",
        "deployment_healthy",
    ],
}

# What to tell the human for each proven category.
OUTCOMES = {
    "DEPENDENCY_FAILURE": {
        "cause": "A required package version is unavailable or incompatible.",
        "next_step": (
            "Check the failing package version in the requirements file "
            "and pin an available version. Human action required"
        ),
        "checklist": [
            "Dependency installation stage passes.",
            "No 'No matching distribution' errors in the build log.",
            "Build and unit tests run and pass.",
        ],
    },
    "TEST_FAILURE": {
        "cause": "A recent source code change broke the failing unit tests.",
        "next_step": (
            "Review the recent source change against the failing tests "
            "and reproduce the failure locally. Human action required"
        ),
        "checklist": [
            "Failing tests pass locally.",
            "Full unit test suite passes in the pipeline.",
            "No new test failures appear.",
        ],
    },
    "DEPLOYMENT_HEALTH_FAILURE": {
        "cause": "A recent configuration change made the deployed service unhealthy.",
        "next_step": (
            "Review the recent configuration change and compare it with "
            "the last healthy release. Human action required"
        ),
        "checklist": [
            "/health returns HTTP 200.",
            "/ready returns HTTP 200.",
            "No ERROR lines after deployment in the log.",
        ],
    },
    "AMBIGUOUS": {
        "cause": "A test failed, passed on retry and has failed before: likely a flaky test.",
        "next_step": (
            "Re-run the flaky test several times in a controlled way "
            "before changing any code. Human action required"
        ),
        "checklist": [
            "The test passes on several repeated runs.",
            "No timeout errors in the test log.",
            "Pipeline is no longer marked unstable.",
        ],
    },
    "NO_FAILURE": {
        "cause": "All stages, tests and health checks passed.",
        "next_step": (
            "No fix needed; review and approve the release. "
            "Human action required"
        ),
        "checklist": [
            "All pipeline stages passed.",
            "All tests passed.",
            "Health checks return HTTP 200.",
        ],
    },
}


class GoalBasedAgent(BaseAgent):
    """Finds the shortest diagnostic plan that proves a root cause."""

    name = "Goal-Based Agent"

    def decide(self, scenario: dict) -> AgentDecision:
        plan, facts, evidence, category, explored = self._search(scenario)

        if category is None:
            return AgentDecision(
                agent_name=self.name,
                failure_category="AMBIGUOUS",
                evidence=[],
                likely_cause="No plan could prove a single root cause.",
                next_step=(
                    "Investigate the pipeline manually. Human action required"
                ),
                verification_checklist=[
                    "Root cause identified manually.",
                    "Pipeline passes after the fix.",
                    "Health checks pass after release.",
                ],
                reasoning=(
                    "Goal: identify the root cause with enough evidence. "
                    f"Breadth-first search explored {explored} plans "
                    "but none reached the goal."
                ),
                confidence=0.3,
                details={"goal": "root cause identified", "plan": []},
            )

        outcome = OUTCOMES[category]

        reasoning = (
            "Goal: identify the root cause with enough evidence. "
            f"Breadth-first search explored {explored} plans. "
            f"Shortest plan that reaches the goal: {' -> '.join(plan)}. "
            f"It proves {category} because these facts were found: "
            f"{', '.join(GOALS[category])}."
        )

        return AgentDecision(
            agent_name=self.name,
            failure_category=category,
            evidence=evidence,
            likely_cause=outcome["cause"],
            next_step=outcome["next_step"],
            verification_checklist=outcome["checklist"],
            reasoning=reasoning,
            confidence=0.9,
            details={
                "goal": "root cause identified with enough evidence",
                "plan": plan,
                "facts_found": sorted(facts),
                "plans_explored": explored,
            },
        )

    def _search(self, scenario: dict):
        """Breadth-first search: try short plans first, stop at the goal."""
        queue = deque([([], set(), [])])  # (plan, facts, evidence)
        seen = set()
        explored = 0

        while queue:
            plan, facts, evidence = queue.popleft()
            explored += 1

            category = self._goal_reached(facts)
            if category:
                return plan, facts, evidence, category, explored

            for action, needs in ACTIONS.items():
                if action in plan:
                    continue
                if not all(fact in facts for fact in needs):
                    continue

                new_plan = plan + [action]
                key = frozenset(new_plan)
                if key in seen:
                    continue
                seen.add(key)

                new_facts, new_evidence = self._do_action(action, scenario)
                queue.append((
                    new_plan,
                    facts | new_facts,
                    evidence + new_evidence,
                ))

        return [], set(), [], None, explored

    @staticmethod
    def _goal_reached(facts: set) -> str | None:
        """Return the first category whose facts are all known."""
        for category, needed in GOALS.items():
            if all(fact in facts for fact in needed):
                return category
        return None

    @staticmethod
    def _do_action(action: str, scenario: dict) -> tuple[set, list[str]]:
        """Run one diagnostic action: return new facts and evidence."""
        facts = set()
        evidence = []

        if action == "check_pipeline_status":
            facts.add("pipeline_checked")
            stages = scenario["pipeline_status"]["stages"]
            statuses = [stage["status"] for stage in stages.values()]
            if stages["unit_tests"]["status"] == "failed":
                facts.add("test_stage_failed")
            if stages["dependency_install"]["status"] == "failed":
                facts.add("install_stage_failed")
            if all(status == "passed" for status in statuses):
                facts.add("all_stages_passed")

        elif action == "read_build_logs":
            for line in scenario["build_logs"].splitlines():
                if "No matching distribution" in line:
                    facts.add("dependency_error_in_logs")
                    evidence.append(line.strip())

        elif action == "get_test_results":
            facts.add("tests_checked")
            tests = scenario["test_results"]
            retried = [f for f in tests["failures"] if f.get("retry_passed")]
            if tests["failed"] > 0:
                facts.add("tests_failed")
                for failure in tests["failures"]:
                    evidence.append(failure["message"])
            if retried:
                facts.add("test_passed_on_retry")
                for failure in retried:
                    evidence.append(failure["test_name"])
            if tests["failed"] == 0 and not retried:
                facts.add("all_tests_passed")

        elif action == "check_dependencies":
            for package in scenario["dependencies"]["packages"]:
                if package["status"] in ("not_found", "conflict"):
                    facts.add("dependency_broken")
                    evidence.append(package["name"])
                    evidence.append(package["required_version"])

        elif action == "get_recent_changes":
            for commit in scenario["recent_changes"]:
                for file in commit["files"]:
                    if file.startswith("config/"):
                        facts.add("config_changed")
                        evidence.append(file)
                    elif file.endswith(".py") and not file.startswith("tests/"):
                        facts.add("source_code_changed")
                        evidence.append(file)

        elif action == "check_deployment_health":
            health = scenario["deployment_health"]
            if health["overall_status"] == "unhealthy":
                facts.add("deployment_unhealthy")
                for check in health["checks"]:
                    if not check["passed"]:
                        evidence.append(check["detail"])
            if health["overall_status"] == "healthy":
                facts.add("deployment_healthy")
                for check in health["checks"]:
                    evidence.append(check["detail"])

        elif action == "review_run_history":
            failed_names = [
                f["test_name"] for f in scenario["test_results"]["failures"]
            ]
            for run in scenario["run_history"]:
                if any(name in run["failed_tests"] for name in failed_names):
                    facts.add("test_failed_before")
                    evidence.append(run["run_id"])

        return facts, evidence
