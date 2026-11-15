"""Streamlit interface for the shared CI/CD failure investigation agents.

Place this file in the repository root and run: python -m streamlit run app.py
Pipeline operations are read-only. Explicit feedback updates local experience.
"""

from __future__ import annotations

from collections import Counter
from datetime import datetime, timezone
from hashlib import sha256
from importlib import import_module
import json
import logging
import os
import threading
from typing import Any, Callable

import pandas as pd
import streamlit as st

from agents.learning_agent import LearningAgent
from core.runner import run_all_agents
from core.scenario_loader import SCENARIO_FILES, load_scenario
from core.schema import AgentDecision


LOGGER = logging.getLogger(__name__)
RESULTS_KEY = "pipeline_results"
NOTICE_KEY = "pipeline_notice"
CATEGORIES = {
    "TEST_FAILURE", "DEPENDENCY_FAILURE", "DEPLOYMENT_HEALTH_FAILURE",
    "NO_FAILURE", "AMBIGUOUS",
}
MECHANISMS = {
    "Simple Reflex": "Applies ordered condition-action rules to current observations.",
    "Model-Based Reflex": "Builds internal state from history and recent changes before applying rules.",
    "Goal-Based": "Searches diagnostic actions with BFS until its evidence goal is reached.",
    "Utility-Based": "Chooses the action with the highest estimated benefit minus cost and risk.",
    "Learning": "Chooses the highest smoothed success rate from stored outcome counts.",
    "LLM": "Selects read-only tools and interprets the evidence returned by those tools.",
}


@st.cache_resource
def operation_lock() -> Any:
    """Serialize app operations because pipeline tools share a global scenario."""
    return threading.RLock()


def optional_function(module_name: str, function_name: str) -> tuple[Callable | None, str]:
    """Allow the UI to run while optional shared modules are unfinished."""
    try:
        module = import_module(module_name)
        function = getattr(module, function_name, None)
        if callable(function):
            return function, ""
        return None, f"{module_name}.{function_name} is not implemented."
    except Exception as error:
        LOGGER.warning("Could not load %s: %s", module_name, error)
        return None, f"Could not load {module_name}: {error}"


def fingerprint(scenario: dict) -> str:
    payload = {
        "scenario": scenario,
        "model": os.getenv("OLLAMA_MODEL", "qwen3:4b"),
        "context": os.getenv("OLLAMA_NUM_CTX", "4096"),
    }
    return sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()


def validate_decisions(decisions: list[AgentDecision]) -> None:
    """Check the runner contract without treating an LLM fallback as success."""
    if not isinstance(decisions, list) or len(decisions) != 6:
        raise ValueError("run_all_agents() must return a list of six decisions.")
    if not all(isinstance(item, AgentDecision) for item in decisions):
        raise TypeError("Every runner result must be an AgentDecision.")
    if len({item.agent_name for item in decisions}) != 6:
        raise ValueError("The six agent names must be unique.")
    if any(item.failure_category not in CATEGORIES for item in decisions):
        raise ValueError("A decision contains an unsupported failure category.")


def is_learning(decision: AgentDecision) -> bool:
    return decision.agent_name == LearningAgent.name


def get_learning(decisions: list[AgentDecision]) -> AgentDecision:
    return next(decision for decision in decisions if is_learning(decision))


def refresh_learning() -> None:
    """Refresh cached learning decisions without rerunning the other agents."""
    learner = LearningAgent()
    for sid, entry in st.session_state[RESULTS_KEY].items():
        scenario, _ = load_scenario(sid)
        replacement = learner.decide(scenario)
        entry["decisions"] = [
            replacement if is_learning(item) else item for item in entry["decisions"]
        ]


def record_feedback(scenario_id: str, success: bool) -> None:
    """A callback records one outcome for the action currently displayed."""
    saved = False
    try:
        with operation_lock():
            entry = st.session_state[RESULTS_KEY][scenario_id]
            decision = get_learning(entry["decisions"])
            LearningAgent().update(
                decision.failure_category,
                decision.details["chosen_action"],
                success=success,
            )
            saved = True
            refresh_learning()
        st.session_state[NOTICE_KEY] = (
            "success", "Feedback saved. Learning counts and decisions refreshed; the LLM was not rerun."
        )
    except Exception as error:
        LOGGER.exception("Feedback processing failed")
        prefix = "Feedback was saved, but refresh failed" if saved else "Feedback was not saved"
        st.session_state[NOTICE_KEY] = ("error", f"{prefix}: {error}")


