"""
tests/test_health.py
---------------------
Tests for the /health endpoint.
"""


def test_health_ok(client):
    """Health endpoint returns 200 with expected fields."""
    response = client.get("/health/")
    assert response.status_code == 200
    body = response.json()
    assert body["db_ok"] is True
    assert body["paper_trade_only"] is True
    assert body["status"] in ("ok", "degraded")
    assert "timestamp" in body
    assert "app_env" in body


def test_health_paper_trade_flag(client):
    """paper_trade_only must be True in test environment (default .env)."""
    response = client.get("/health/")
    assert response.json()["paper_trade_only"] is True
