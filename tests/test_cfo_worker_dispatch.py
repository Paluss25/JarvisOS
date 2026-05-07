import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))


def test_cfo_worker_dispatch_resolves_live_worker_routes():
    from agents.cfo.tools import _resolve_worker_sub_agent

    assert _resolve_worker_sub_agent("finance", "ynab-finance") == ("ynab", None)
    assert _resolve_worker_sub_agent("cost", "ai-cost") == ("ai-cost", None)
    assert _resolve_worker_sub_agent("market", "market-news") == ("market-news", None)
    assert _resolve_worker_sub_agent("strategy", "opportunity-scanner") == (
        "opportunity-scanner",
        None,
    )


def test_cfo_worker_dispatch_uses_runtime_defaults():
    from agents.cfo.tools import _resolve_worker_sub_agent

    assert _resolve_worker_sub_agent("finance", "") == ("ynab", None)
    assert _resolve_worker_sub_agent("cost", "") == ("ai-cost", None)
    assert _resolve_worker_sub_agent("market", "") == ("market-quotes", None)


def test_cfo_worker_dispatch_rejects_unknown_sub_agent():
    from agents.cfo.tools import _resolve_worker_sub_agent

    target, error = _resolve_worker_sub_agent("cost", "../ai-cost")

    assert target is None
    assert error is not None
    assert "not allowed" in error
