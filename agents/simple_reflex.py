"""Simple Reflex Agent.

Uses condition-action rules based only on the current pipeline
percept. It does not maintain or use historical internal state.
"""

from agents.base import BaseAgent
from core.schema import AgentDecision

def find_log_lines(build_logs: str, keywords: list[str]) -> list[str]:
    """Return the build log lines that contain any of the keywords.

    The lines are copied exactly, so they can be checked against
    the scenario data.
    """
    return [
        line.strip()
        for line in build_logs.splitlines()
        if line.strip() and any(keyword in line for keyword in keywords)
    ]

class SimpleReflexAgent(BaseAgent):
    """Classifies CI/CD failures using fixed condition-action rules."""

    name = "Simple Reflex Agent"

    def decide(self, scenario: dict) -> AgentDecision:
        pipeline = scenario.get("pipeline_status", {})
        stages = pipeline.get("stages", {})
        tests = scenario.get("test_results", {})
        dependencies = scenario.get("dependencies", {})
        health = scenario.get("deployment_health", {})
        build_logs = scenario.get("build_logs", "")

        evidence = []
        failed_stages = []

        # Inspect current pipeline stages.
        if isinstance(stages, dict):
            for stage_name, stage_data in stages.items():
                if isinstance(stage_data, dict):
                    status = stage_data.get("status")
                else:
                    status = stage_data

                if status == "failed":
                    failed_stages.append(stage_name)

        # Rule 1: Dependency failure.
        packages = dependencies.get("packages", [])
        dependency_failures = []

        for package in packages:
            if package.get("status") in ("not_found", "conflict", "deprecated"):
                dependency_failures.append(package)
                package_name = package.get("name", "")
                log_lines = find_log_lines(build_logs, [package_name])
                evidence.extend(log_lines or [package_name])

        if dependency_failures:
            return AgentDecision(
                agent_name=self.name,
                failure_category="DEPENDENCY_FAILURE",
                evidence=evidence,
                likely_cause=(
                    "One or more required dependencies are missing, "
                    "conflicting, or deprecated."
                ),
                next_step=(
                    "Review the affected package versions and resolve "
                    "the dependency issue. Human action required"
                ),
                verification_checklist=[
                    "Check the required and resolved package versions.",
                    "Correct the dependency configuration.",
                    "Reinstall dependencies.",
                    "Rerun the pipeline.",
                ],
                reasoning=(
                    "The current dependency data contains a package "
                    "with a failing dependency status."
                ),
                confidence=0.95,
                details={
                    "rule_fired": "DEPENDENCY_FAILURE_RULE",
                    "failed_stages": failed_stages,
                    "failed_test_count": tests.get("failed", 0),
                },
            )

        # Rule 2: Flaky test or failure that passed on retry.
        failures = tests.get("failures", [])
        flaky_failures = [
            failure
            for failure in failures
            if failure.get("retry_passed", False)
        ]

        if flaky_failures:
            for failure in flaky_failures:
                test_name = (
                    failure.get("name")
                    or failure.get("test")
                    or failure.get("test_name")
                    or "Unknown"
                )

                log_lines = find_log_lines(build_logs, [test_name])
                evidence.extend(log_lines or [test_name])

            return AgentDecision(
                agent_name=self.name,
                failure_category="AMBIGUOUS",
                evidence=evidence,
                likely_cause=(
                    "A test failed initially but passed on retry, "
                    "indicating a possible intermittent failure."
                ),
                next_step=(
                    "Investigate the intermittent test and repeat the "
                    "pipeline run to confirm stability. Human action required"
                ),
                verification_checklist=[
                    "Inspect the test failure and retry logs.",
                    "Repeat the test several times.",
                    "Check for timing or environment-related instability.",
                ],
                reasoning=(
                    "The current test results show a failure that passed "
                    "on retry, so the pipeline result is potentially flaky."
                ),
                confidence=0.70,
                details={
                    "rule_fired": "FLAKY_TEST_RULE",
                    "failed_stages": failed_stages,
                    "failed_test_count": tests.get("failed", 0),
                },
            )

        # Rule 3: Ordinary test failure.
        failed_test_count = tests.get("failed", 0)

        if failed_test_count > 0 or failed_stages:
            evidence.extend(
                find_log_lines(build_logs, ["FAILED", "ERROR"])
            )

            return AgentDecision(
                agent_name=self.name,
                failure_category="TEST_FAILURE",
                evidence=evidence,
                likely_cause=(
                    "One or more automated tests or pipeline stages failed."
                ),
                next_step=(
                    "Inspect the failed tests and related code changes, "
                    "then correct the underlying issue. Human action required"
                ),
                verification_checklist=[
                    "Inspect the failed test cases.",
                    "Review recent code changes.",
                    "Apply the required correction.",
                    "Rerun the test suite and pipeline.",
                ],
                reasoning=(
                    "The current pipeline percept reports failed tests "
                    "or a failed pipeline stage."
                ),
                confidence=0.95,
                details={
                    "rule_fired": "TEST_FAILURE_RULE",
                    "failed_stages": failed_stages,
                    "failed_test_count": failed_test_count,
                },
            )

        # Rule 4: Deployment health failure.
        health_checks = health.get("checks", [])
        unhealthy_checks = [
            check
            for check in health_checks
            if check.get("status") in ("failed", "unhealthy")
            or check.get("status_code") in (500, 502, 503, 504)
        ]

        if health.get("overall_status") == "unhealthy" or unhealthy_checks:
            for check in unhealthy_checks:
                evidence.append(check.get("detail", check.get("name", "")))

            evidence.extend(find_log_lines(build_logs, ["ERROR"]))

            return AgentDecision(
                agent_name=self.name,
                failure_category="DEPLOYMENT_HEALTH_FAILURE",
                evidence=evidence,
                likely_cause=(
                    "The deployment is unhealthy even though the build "
                    "and test stages did not report a failure."
                ),
                next_step=(
                    "Inspect the unhealthy deployment checks and service "
                    "logs before considering another deployment. "
                    "Human action required"
                ),
                verification_checklist=[
                    "Inspect failed health-check endpoints.",
                    "Review application and service logs.",
                    "Check dependent services.",
                    "Rerun health checks after the correction.",
                ],
                reasoning=(
                    "The current deployment health data reports an "
                    "unhealthy service or failed health check."
                ),
                confidence=0.95,
                details={
                    "rule_fired": "DEPLOYMENT_HEALTH_FAILURE_RULE",
                    "failed_stages": failed_stages,
                    "failed_test_count": failed_test_count,
                },
            )

        # Rule 5: No failure detected.
        evidence.extend(find_log_lines(build_logs, ["successfully"]))

        return AgentDecision(
            agent_name=self.name,
            failure_category="NO_FAILURE",
            evidence=evidence,
            likely_cause="No failure is indicated by the current pipeline data.",
            next_step=(
                "Continue monitoring the pipeline and deployment health. "
                "Human action required"
            ),
            verification_checklist=[
                "Confirm all pipeline stages passed.",
                "Confirm automated tests passed.",
                "Confirm dependencies are resolved.",
                "Confirm deployment health checks are healthy.",
            ],
            reasoning=(
                "No condition-action rule for dependency, flaky test, "
                "test, or deployment failure was triggered."
            ),
            confidence=0.95,
            details={
                "rule_fired": "NO_FAILURE_RULE",
                "failed_stages": failed_stages,
                "failed_test_count": failed_test_count,
            },
        )
