"""LLM Agent.

Uses a local Ollama model (Qwen3 by default) through LangChain. The agent
works in three steps:

1. Investigate: the model calls read-only pipeline tools. Native tool
   calling is tried first; if the model calls fewer than two tools, it keeps
   choosing tools one at a time through structured JSON output instead.
2. Assess: the model receives every tool output as numbered lines and
   returns a structured assessment that cites evidence by line number.
3. Ground: the cited lines are copied verbatim into the decision, so every
   evidence item is exact text returned by a tool.

The agent only recommends; it never changes code or deploys.
"""

import json
import os
import re
from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage, ToolMessage

from agents.base import BaseAgent
from core.schema import AgentDecision
from tools.pipeline_tools import ALL_TOOLS, TOOLS_BY_NAME, set_scenario

DEFAULT_MODEL = os.getenv("OLLAMA_MODEL", "qwen3:4b")
CONTEXT_WINDOW = int(os.getenv("OLLAMA_NUM_CTX", "4096"))
MAX_ANSWER_TOKENS = 1024
MAX_TOOL_ROUNDS = 4
MIN_TOOL_CALLS = 2

CATEGORIES = [
    "TEST_FAILURE",
    "DEPENDENCY_FAILURE",
    "DEPLOYMENT_HEALTH_FAILURE",
    "NO_FAILURE",
    "AMBIGUOUS",
]

SYSTEM_PROMPT = """You are a CI/CD pipeline failure investigator.

Rules:
1. Gather evidence with tools before deciding. Start with get_pipeline_status
   to see which stage failed, then:
   - dependency_install or build failed: read_build_logs and get_dependency_info
   - unit_tests failed: get_test_results and get_recent_change_summary
   - deployment passed but health checks are unhealthy: read_build_logs and
     get_recent_change_summary
   - everything passed: read_build_logs to confirm there are no errors
2. Base every conclusion only on what the tools returned.
3. You only recommend. Never claim to have changed code, re-run, or deployed.
   The recommended next step is performed by a human.

Failure categories:
- TEST_FAILURE: unit tests fail, typically after a code change.
- DEPENDENCY_FAILURE: a package version is unavailable or incompatible.
- DEPLOYMENT_HEALTH_FAILURE: build and tests pass but post-deployment health checks fail.
- NO_FAILURE: all stages passed and health checks are healthy.
- AMBIGUOUS: signals conflict or are inconclusive, such as a test that failed
  and then passed on retry."""

USER_PROMPT = "A CI/CD pipeline run needs investigation. Use the tools to inspect it."

ASSESS_PROMPT = """Every tool output above is split into numbered lines (L1, L2, ...).

Return your assessment as JSON with these keys:
- failure_category: one of the five categories
- evidence_lines: the numbers of the 2 to 4 lines that best support your decision
- likely_cause: one or two sentences
- next_step: one action a human should take next
- verification_checklist: 3 to 5 checks that confirm the fix worked
- reasoning: how the evidence led to your decision
- confidence: a number between 0 and 1"""

ASSESSMENT_SCHEMA = {
    "type": "object",
    "properties": {
        "failure_category": {"type": "string", "enum": CATEGORIES},
        "evidence_lines": {"type": "array", "items": {"type": "integer"}},
        "likely_cause": {"type": "string"},
        "next_step": {"type": "string"},
        "verification_checklist": {"type": "array", "items": {"type": "string"}},
        "reasoning": {"type": "string"},
        "confidence": {"type": "number"},
    },
    "required": [
        "failure_category",
        "evidence_lines",
        "likely_cause",
        "next_step",
        "verification_checklist",
        "reasoning",
        "confidence",
    ],
}