def reset_learning() -> None:
    try:
        with operation_lock():
            LearningAgent().reset_experience()
            refresh_learning()
        st.session_state[NOTICE_KEY] = ("success", "Seed experience restored. The LLM was not rerun.")
    except Exception as error:
        LOGGER.exception("Experience reset failed")
        st.session_state[NOTICE_KEY] = ("error", f"Could not complete the experience reset: {error}")


def string_values(value: Any) -> list[str]:
    """Extract original strings, including unescaped log lines, for matching."""
    if isinstance(value, str):
        return [value]
    if isinstance(value, dict):
        return [text for item in value.values() for text in string_values(item)]
    if isinstance(value, list):
        return [text for item in value for text in string_values(item)]
    return []


def evidence_report(decision: AgentDecision, scenario: dict, checker: Callable | None) -> dict:
    """Check literal presence, not whether a quotation proves the diagnosis.

    LLM quotations must occur in its recorded tool outputs. Classical quotations
    may occur anywhere in the shared scenario. The shared checker is also called
    when available; its original output is displayed without assuming its schema.
    """
    calls = decision.details.get("tool_calls", [])
    is_llm = "LLM" in decision.agent_name
    if is_llm:
        sources = [str(call.get("output", "")) for call in calls]
    else:
        sources = string_values(scenario) + [
            json.dumps(scenario, ensure_ascii=False),
            json.dumps(scenario, ensure_ascii=False, indent=2),
        ]
    items = [
        {"evidence": text, "found": bool(text.strip()) and any(text in src for src in sources)}
        for text in decision.evidence
    ]
    report = {"items": items, "verified": bool(items) and all(item["found"] for item in items)}
    if checker is not None:
        try:
            report["shared_checker"] = checker(decision, scenario)
        except Exception as error:
            report["shared_checker_error"] = str(error)
    return report


def evidence_label(decision: AgentDecision, report: dict) -> str:
    if decision.details.get("error"):
        return "Analysis unavailable"
    if not decision.evidence:
        return "No evidence provided"
    return "Literal evidence verified" if report["verified"] else "Evidence match failed"


def build_comparison(decisions: list[AgentDecision], reports: dict) -> pd.DataFrame:
    return pd.DataFrame([
        {
            "Agent": decision.agent_name,
            "Category": decision.failure_category,
            "Confidence": f"{decision.confidence:.0%}" if decision.confidence is not None else "Not estimated",
            "Next step": decision.next_step,
            "Evidence": evidence_label(decision, reports[decision.agent_name]),
            "Analysis": "Unavailable" if decision.details.get("error") else "Returned",
        }
        for decision in decisions
    ])


def markdown_table(table: pd.DataFrame) -> str:
    """Export Markdown without requiring the optional tabulate package."""
    def cell(value: Any) -> str:
        return str(value).replace("\\", "\\\\").replace("|", "\\|").replace("\n", " ")

    header = "| " + " | ".join(cell(col) for col in table.columns) + " |"
    divider = "| " + " | ".join("---" for _ in table.columns) + " |"
    rows = ["| " + " | ".join(cell(value) for value in row) + " |" for row in table.itertuples(index=False, name=None)]
    return "\n".join([header, divider, *rows])


def mechanism_for(decision: AgentDecision) -> str:
    for name, description in MECHANISMS.items():
        if name in decision.agent_name:
            return description
    return "See this agent's reasoning and mechanism details."


def render_differences(decisions: list[AgentDecision]) -> None:
    st.subheader("Why decisions differ")
    available = [item for item in decisions if not item.details.get("error")]
    categories = {item.failure_category for item in available}
    if len(categories) == 1 and available:
        st.write("Available agents agree on the category. Compare their recommended actions, evidence, and reasoning below.")
    elif len(categories) > 1:
        st.write("Available agents selected different categories. Their mechanisms weigh current signals, history, cost, and experience differently.")
    else:
        st.write("No completed analysis is available for comparison.")
    for decision in decisions:
        with st.expander(f"{decision.agent_name}: {decision.failure_category}"):
            st.write(mechanism_for(decision))
            st.write("**Selected action:**", decision.next_step)
            st.write("**Reasoning for this scenario:**", decision.reasoning)
            if decision.details.get("error"):
                st.error(str(decision.details["error"]))


