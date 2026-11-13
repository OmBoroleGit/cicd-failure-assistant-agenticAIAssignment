## 1. System Architecture

The Intelligent CI/CD Pipeline Failure Assistant is a Python-based diagnostic system designed to analyse CI/CD pipeline failures and provide evidence-based recommendations.

The system uses six agents:
- Simple Reflex Agent
- Model-Based Reflex Agent
- Goal-Based Agent
- Utility-Based Agent
- Learning Agent
- LLM-Based Agent

All agents receive the same selected scenario data and produce a structured diagnostic decision. The system compares their outputs to help users understand different approaches to pipeline failure diagnosis.

### Shared Architecture Components

**Scenario Loader (`core/scenario_loader.py`)**

Loads scenario data from the JSON files stored in `data/scenarios/`. It separates the expected failure category from the scenario before passing the scenario to the agents. This prevents agents from accessing the ground-truth answer during diagnosis.

**Shared Decision Schema (`core/schema.py`)**

All agents use a common `AgentDecision` data structure containing:

- `agent_name`: Name of the agent.
- `failure_category`: Predicted failure category.
- `evidence`: Evidence supporting the decision.
- `likely_cause`: Probable explanation of the failure.
- `next_step`: Recommended action.
- `verification_checklist`: Steps to verify the resolution.
- `reasoning`: Explanation of the agent's decision.
- `confidence`: Confidence estimate between 0 and 1.
- `details`: Additional diagnostic information.

**Base Agent (`agents/base.py`)**

Defines a common abstract agent interface. Each agent implements the `decide(scenario)` method, ensuring consistent interaction across the system.

**Runner (`core/runner.py`)**

Provides a common execution entry point for running the agents against a selected scenario and collecting their decisions.

### System Workflow

1. The user selects a CI/CD scenario.
2. The scenario loader reads the corresponding JSON file.
3. The expected failure category is kept separate from the scenario data.
4. The agents independently analyse the same scenario.
5. Each agent returns a structured `AgentDecision`.
6. The system can compare the decisions and present the diagnostic results.
7. Recommendations require human action; the assistant does not automatically modify code or deploy changes.

---

## 2. Scenario Design

Five scenarios were created to evaluate the diagnostic capabilities of the agents. They cover normal pipeline execution, common failures, deployment issues, and ambiguous situations.

| Scenario | Description | Expected Category |
|---|---|---|
| A | Unit tests fail after a discount-related code change. | `TEST_FAILURE` |
| B | Dependency installation fails because a required NumPy version is unavailable. | `DEPENDENCY_FAILURE` |
| C | Build, tests, and deployment stages pass, but deployment health checks return HTTP 503. | `DEPLOYMENT_HEALTH_FAILURE` |
| D | All pipeline stages, tests, dependencies, and deployment health checks pass. | `NO_FAILURE` |
| E | A test initially fails but passes on retry, indicating possible intermittent behaviour. | `AMBIGUOUS` |

### Scenario Design Considerations

Each scenario contains structured information such as:

- Pipeline status and stage durations.
- Build logs.
- Test results and failure details.
- Dependency information.
- Recent code changes.
- Deployment health checks.
- Historical pipeline runs.

The scenarios are designed to test both straightforward and less certain diagnostic situations.

The `expected_category` field is used for evaluation only. It is removed by the scenario loader before the scenario is provided to an agent.

---

## 3. Simple Reflex Agent

**Implementation:** `agents/simple_reflex.py`

The Simple Reflex Agent uses a condition-action approach. It analyses the current pipeline observations and applies predefined rules to determine the failure category.

It does not maintain internal historical state or use previous pipeline runs to make its decision.

### Rule-Based Decision Mechanism

The agent follows these conditions:

