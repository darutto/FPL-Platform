"""Probe: drive the REAL orchestrator path with a response object in the
observed failing state (no tool calls, no text, no usage) and report what
the orchestrator actually returns. No network, no keys required."""
import json, sys
sys.path.insert(0, ".")
from fpl_grounded_assistant import orchestrator as orch

BOOT = json.load(open("../../field-notes/artifacts/agentic-loop-bootstrap-2026-08-18.json"))

class EmptyOpenAIResponse:
    """Shape matching the report: status/output present but nothing usable."""
    def __init__(self, status="completed", incomplete_details=None, output=None, usage=None):
        self.id = "resp_probe"
        self.status = status
        self.incomplete_details = incomplete_details
        self.output = output if output is not None else []
        self.output_text = ""
        self.usage = usage

class IncompleteDetails:
    def __init__(self, reason): self.reason = reason

class ReasoningItem:
    """output containing ONLY a reasoning item — the 'all budget on reasoning' case."""
    type = "reasoning"
    def __init__(self): self.id="rs_1"; self.summary=[]; self.content=[]

def run(label, resp):
    r = orch.ask_orchestrated(
        "¿Qué gameweek es la actual?", BOOT,
        provider="openai", model="gpt-5.6-luna",
        _orch_request_fn=lambda: resp,
    )
    print(f"--- {label} ---")
    print(f"  outcome     = {r.outcome!r}")
    print(f"  error       = {r.error!r}")
    print(f"  answer_text = {r.answer_text!r}")
    print(f"  tool_chosen = {r.tool_chosen!r}")
    print(f"  tokens in/out/cache = {r.primary_input_tokens}/{r.primary_output_tokens}/{r.primary_cache_read_tokens}")
    print(f"  answer_is_empty = {r.answer_text == ''}")
    print()

run("A: completed, empty output, no usage", EmptyOpenAIResponse())
run("B: incomplete/max_output_tokens, reasoning-only output",
    EmptyOpenAIResponse(status="incomplete",
                        incomplete_details=IncompleteDetails("max_output_tokens"),
                        output=[ReasoningItem()]))
run("C: response is None (success but nothing)", None)