def render_decision(decision: AgentDecision, report: dict) -> None:
    with st.container(border=True):
        st.subheader(decision.agent_name)
        st.write("**Failure category:**", decision.failure_category)
        if decision.confidence is not None:
            st.write("**Confidence:**", f"{decision.confidence:.0%}")
        label = evidence_label(decision, report)
        if decision.details.get("error"):
            st.error(str(decision.details["error"]))
        if report["verified"] and not decision.details.get("error"):
            st.success(label)
        else:
            st.warning(label)
        if "shared_checker_error" in report:
            st.warning("The shared evidence checker raised an error; see evidence details.")
        st.write("**Supporting evidence**")
        for item in report["items"]:
            st.caption("Matched" if item["found"] else "Not matched")
            st.code(item["evidence"], language=None)
        st.write("**Likely cause:**", decision.likely_cause or "Not provided")
        st.write("**Recommended next step:**", decision.next_step or "Not provided")
        st.write("**Post-fix verification checklist**")
        for item in decision.verification_checklist:
            st.write(f"- {item}")
        if not 3 <= len(decision.verification_checklist) <= 5:
            st.warning("The output contract requires 3–5 verification items.")
        st.write("**Reasoning:**", decision.reasoning or "Not provided")
        with st.expander("Mechanism and evidence-check details"):
            st.json(json.dumps({"mechanism": decision.details, "evidence_check": report}, default=str))


def render_learning(decision: AgentDecision, scenario_id: str) -> None:
    st.subheader("Learning feedback")
    st.caption("Record whether the recommended human action worked. Feedback changes local experience only. Label simulated feedback in your report.")
    st.write("**Current action:**", decision.details.get("chosen_action", "Not provided"))
    counts = decision.details.get("experience_counts", {})
    rates = decision.details.get("success_rates", {})
    rows = [{"Action": action, **values, "Smoothed success rate": rates.get(action)} for action, values in counts.items()]
    if rows:
        st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch")
    columns = st.columns(3)
    columns[0].button("Worked", key=f"worked_{scenario_id}", on_click=record_feedback, args=(scenario_id, True))
    columns[1].button("Did not work", key=f"failed_{scenario_id}", on_click=record_feedback, args=(scenario_id, False))
    columns[2].button("Reset experience to seed", key="reset_experience", on_click=reset_learning)
    with st.expander("Most recent feedback"):
        st.json(decision.details.get("last_update") or {"status": "No feedback recorded"})


def render_trace(decisions: list[AgentDecision]) -> None:
    with st.expander("LLM tool-call trace"):
        llm = next((item for item in decisions if "LLM" in item.agent_name), None)
        if llm is None:
            st.warning("No LLM decision was returned.")
            return
        calls = llm.details.get("tool_calls", [])
        st.write("**Model:**", llm.details.get("model", "Not provided"))
        st.write("**Tool selection mode:**", llm.details.get("tool_mode", "Not provided"))
        count = len({call.get("tool") for call in calls if call.get("tool")})
        st.write("**Distinct tools:**", count)
        if count < 2:
            st.warning("The assignment requires at least two distinct relevant tools.")
        if llm.details.get("error"):
            st.error(str(llm.details["error"]))
        for index, call in enumerate(calls, start=1):
            st.write(f"**{index}. {call.get('tool', 'Unknown tool')}**")
            st.caption(f"Selection mode: {call.get('mode', 'Not provided')}")
            st.json(call.get("args", {}))
            st.code(str(call.get("output", "")), language=None)