1. **Dependency Failure:** Checks whether any package has a dependency status of `not_found`, `conflict`, or `deprecated`.
2. **Ambiguous Failure:** Checks whether a test failed initially but passed on retry.
3. **Test Failure:** Checks whether automated tests or pipeline stages have failed.
4. **Deployment Health Failure:** Checks whether deployment health is unhealthy or health checks have failed.
5. **No Failure:** If none of the failure conditions are triggered, the agent classifies the pipeline as healthy.

The rules use a fixed priority order so that the agent returns one classification for each scenario.

### Decision Output

The agent returns:
- Predicted failure category.
- Evidence from current pipeline observations.
- Likely cause.
- Recommended next step.
- Verification checklist.
- Reasoning and confidence estimate.
- Rule identifier in the `details` field.

### Characteristics

- Uses current observations only.
- Applies predefined condition-action rules.
- Does not maintain historical memory.
- Produces predictable and explainable decisions.
- Is suitable for straightforward pipeline failures.

---

## 4. Model-Based Reflex Agent

**Implementation:** `agents/model_based_reflex.py`

The Model-Based Reflex Agent extends the reflex approach by maintaining an internal representation of the pipeline's state.

Unlike the Simple Reflex Agent, it considers historical information and recent changes in addition to current pipeline observations.

### Internal State

The agent derives internal state information from:

- Failed pipeline stages.
- Previous successful pipeline runs.
- Recent changed files.
- Historical failed tests.
- Tests that failed but passed on retry.
- Repeated test failures.
- Unstable pipeline runs.
- Dependency lockfile changes.

This information helps the agent distinguish recurring problems from isolated failures.

### Decision Mechanism

The agent applies rules using both current and historical information:

1. **Dependency History Rule:** Detects dependency-related problems using package status and dependency configuration.
2. **Deployment History Rule:** Identifies unhealthy deployment checks.
3. **Flaky History Rule:** Identifies intermittent or repeated failures and unstable runs.
4. **
## 5. Goal-Based Agent

**Implementation:** `agents/goal_based.py`

The Goal-Based Agent works towards a fixed goal: **identify the root cause with enough evidence**. Instead of reacting to a single rule, it plans which diagnostic checks to perform and stops as soon as the collected facts prove one failure category.

### Diagnostic Actions

Each action reads one part of the scenario. An action can only run when its preconditions are already known.

| Action | Precondition | Facts it can add |
|---|---|---|
| `check_pipeline_status` | None | `pipeline_checked`, `test_stage_failed`, `install_stage_failed`, `all_stages_passed` |
| `read_build_logs` | `pipeline_checked` | `dependency_error_in_logs` |
| `get_test_results` | `pipeline_checked` | `tests_checked`, `tests_failed`, `test_passed_on_retry`, `all_tests_passed` |
| `check_dependencies` | `pipeline_checked` | `dependency_broken` |
| `get_recent_changes` | `pipeline_checked` | `source_code_changed`, `config_changed` |
| `check_deployment_health` | `pipeline_checked` | `deployment_unhealthy`, `deployment_healthy` |
| `review_run_history` | `tests_checked` | `test_failed_before` |

### Goal Conditions

A category is proven when all of its facts are known.

| Category | Facts required |
|---|---|
| `DEPENDENCY_FAILURE` | `install_stage_failed`, `dependency_error_in_logs`, `dependency_broken` |
| `TEST_FAILURE` | `test_stage_failed`, `tests_failed`, `source_code_changed` |
| `DEPLOYMENT_HEALTH_FAILURE` | `all_stages_passed`, `deployment_unhealthy`, `config_changed` |
| `AMBIGUOUS` | `test_passed_on_retry`, `test_failed_before` |
| `NO_FAILURE` | `all_stages_passed`, `all_tests_passed`, `deployment_healthy` |

### Decision Mechanism

1. The agent starts with no facts.
2. It uses **breadth-first search (BFS)**: it tries all one-step plans first, then two-step plans, and so on.
3. After each plan, it checks whether the facts collected satisfy any goal condition.
4. The first plan that reaches a goal is the **shortest plan** that proves the root cause.
5. The proven category decides the likely cause, next step and verification checklist.
6. If no plan reaches a goal, the agent returns `AMBIGUOUS` and recommends a manual investigation.

