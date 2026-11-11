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