class LLMAgent(BaseAgent):
    """Recommends the next troubleshooting step using an LLM with tool calling."""

    name = "LLM Agent"

    def __init__(self, model: str = DEFAULT_MODEL, llm: Any = None) -> None:
        """Create the agent.

        Args:
            model: Ollama model tag, e.g. "qwen3:4b". Can also be set with
                the OLLAMA_MODEL environment variable.
            llm: Optional pre-built chat model, used by tests. When given,
                it is used for every step.
        """
        self.model = model
        self._test_llm = llm

    # ------------------------------------------------------------------ main

    def decide(self, scenario: dict) -> AgentDecision:
        set_scenario(scenario)
        tool_calls: list[dict[str, Any]] = []
        tool_mode = "native"

        try:
            # Step 1: investigate.
            self._native_tool_loop(tool_calls)
            if len(tool_calls) < MIN_TOOL_CALLS:
                tool_mode = "structured"
                self._structured_tool_loop(tool_calls)

            # Step 2: assess.
            numbered_lines = number_tool_output_lines(tool_calls)
            assessment = self._assess(numbered_lines)
        except Exception as error:  # Ollama not running, model missing, etc.
            return self._fallback(
                reason=(
                    f"The LLM call failed ({type(error).__name__}: {error}). "
                    f"Check that Ollama is running and '{self.model}' is pulled."
                ),
                tool_calls=tool_calls,
            )

        if assessment is None:
            return self._fallback(
                reason="The model did not return a usable assessment.",
                tool_calls=tool_calls,
            )

        # Step 3: ground.
        return self._build_decision(assessment, numbered_lines, tool_calls, tool_mode)

    # ------------------------------------------------------- investigation

    def _native_tool_loop(self, tool_calls: list[dict[str, Any]]) -> None:
        """Native tool calling: the model requests tools through the tool-call API."""
        llm_with_tools = self._chat_model().bind_tools(ALL_TOOLS)
        messages = [SystemMessage(SYSTEM_PROMPT), HumanMessage(USER_PROMPT)]

        for _ in range(MAX_TOOL_ROUNDS):
            response = llm_with_tools.invoke(messages)
            messages.append(response)
            if not response.tool_calls:
                return

            new_tool_called = False
            for call in response.tool_calls:
                called = {c["tool"] for c in tool_calls}
                tool = TOOLS_BY_NAME.get(call["name"])
                if tool is None:
                    output = f"Unknown tool: {call['name']}"
                elif call["name"] in called:
                    # Tools are read-only, so a repeat returns nothing new.
                    output = "This tool was already called; use its earlier output."
                else:
                    output = tool.invoke(call.get("args") or {})
                    tool_calls.append(
                        {"tool": call["name"], "args": call.get("args") or {}, "output": output, "mode": "native"}
                    )
                    new_tool_called = True
                messages.append(ToolMessage(content=output, tool_call_id=call["id"]))

            if not new_tool_called:
                return

    def _structured_tool_loop(self, tool_calls: list[dict[str, Any]]) -> None:
        """Structured tool selection: the model picks one tool at a time as JSON.

        Each step shows the outputs gathered so far. The JSON schema only
        allows tools that have not been called yet, and only allows "done"
        once at least two tools have been called.
        """
        for _ in range(MAX_TOOL_ROUNDS):
            called = {call["tool"] for call in tool_calls}
            remaining = [t for t in ALL_TOOLS if t.name not in called]
            if not remaining:
                return

            options = [t.name for t in remaining]
            if len(tool_calls) >= MIN_TOOL_CALLS:
                options.append("done")

            menu = "\n".join(f"- {t.name}: {t.description}" for t in remaining)
            gathered = format_tool_outputs(tool_calls) or "none yet"
            prompt = (
                f"{USER_PROMPT}\n\nTool outputs so far:\n\n{gathered}\n\n"
                f"Tools you can still call:\n{menu}\n\n"
                'Which tool should be called next? Reply as JSON: {"next_tool": "<name>"}'
                + (', or {"next_tool": "done"} if you have enough evidence.' if "done" in options else ".")
            )
            schema = {
                "type": "object",
                "properties": {"next_tool": {"type": "string", "enum": options}},
                "required": ["next_tool"],
            }
            reply = self._chat_model(schema).invoke(
                [SystemMessage(SYSTEM_PROMPT), HumanMessage(prompt)]
            ).content
            choice = str((parse_json_answer(reply) or {}).get("next_tool", "")).strip()

            if choice == "done" and "done" in options:
                return
            if choice not in TOOLS_BY_NAME or choice in called:
                choice = remaining[0].name  # guard for malformed replies

            output = TOOLS_BY_NAME[choice].invoke({})
            tool_calls.append({"tool": choice, "args": {}, "output": output, "mode": "structured"})

    # ----------------------------------------------------------- assessment

    def _assess(self, numbered_lines: list[str]) -> dict[str, Any] | None:
        """Ask for the structured assessment, retrying once if it is unusable."""
        evidence_block = "\n".join(f"L{i}: {line}" for i, line in enumerate(numbered_lines, 1))
        messages = [
            SystemMessage(SYSTEM_PROMPT),
            HumanMessage(f"{USER_PROMPT}\n\nTool outputs:\n\n{evidence_block}\n\n{ASSESS_PROMPT}"),
        ]
        model = self._chat_model(ASSESSMENT_SCHEMA)

        for _ in range(2):
            parsed = parse_json_answer(model.invoke(messages).content)
            if parsed and parsed.get("failure_category") in CATEGORIES:
                return parsed
        return None

    def _build_decision(
        self,
        assessment: dict[str, Any],
        numbered_lines: list[str],
        tool_calls: list[dict[str, Any]],
        tool_mode: str,
    ) -> AgentDecision:
        evidence = []
        for number in assessment.get("evidence_lines") or []:
            if isinstance(number, int) and 1 <= number <= len(numbered_lines):
                line = numbered_lines[number - 1]
                if line not in evidence:
                    evidence.append(line)

        next_step = str(assessment.get("next_step", "")).strip() or "Review the pipeline evidence."
        if "human action required" not in next_step.lower():
            next_step = f"{next_step.rstrip('.')}. Human action required"

        tools_used = ", ".join(dict.fromkeys(call["tool"] for call in tool_calls)) or "none"
        reasoning = (
            f"Called {len(tool_calls)} tool(s) ({tool_mode} tool selection): {tools_used}. "
            f"{str(assessment.get('reasoning', '')).strip()}"
        )
        if not evidence:
            reasoning += " Note: the model cited no valid evidence lines."

        return AgentDecision(
            agent_name=self.name,
            failure_category=assessment["failure_category"],
            evidence=evidence,
            likely_cause=str(assessment.get("likely_cause", "")).strip(),
            next_step=next_step,
            verification_checklist=as_string_list(assessment.get("verification_checklist")),
            reasoning=reasoning,
            confidence=as_confidence(assessment.get("confidence")),
            details={
                "model": self.model,
                "tool_mode": tool_mode,
                "tool_calls": tool_calls,
                "tool_call_count": len(tool_calls),
                "evidence_lines": assessment.get("evidence_lines"),
            },
        )

    def _fallback(self, reason: str, tool_calls: list[dict[str, Any]]) -> AgentDecision:
        """Safe decision returned when the model cannot produce a usable answer."""
        return AgentDecision(
            agent_name=self.name,
            failure_category="AMBIGUOUS",
            evidence=[],
            likely_cause="The LLM agent could not complete its analysis.",
            next_step="Review the classical agents' recommendations. Human action required",
            verification_checklist=[
                "Confirm Ollama is running.",
                f"Confirm the model '{self.model}' is pulled.",
                "Run the scenario again.",
            ],
            reasoning=reason,
            confidence=None,
            details={
                "model": self.model,
                "tool_calls": tool_calls,
                "tool_call_count": len(tool_calls),
                "error": reason,
            },
        )

    # ---------------------------------------------------------------- model

    def _chat_model(self, schema: dict | None = None) -> Any:
        """Return the chat model, optionally constrained to a JSON schema."""
        if self._test_llm is not None:
            return self._test_llm

        from langchain_ollama import ChatOllama

        # Qwen3 is not meant for greedy decoding (temperature 0): it tends to
        # repeat itself until Ollama aborts. These are Qwen3's recommended
        # non-thinking sampling settings; the fixed seed keeps runs repeatable.
        settings: dict[str, Any] = {
            "model": self.model,
            "reasoning": False,
            "temperature": 0.7,
            "top_p": 0.8,
            "top_k": 20,
            "repeat_penalty": 1.1,
            "seed": 42,
            "num_ctx": CONTEXT_WINDOW,
            "num_predict": MAX_ANSWER_TOKENS,
        }
        if schema is not None:
            settings["format"] = schema
        return ChatOllama(**settings)


# -------------------------------------------------------------------- helpers


def format_tool_outputs(tool_calls: list[dict[str, Any]]) -> str:
    return "\n\n".join(f"### Output of {call['tool']}\n{call['output']}" for call in tool_calls)


def number_tool_output_lines(tool_calls: list[dict[str, Any]]) -> list[str]:
    """Split all tool outputs into non-empty lines, exactly as the tools returned them."""
    lines = []
    for call in tool_calls:
        for line in str(call["output"]).splitlines():
            if line.strip():
                lines.append(line.strip())
    return lines


def parse_json_answer(text: str) -> dict[str, Any] | None:
    """Extract the JSON object from a model message."""
    if not text:
        return None
    text = re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL)
    text = re.sub(r"```(?:json)?", "", text)
    match = re.search(r"\{.*\}", text, flags=re.DOTALL)
    if not match:
        return None
    try:
        data = json.loads(match.group(0))
    except json.JSONDecodeError:
        return None
    return data if isinstance(data, dict) else None


def as_string_list(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    if isinstance(value, str) and value.strip():
        return [value.strip()]
    return []


def as_confidence(value: Any) -> float | None:
    try:
        return max(0.0, min(1.0, float(value)))
    except (TypeError, ValueError):
        return None