### Plans Found per Scenario

| Scenario | Plan found | Plans explored | Category |
|---|---|---|---|
| A | check_pipeline_status → get_test_results → get_recent_changes | 13 | `TEST_FAILURE` |
| B | check_pipeline_status → read_build_logs → check_dependencies | 9 | `DEPENDENCY_FAILURE` |
| C | check_pipeline_status → get_recent_changes → check_deployment_health | 18 | `DEPLOYMENT_HEALTH_FAILURE` |
| D | check_pipeline_status → get_test_results → check_deployment_health | 14 | `NO_FAILURE` |
| E | check_pipeline_status → get_test_results → review_run_history | 15 | `AMBIGUOUS` |

### Decision Output

The agent returns the shared `AgentDecision`. The `details` field contains:
- `goal`: the goal the agent was searching for.
- `plan`: the ordered list of diagnostic actions.
- `facts_found`: the facts collected by the plan.
- `plans_explored`: how many plans the search examined.

Confidence is `0.9` when a plan reaches the goal and `0.3` when no plan does.

### Characteristics

- Plans before deciding, rather than reacting to one observation.
- Uses only the evidence gathered by the actions in its plan.
- Always finds the shortest plan, because BFS checks shorter plans first.
- Makes its reasoning visible through the plan and the facts found.

---

## 6. Utility-Based Agent

**Implementation:** `agents/utility_based.py`

The Utility-Based Agent does not just ask "what went wrong?" but "which next step is worth taking?". It scores every candidate next step and recommends the one with the highest utility.

### Utility Formula

**utility = P(resolves issue) × impact − time cost − risk**

- **P(resolves issue):** how likely the step is to fix the problem, based on the evidence in the scenario.
- **Impact:** how much the step helps if it works (0–10).
- **Time cost:** how much effort the step takes (0–10).
- **Risk:** how likely the step is to cause new problems (0–10).

Impact, time cost and risk are hand-set values.

### Candidate Steps

| Candidate step | Fixes category | Impact | Time cost | Risk |
|---|---|---|---|---|
| Re-run the flaky test several times in a controlled way | `AMBIGUOUS` | 6 | 1 | 0.5 |
| Compare the failing tests with the recent code change and fix it locally | `TEST_FAILURE` | 9 | 4 | 0.5 |
| Pin an available version of the failing package in the requirements file | `DEPENDENCY_FAILURE` | 9 | 2 | 1 |
| Roll back the recent configuration change and re-check the health endpoints | `DEPLOYMENT_HEALTH_FAILURE` | 9 | 2 | 2 |
| Approve the release with no changes | `NO_FAILURE` | 5 | 0 | 1 |
| Escalate for a full manual investigation | Any | 9 | 8 | 0.5 |

### Decision Mechanism

1. **Collect signals.** The agent counts the evidence signals that support each category, for example "tests failed", "install stage failed", "deployment unhealthy" or "test passed on retry".
2. **Turn signals into probabilities.** P for a category = signals for that category ÷ all signals found.
3. **Score every candidate step.** Each step uses the probability of the category it fixes. Escalation uses a fixed P of 0.9, because a full manual investigation almost always finds the cause.
4. **Pick the winner.** The step with the highest utility is recommended, and its category becomes the decision.

### Worked Example: Scenario E

The evidence gives one `TEST_FAILURE` signal (the unit test stage failed) and two `AMBIGUOUS` signals (the test passed on retry, and it also failed in earlier runs). So P(`TEST_FAILURE`) = 0.33 and P(`AMBIGUOUS`) = 0.67.

