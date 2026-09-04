from __future__ import annotations

import sys
from types import SimpleNamespace

from src.agents import llm_event_analyst
from src.orchestration.langgraph_v5 import run_v5_langgraph
from src.v5_config import V5DiscoveryConfig


def test_timeout_falls_back_with_typed_degradation_reason(monkeypatch):
    monkeypatch.setattr(
        llm_event_analyst,
        "_call_llm",
        lambda news_text: (_ for _ in ()).throw(TimeoutError("request timed out")),
    )

    event = llm_event_analyst.analyze_event_with_llm(
        "Red Sea shipping routes face disruption from regional conflict."
    )
    trace = llm_event_analyst.get_last_analysis_trace()

    assert event.supply_chain_nodes
    assert trace["fallback_occurred"] is True
    assert trace["effective_event_analyzer"] == "rule"
    assert trace["degradation_reason"] == "LLM_TIMEOUT"
    assert trace["llm_latency_ms"] >= 0


def test_openai_client_uses_five_second_budget_without_sdk_retries(monkeypatch):
    observed = {}

    class FakeCompletions:
        def create(self, **kwargs):
            return SimpleNamespace(
                usage=None,
                choices=[SimpleNamespace(message=SimpleNamespace(content="{}"))],
            )

    class FakeOpenAI:
        def __init__(self, **kwargs):
            observed.update(kwargs)
            self.chat = SimpleNamespace(completions=FakeCompletions())

    monkeypatch.setitem(sys.modules, "openai", SimpleNamespace(OpenAI=FakeOpenAI))

    assert llm_event_analyst._call_llm("test event") == "{}"
    assert observed == {
        "timeout": llm_event_analyst.LLM_EVENT_ANALYST_TIMEOUT_SECONDS,
        "max_retries": 0,
    }
    assert observed["timeout"] == 5.0


def test_failure_reason_codes_do_not_include_exception_details():
    assert llm_event_analyst._classify_failure(TimeoutError("secret detail")) == "LLM_TIMEOUT"
    assert llm_event_analyst._classify_failure(ValueError("bad json")) == "LLM_INVALID_OUTPUT"


def test_pipeline_output_identifies_effective_fallback_path(monkeypatch):
    monkeypatch.setattr(
        llm_event_analyst,
        "_call_llm",
        lambda news_text: (_ for _ in ()).throw(TimeoutError("request timed out")),
    )

    result = run_v5_langgraph(
        "Red Sea shipping routes face disruption from regional conflict.",
        event_analyzer="llm",
        config=V5DiscoveryConfig(enable_node_repair=False),
    )
    metadata = result.final_report.execution_metadata

    assert metadata is not None
    assert metadata.requested_event_analyzer == "llm"
    assert metadata.effective_event_analyzer == "rule"
    assert metadata.degraded is True
    assert metadata.degradation_reason == "LLM_TIMEOUT"
    assert metadata.outcome_status == result.state.status
