from collections import Counter

from agents.base import BaseAgent
from core.schema import AgentDecision

class ModelBasedReflexAgent(BaseAgent):
    """
    Builds an internal representation of pipeline state from current
    observations, recent changes and historical runs.
    Uses that state to apply condition-action rules and identify
    failures that require historical context.
    """

    name = "Model-Based Reflex Agent"

    def decide(self, scenario: dict) -> AgentDecision:
        stages = scenario["pipeline_status"]["stages"]
        test_results = scenario["test_results"]
        dependencies = scenario["dependencies"]
        history = scenario["run_history"]
        changes = scenario["recent_changes"]
        health = scenario["deployment_health"]

        # Build the internal world state.
        failed_stages = [
            name for name, data in stages.items()
            if data["status"] == "failed"
        ]

        changed_files = [
            file
            for commit in changes
            for file in commit["files"]
        ]

        historical_failures = [
            test
            for run in history
            for test in run.get("failed_tests", [])
        ]

        failure_counts = Counter(historical_failures)

        flaky_tests = [
            failure["test_name"]
            for failure in test_results["failures"]
            if failure.get("retry_passed", False)
        ]

        repeated_failures = [
            test for test, count in failure_counts.items()
            if count > 1
        ]

        unstable_runs = [
            run["run_id"]
            for run in history
            if run["status"] == "unstable"
        ]

        successful_runs = [
            run["run_id"]
            for run in history
            if run["status"] == "passed"
        ]

        last_successful_run = (
            successful_runs[-1] if successful_runs else None
        )

        internal_state = {
            "current_failed_stages": failed_stages,
            "last_successful_run": last_successful_run,
            "changed_files": changed_files,
            "historical_failed_tests": historical_failures,
            "flaky_tests": flaky_tests,
            "repeated_failures": repeated_failures,
            "unstable_runs": unstable_runs,
            "lockfile_changed": dependencies["lockfile_changed"]
        }

        evidence = []
        rule_fired = "NO_FAILURE_RULE"

        category = "NO_FAILURE"
        cause = (
            "Current and historical pipeline information "
            "shows no failure."
        )

        next_step = (
            "Review the successful pipeline history and approve the result "
            "if it meets release requirements. Human action required"
        )

        checklist = [
            "Confirm all pipeline stages completed successfully.",
            "Confirm all unit tests passed.",
            "Confirm deployment health checks are successful."
        ]

        dependency_problem = any(
            package["status"] in {"not_found", "conflict"}
            for package in dependencies["packages"]
        )

        # Rule 1: Dependency failure
        if "dependency_install" in failed_stages or dependency_problem:
            category = "DEPENDENCY_FAILURE"
            rule_fired = "DEPENDENCY_HISTORY_RULE"

            cause = (
                "Dependency installation failed. Recent dependency "
                "configuration changes may have introduced an "
                "unavailable or incompatible package version."
            )

            # CHANGED: show the changed dependency files, not the field name
            if dependencies["lockfile_changed"]:
                for commit in changes:
                    for file in commit["files"]:
                        if "requirements" in file or "lock" in file:
                            evidence.append(file)

            for package in dependencies["packages"]:
                if package["status"] in {"not_found", "conflict"}:
                    evidence.extend([
                        package["name"],
                        package["required_version"],
                        package["status"]
                    ])

            # CHANGED: show the real ERROR log lines, not the stage name
            if "dependency_install" in failed_stages:
                evidence.extend(
                    line.strip()
                    for line in scenario["build_logs"].splitlines()
                    if "ERROR" in line
                )

            next_step = (
                "Ask the project maintainer to review recent dependency "
                "changes, verify package versions and correct the lockfile. "
                "Human action required"
            )

            checklist = [
                "Identify the dependency causing installation failure.",
                "Review recent requirements and lockfile changes.",
                "Verify package compatibility and availability.",
                "Rerun installation, build and tests."
            ]

        # Rule 2: Deployment health failure
        elif health["overall_status"] == "unhealthy":
            category = "DEPLOYMENT_HEALTH_FAILURE"
            rule_fired = "DEPLOYMENT_HISTORY_RULE"

            cause = (
                "Build and test results must be distinguished from "
                "deployment health. The deployed application is unhealthy."
            )

            for check in health["checks"]:
                if not check["passed"]:
                    evidence.extend([
                        check["name"],
                        str(check["status_code"]),
                        check["detail"]
                    ])

            evidence.extend(changed_files)

            next_step = (
                "Ask the deployment owner to inspect recent configuration "
                "changes and investigate the failing health checks. "
                "Human action required"
            )

            checklist = [
                "Inspect failed deployment health endpoints.",
                "Review recently changed configuration files.",
                "Check database connectivity and connection pool settings.",
                "Rerun readiness and health checks after correction."
            ]

        # Rule 3: Flaky or intermittent test
        elif flaky_tests or repeated_failures or unstable_runs:
            category = "AMBIGUOUS"
            rule_fired = "FLAKY_HISTORY_RULE"

            cause = (
                "Test history indicates intermittent behavior. "
                "A failure followed by a successful retry or repeated "
                "historical failures requires further investigation."
            )

            evidence.extend(flaky_tests)
            evidence.extend(repeated_failures)
            evidence.extend(unstable_runs)

            for failure in test_results["failures"]:
                if failure["test_name"] in flaky_tests:
                    evidence.append(failure["message"])

            next_step = (
                "Ask the developer to investigate the intermittent test "
                "using controlled repeated runs and compare its historical "
                "failure pattern. Human action required"
            )

            checklist = [
                "Identify tests with repeated or intermittent failures.",
                "Run suspected flaky tests multiple times.",
                "Compare current results with previous pipeline runs.",
                "Inspect timing, network and shared-state dependencies.",
                "Confirm stable results before proceeding."
            ]

        # Rule 4: Ordinary unit test failure
        elif (
            test_results["failed"] > 0
            or "unit_tests" in failed_stages
        ):
            category = "TEST_FAILURE"
            rule_fired = "TEST_HISTORY_RULE"

            cause = (
                "The current pipeline contains failed unit tests. "
                "Recent source changes should be investigated "
                "to identify the likely regression."
            )

            for failure in test_results["failures"]:
                evidence.extend([
                    failure["test_name"],
                    failure["message"]
                ])

            evidence.extend(changed_files)

            if last_successful_run:
                evidence.append(last_successful_run)

            next_step = (
                "Ask the developer to compare the failing tests with "
                "the recent source changes and investigate the regression. "
                "Human action required"
            )

            checklist = [
                "Identify the failing test assertions.",
                "Compare recent source changes with the last successful run.",
                "Reproduce the failure locally.",
                "Review and apply the proposed correction.",
                "Rerun the complete unit test suite."
            ]

        else:
            evidence.extend(
                data["status"] for data in stages.values()
            )
            evidence.append(health["overall_status"])

        # Include historical context in the reasoning.
        reasoning = (
            "Updated internal state using current pipeline observations, "
            "recent changes and run history. "
            f"Last successful run: {last_successful_run}. "
            f"Changed files: {changed_files}. "
            f"Historical failed tests: {historical_failures}. "
            f"Flaky tests: {flaky_tests}. "
            f"Selected rule: {rule_fired}."
        )

        return AgentDecision(
            agent_name=self.name,
            failure_category=category,
            evidence=evidence,
            likely_cause=cause,
            next_step=next_step,
            verification_checklist=checklist,
            reasoning=reasoning,
            confidence=0.70 if category == "AMBIGUOUS" else 0.95,
            details={
                "internal_state": internal_state,
                "rule_fired": rule_fired
            }
        )