| Candidate step | P | Utility |
|---|---|---|
| **Re-run the flaky test several times in a controlled way** | 0.67 | **2.52** (winner) |
| Escalate for a full manual investigation | 0.90 | −0.40 |
| Approve the release with no changes | 0.00 | −1.00 |
| Compare the failing tests with the recent code change and fix it locally | 0.33 | −1.53 |
| Pin an available version of the failing package in the requirements file | 0.00 | −3.00 |
| Roll back the recent configuration change and re-check the health endpoints | 0.00 | −4.00 |

The cheap, low-risk re-run wins over the expensive manual investigation, even though the investigation is more likely to succeed.

In scenarios A–D, all signals point to one category, so that category has P = 1.0 and its matching step wins.

### Decision Output

The agent returns the shared `AgentDecision`. The `details` field contains:
- `probabilities`: P for each category.
- `utility_scores`: the full score table for all candidate steps.
- `winner`: the recommended step.

Confidence is the probability of the winning category, or `0.3` if escalation wins.

### Characteristics

- Weighs benefit against cost and risk instead of only diagnosing.
- Can prefer a cheaper step over a more certain but costly one.
- Shows every option's score, so the choice can be checked.
- Depends on hand-set impact, cost and risk values.

---

## 7. Learning Agent

**Implementation:** `agents/learning_agent.py`
**Experience data:** `data/experience.json` (seed copy: `data/experience_seed.json`)

The Learning Agent chooses the next step that has worked best in the past, and it improves as feedback is recorded.

### Experience Data

For each failure category, `experience.json` stores possible actions and how often each one worked (`successes`) or did not work (`failures`). The file is seeded with starting counts so that the first run already has history.

### Decision Mechanism

1. **Detect the category** using simple checks on the scenario, in this order: broken dependency → unhealthy deployment → test passed on retry → failed tests → no failure.
2. **Score every stored action** for that category using the smoothed success rate:

   **rate = (successes + 1) ÷ (successes + failures + 2)**

   The "+1" and "+2" stop the agent from trusting very small samples too much. An action with 1 success out of 1 try scores 0.67, not 100%, and an untried action starts at 0.5.
3. **Choose the action with the highest rate.**
4. **Explain the choice** by listing the counts and rates behind it, and the most recent feedback for the category.

### Choices with the Seed Data

| Scenario | Category | Chosen action | Rate |
|---|---|---|---|
| A | `TEST_FAILURE` | Compare the failing tests with the recent code change and fix it locally (9 of 10) | 0.83 |
| B | `DEPENDENCY_FAILURE` | Pin an available version of the failing package in the requirements file (8 of 9) | 0.82 |
| C | `DEPLOYMENT_HEALTH_FAILURE` | Roll back the recent configuration change (7 of 9) | 0.73 |
| D | `NO_FAILURE` | Approve the release with no changes (10 of 10) | 0.92 |
| E | `AMBIGUOUS` | Check the flaky test for timing or network dependence (6 of 7) | 0.78 |

### Learning from Feedback

- `update(category, action, success)` adds one success or one failure to the action's counts, saves the file and records the rate before and after the change in `last_update`.
- The next decision reads the updated counts, so feedback changes future choices.
- `reset_experience()` copies `experience_seed.json` back over `experience.json`, so demos and screenshots start from the same counts.

**Example (scenario E):** after four "did not work" updates for "Check the flaky test for timing or network dependence", its counts become 6 successes and 5 failures, and its rate falls from 0.78 to 0.54. "Re-run the flaky test several times in a controlled way" (0.56) now has the highest rate, so the agent switches to it.

### Decision Output

The agent returns the shared `AgentDecision`. The `details` field contains:
- `experience_counts`: successes and failures for each action in the category.
- `success_rates`: the smoothed rate for each action.
- `chosen_action`: the recommended action.
- `last_update`: the most recent feedback and how it changed the rate.

Confidence is the smoothed success rate of the chosen action.

### Characteristics

- Improves its choices from recorded outcomes rather than fixed rules.
- Shows the counts behind every choice.
- Learns which action to take; the category itself comes from simple checks.
- Starts from simulated seed counts, which are replaced by real feedback over time.
