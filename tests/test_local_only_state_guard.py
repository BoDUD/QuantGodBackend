from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]


def test_active_backend_has_no_retired_remote_state_sync() -> None:
    roots = [
        REPO_ROOT / "Dashboard",
        REPO_ROOT / "MQL5",
        REPO_ROOT / "tools",
        REPO_ROOT / "scripts",
    ]
    forbidden_fragments = ("cloud" + "flare", "cloud" + "sync", "qg_" + "ingest_token")
    suffixes = {".py", ".js", ".mjs", ".sh", ".mq5", ".json"}
    findings: list[str] = []
    for root in roots:
        for path in root.rglob("*"):
            if not path.is_file() or path.suffix.lower() not in suffixes:
                continue
            text = path.read_text(encoding="utf-8", errors="ignore").lower().replace("_", " ")
            for fragment in forbidden_fragments:
                if fragment.replace("_", " ") in text:
                    findings.append(f"{path.relative_to(REPO_ROOT)}:{fragment}")
    assert findings == []


def test_sqlite_local_state_store_remains_available() -> None:
    sqlite_store = REPO_ROOT / "tools" / "usdjpy_strategy_backtest" / "sqlite_store.py"
    assert sqlite_store.exists()
    source = sqlite_store.read_text(encoding="utf-8")
    assert "sqlite3" in source
