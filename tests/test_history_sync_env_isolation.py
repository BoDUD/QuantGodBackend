from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]


def test_history_sync_only_loads_usdjpy_environment() -> None:
    source = (REPO_ROOT / "tools" / "run_mac_usdjpy_history_sync_loop.sh").read_text(encoding="utf-8")

    assert 'load_env_file "$REPO_ROOT/.env.usdjpy.local"' in source
    for forbidden in (
        ".env.local",
        ".env.auto.local",
        ".env.telegram.local",
        ".env.deepseek.local",
    ):
        assert forbidden not in source


def test_history_sync_has_no_notification_or_model_dispatch() -> None:
    source = (REPO_ROOT / "tools" / "run_mac_usdjpy_history_sync_loop.sh").read_text(encoding="utf-8").lower()

    for forbidden in ("telegram", "deepseek", "run_telegram_gateway", "--send"):
        assert forbidden not in source


def test_history_sync_propagates_required_stage_failures() -> None:
    source = (REPO_ROOT / "tools" / "run_mac_usdjpy_history_sync_loop.sh").read_text(encoding="utf-8")

    assert 'history_sync_command || echo' not in source
    assert 'quality || echo' not in source
    assert "return 1" in source
    assert "operationId=" in source
    assert "failureCount=" in source
