"""Environment smoke tests; no real Discord requests are sent."""

import pytest

from stock_signal.__main__ import main


def test_dry_run_starts(monkeypatch, capsys):
    monkeypatch.setenv("DRY_RUN", "true")
    main()
    assert "development environment is ready" in capsys.readouterr().out


def test_live_mode_is_blocked(monkeypatch):
    monkeypatch.setenv("DRY_RUN", "false")
    with pytest.raises(RuntimeError, match="not implemented"):
        main()
