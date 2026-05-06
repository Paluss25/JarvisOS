"""Tests for CIO issue collection."""

import pytest

from agents.cio import issue_collector
from agents.cio.issue_collector import LokiIssueCollector


class FakePrometheus:
    async def query(self, promql: str):
        if promql == 'up{job="cadvisor"}':
            return [
                {"metric": {"instance": "10.10.200.50:9080"}, "value": [0, "1"]},
            ]
        raise AssertionError(f"unexpected query: {promql}")


@pytest.mark.asyncio
async def test_cadvisor_prometheus_miss_is_suppressed_when_live_endpoint_is_valid(monkeypatch):
    monkeypatch.setattr(
        issue_collector,
        "EXPECTED_NODE_EXPORTER",
        ["10.10.200.50:9100", "10.10.200.71:9100"],
    )

    collector = LokiIssueCollector()
    collector._prom = FakePrometheus()

    async def fake_probe(ip: str) -> bool:
        return ip == "10.10.200.71"

    monkeypatch.setattr(collector, "_cadvisor_endpoint_has_metrics", fake_probe)

    issues = await collector._check_cadvisor()

    assert issues == []


@pytest.mark.asyncio
async def test_cadvisor_missing_from_prometheus_and_endpoint_emits_connection_issue(monkeypatch):
    monkeypatch.setattr(
        issue_collector,
        "EXPECTED_NODE_EXPORTER",
        ["10.10.200.50:9100", "10.10.200.71:9100"],
    )

    collector = LokiIssueCollector()
    collector._prom = FakePrometheus()

    async def fake_probe(_ip: str) -> bool:
        return False

    monkeypatch.setattr(collector, "_cadvisor_endpoint_has_metrics", fake_probe)

    issues = await collector._check_cadvisor()

    assert len(issues) == 1
    assert issues[0].component == "10.10.200.71-cadvisor"
    assert issues[0].issue_type == "connection_error"
    assert "http://10.10.200.71:9080/metrics" in issues[0].suggested_action

