from __future__ import annotations

import json
import logging

from src import observability
from src.observability import ExecutionMetadata, FunnelMetrics


def test_jsonl_run_record_contains_safe_aggregatable_fields(tmp_path, monkeypatch):
    log_path = tmp_path / "runtime.jsonl"
    monkeypatch.setattr(observability, "_LOG_PATH", log_path)
    logger = logging.getLogger("georisk.runtime")
    for handler in list(logger.handlers):
        handler.close()
        logger.removeHandler(handler)

    with observability.analysis_run("run-test") as telemetry:
        observability.record_gate_decision(
            candidate_type="supply_chain_node",
            candidate_id="ports",
            gate="support_threshold",
            accepted=False,
            reason_code="SUPPORT_BELOW_THRESHOLD",
            support_count=1,
            threshold=2,
        )
        metadata = ExecutionMetadata(
            run_id=telemetry.run_id,
            requested_event_analyzer="llm",
            effective_event_analyzer="rule",
            degraded=True,
            degradation_reason="LLM_TIMEOUT",
            total_latency_ms=12.5,
            llm_latency_ms=10.0,
            llm_latency_share_pct=80.0,
            outcome_status="RANKING_ABSTAIN",
            funnel=FunnelMetrics(rejected_decision_count=1),
            gate_decisions=list(telemetry.gate_decisions),
        )
        observability.emit_run_record(metadata, total_latency_ms=12.5)

    payload = json.loads(log_path.read_text(encoding="utf-8"))
    assert payload["run_id"] == "run-test"
    assert payload["outcome_status"] == "RANKING_ABSTAIN"
    assert payload["degradation_reason"] == "LLM_TIMEOUT"
    assert payload["total_latency_ms"] == 12.5
    assert payload["llm_latency_share_pct"] == 80.0
    assert payload["gate_decisions"][0]["reason_code"] == "SUPPORT_BELOW_THRESHOLD"
    assert "news_text" not in payload
    assert "api_key" not in json.dumps(payload).lower()


def test_gate_decisions_are_isolated_by_analysis_context():
    with observability.analysis_run("first") as first:
        observability.record_gate_decision(
            candidate_type="node",
            candidate_id="a",
            gate="test",
            accepted=True,
            reason_code="PASS",
        )
        assert len(first.gate_decisions) == 1

    with observability.analysis_run("second") as second:
        assert second.gate_decisions == []
