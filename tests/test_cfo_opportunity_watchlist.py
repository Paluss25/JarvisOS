import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))


def test_opportunity_watchlist_expands_single_holding_with_default_diversifiers(monkeypatch):
    from workers.strategy import opportunity

    monkeypatch.setenv("CFO_OPPORTUNITY_DEFAULT_WATCHLIST", "BTC,ETH,AMD,RIOT,XRP,GLD")

    result = opportunity._resolve_watchlist(
        holdings=[{"symbol": "BTC"}],
        scope_watchlist=None,
    )

    assert result[:6] == ["BTC", "ETH", "AMD", "RIOT", "XRP", "GLD"]


def test_opportunity_watchlist_honors_explicit_scope_without_expansion(monkeypatch):
    from workers.strategy import opportunity

    monkeypatch.setenv("CFO_OPPORTUNITY_DEFAULT_WATCHLIST", "BTC,ETH,AMD")

    result = opportunity._resolve_watchlist(
        holdings=[{"symbol": "BTC"}],
        scope_watchlist=["vwce", "sgld"],
    )

    assert result == ["VWCE", "SGLD"]