def main() -> None:
    st.set_page_config(page_title="CI/CD Failure Assistant", page_icon="🔎", layout="wide")
    st.title("Intelligent CI/CD Pipeline Failure Assistant")
    st.info("Pipeline access is read-only. Agents recommend human troubleshooting actions; they never change code or deploy. Learning feedback saves local experience counts.")
    st.session_state.setdefault(RESULTS_KEY, {})
    checker, checker_note = optional_function("core.evidence_check", "check_evidence")
    shared_table, comparison_note = optional_function("core.comparison", "build_table")

    # Scenario metadata comes from the same loader used by the runner.
    try:
        scenarios = {sid: load_scenario(sid)[0] for sid in SCENARIO_FILES}
    except Exception as error:
        st.error(f"Could not load scenarios: {error}")
        st.stop()
    scenario_id = st.selectbox("Select scenario", list(scenarios), format_func=lambda sid: f"{sid} — {scenarios[sid]['name']}")
    scenario = scenarios[scenario_id]
    st.caption(f"Scenario type: {scenario.get('scenario_type', 'Not provided')} · Model: {os.getenv('OLLAMA_MODEL', 'qwen3:4b')}")
    with st.expander("Raw scenario received by the agents"):
        st.json(scenario)

    if st.session_state.get(NOTICE_KEY):
        level, message = st.session_state.pop(NOTICE_KEY)
        getattr(st, level)(message)

    current_fingerprint = fingerprint(scenario)
    entry = st.session_state[RESULTS_KEY].get(scenario_id)
    if entry and entry["fingerprint"] != current_fingerprint:
        del st.session_state[RESULTS_KEY][scenario_id]
        st.warning("Scenario or model settings changed. Run analysis again.")

    run_col, clear_col = st.columns(2)
    run_clicked = run_col.button("Run / rerun all six agents", type="primary")
    if clear_col.button("Clear stored analyses"):
        st.session_state[RESULTS_KEY].clear()
        st.rerun()
    if run_clicked:
        try:
            with st.spinner("Running all six agents. Local model inference can take several minutes..."):
                with operation_lock():
                    decisions = run_all_agents(scenario_id)
                validate_decisions(decisions)
            st.session_state[RESULTS_KEY][scenario_id] = {
                "fingerprint": current_fingerprint,
                "ran_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                "decisions": decisions,
            }
        except Exception as error:
            LOGGER.exception("Agent execution failed")
            st.error(f"Analysis failed: {error}. Check dependencies and Ollama, then retry.")
            st.stop()

    entry = st.session_state[RESULTS_KEY].get(scenario_id)
    if not entry:
        st.info("Choose a scenario and click Run / rerun all six agents. No LLM calls occur until you click Run.")
        st.stop()

    # Reading the experience file is cheap and also picks up feedback saved by
    # another browser session. Cached LLM and other classical results stay intact.
    try:
        with operation_lock():
            replacement = LearningAgent().decide(scenario)
        entry["decisions"] = [replacement if is_learning(item) else item for item in entry["decisions"]]
    except Exception as error:
        st.error(f"Could not refresh learning experience: {error}")
        st.stop()

    decisions = entry["decisions"]
    st.caption(f"Analysis run at {entry['ran_at']} (UTC). Results are retained for this browser session. Learning counts refresh from disk.")
    if checker_note:
        st.warning("Shared evidence checker unavailable. Badges use the built-in literal matcher; this does not complete the shared checker deliverable.")
    st.caption("Evidence badges check literal presence only. Review whether each quotation supports the cause and recommendation.")
    reports = {item.agent_name: evidence_report(item, scenario, checker) for item in decisions}
    available = [item for item in decisions if not item.details.get("error")]
    categories = Counter(item.failure_category for item in available)
    highest = max(categories.values(), default=0)
    leaders = [category for category, count in categories.items() if count == highest]
    metrics = st.columns(3)
    metrics[0].metric("Decisions returned", f"{len(decisions)}/6")
    metrics[1].metric("Largest category agreement", f"{highest}/{len(available)}" if available else "Unavailable")
    metrics[2].metric("Unavailable analyses", len(decisions) - len(available))
    st.caption("Leading categories: " + (", ".join(leaders) or "None") + ". Agreement does not measure accuracy.")

    st.subheader("Agent comparison")
    table = build_comparison(decisions, reports)
    st.dataframe(table, hide_index=True, width="stretch")
    if shared_table:
        with st.expander("Shared comparison module output"):
            try:
                shared_output = shared_table(decisions)
                if isinstance(shared_output, pd.DataFrame):
                    st.dataframe(shared_output, hide_index=True, width="stretch")
                else:
                    st.write(shared_output)
            except Exception as error:
                st.warning(f"The shared comparison module failed: {error}")
    elif comparison_note:
        st.caption("Using the built-in comparison table while the shared comparison module is unfinished.")

    markdown = f"# Scenario {scenario_id}: {scenario['name']}\n\n" + markdown_table(table)
    markdown += "\n\n## Mechanisms and reasoning\n"
    for item in decisions:
        markdown += f"\n### {item.agent_name}\n\n{mechanism_for(item)}\n\n{item.reasoning}\n"
    downloads = st.columns(3)
    downloads[0].download_button("Download comparison CSV", table.to_csv(index=False).encode("utf-8"), f"comparison_{scenario_id}.csv", "text/csv")
    downloads[1].download_button("Download comparison Markdown", markdown.encode("utf-8"), f"comparison_{scenario_id}.md", "text/markdown")
    downloads[2].download_button("Download full decisions JSON", json.dumps({"scenario": scenario_id, "analysis_run_at": entry["ran_at"], "decisions": [item.to_dict() for item in decisions], "evidence_checks": reports}, indent=2, default=str).encode("utf-8"), f"decisions_{scenario_id}.json", "application/json")

    render_differences(decisions)
    render_trace(decisions)
    render_learning(get_learning(decisions), scenario_id)
    st.subheader("Full agent decisions")
    for decision in decisions:
        render_decision(decision, reports[decision.agent_name])


if __name__ == "__main__":
    main()
