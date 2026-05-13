"""
tests/test_quant_dashboard_static.py
-------------------------------------
Smoke tests for the static Quant Dashboard bundle integrated from the Claude
Design handoff. Only checks that the FastAPI app serves every asset the
prototype loads — does not exercise the JS itself.
"""

import pytest

QUANT_ASSETS = [
    "/static/quant-dashboard/index.html",
    "/static/quant-dashboard/styles.css",
    "/static/quant-dashboard/icons.jsx",
    "/static/quant-dashboard/data.jsx",
    "/static/quant-dashboard/charts.jsx",
    "/static/quant-dashboard/chrome.jsx",
    "/static/quant-dashboard/kpi.jsx",
    "/static/quant-dashboard/sections.jsx",
    "/static/quant-dashboard/table.jsx",
    "/static/quant-dashboard/tweaks-panel.jsx",
    "/static/quant-dashboard/live-data.jsx",
    "/static/quant-dashboard/app.jsx",
]


@pytest.mark.parametrize("path", QUANT_ASSETS)
def test_quant_dashboard_asset_is_served(client, path):
    """Every asset referenced by index.html must be reachable via /static."""
    response = client.get(path)
    assert response.status_code == 200, f"missing asset: {path}"
    assert len(response.content) > 0, f"empty asset: {path}"


def test_quant_dashboard_index_wires_live_data(client):
    """index.html must include the live-data.jsx overlay so the bundle isn't pure mock."""
    response = client.get("/static/quant-dashboard/index.html")
    assert response.status_code == 200
    body = response.text
    assert "live-data.jsx" in body, "live-data overlay script is not wired into index.html"
    assert "app.jsx" in body, "app.jsx entry script is not wired into index.html"
