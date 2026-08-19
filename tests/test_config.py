"""
tests/test_config.py
---------------------
Tests for config/settings.py loading and validation.
"""




def test_settings_loads():
    """Settings can be instantiated without error."""
    # Import after conftest has set env vars
    from config.settings import get_settings

    s = get_settings()
    assert s is not None


def test_default_db_url():
    """DB_URL defaults to SQLite in test environment."""
    from config.settings import get_settings

    s = get_settings()
    assert "sqlite" in s.db_url


def test_paper_trade_default():
    """PAPER_TRADE_ONLY defaults to True (safe default)."""
    from config.settings import get_settings

    s = get_settings()
    assert s.paper_trade_only is True


def test_max_kelly_fraction_is_conservative():
    """Max Kelly fraction must not exceed 10% (safety guard)."""
    from config.settings import get_settings

    s = get_settings()
    assert s.max_kelly_fraction <= 0.10


def test_min_edge_threshold_positive():
    """Min edge threshold must be positive."""
    from config.settings import get_settings

    s = get_settings()
    assert s.min_edge_threshold > 0.0


def test_settings_singleton():
    """get_settings() returns the same cached instance."""
    from config.settings import get_settings

    s1 = get_settings()
    s2 = get_settings()
    assert s1 is s2
