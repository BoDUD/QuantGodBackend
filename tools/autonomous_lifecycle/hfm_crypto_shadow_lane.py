from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict

try:
    from tools.hfm_crypto_cfd.builder import build_hfm_crypto_cfd_state
    from tools.hfm_crypto_cfd.schema import SAFETY
except ModuleNotFoundError:  # pragma: no cover
    from hfm_crypto_cfd.builder import build_hfm_crypto_cfd_state
    from hfm_crypto_cfd.schema import SAFETY


def build_hfm_crypto_shadow_lane(
    runtime_dir: Path,
    *,
    write: bool = False,
    moss_backtest_json: str = "",
    simulation_profile_json: str = "",
    contract_spec_json: str = "",
    extra_bases_roots: list[str] | None = None,
) -> Dict[str, Any]:
    runtime_dir = Path(runtime_dir)
    state = build_hfm_crypto_cfd_state(
        runtime_dir,
        moss_backtest_json=moss_backtest_json,
        simulation_profile_json=simulation_profile_json,
        contract_spec_json=contract_spec_json,
        extra_bases_roots=extra_bases_roots or [],
        write=write,
    )
    local = state.get("localEvidence") if isinstance(state.get("localEvidence"), dict) else {}
    symbol_evidence = state.get("symbolEvidence") if isinstance(state.get("symbolEvidence"), dict) else {}
    moss = state.get("mossBacktestProfile") if isinstance(state.get("mossBacktestProfile"), dict) else {}
    execution_spec = state.get("executionSpecReview") if isinstance(state.get("executionSpecReview"), dict) else {}
    simulation_review = state.get("simulationProfileReview") if isinstance(state.get("simulationProfileReview"), dict) else {}
    standalone_exporter = state.get("standaloneExporterBundle") if isinstance(state.get("standaloneExporterBundle"), dict) else {}
    metrics = moss.get("metrics") if isinstance(moss.get("metrics"), dict) else {}
    status = str(state.get("status") or "WAITING_HFM_CRYPTO_SYMBOLS")
    ready = status == "READY_FOR_SHADOW_RESEARCH"
    payload: Dict[str, Any] = {
        "ok": True,
        "schema": "quantgod.hfm_crypto_shadow_lane.v1",
        "lane": "HFM_CRYPTO_CFD_SHADOW",
        "laneZh": "HFM Crypto CFD 影子车道",
        "stage": "SHADOW" if ready else "WAITING_SYMBOL_EVIDENCE",
        "stageZh": "影子研究就绪" if ready else "等待 HFM crypto symbol 证据",
        "status": status,
        "statusZh": state.get("statusZh"),
        "riskContextOnly": True,
        "hfmCryptoCfdState": state,
        "summary": {
            "symbolEvidenceFound": bool(symbol_evidence.get("found") or local.get("found")),
            "symbolEvidenceSources": symbol_evidence.get("sources", []),
            "targetSymbolCount": len(state.get("targetSymbols") or []),
            "detectedSymbolCount": len(symbol_evidence.get("canonicalSymbols") or local.get("canonicalSymbols") or []),
            "mossProfileFound": bool(moss.get("profileFound")),
            "mossRoiPct": metrics.get("roiPct"),
            "mossSharpe": metrics.get("sharpe"),
            "mossMaxDrawdownPct": metrics.get("maxDrawdownPct"),
            "mossLiquidationCount": metrics.get("liquidationCount"),
            "simulationProfileStatus": simulation_review.get("status"),
            "simulationProfileQualified": bool(simulation_review.get("simulationQualified")),
            "executionSpecStatus": execution_spec.get("status"),
            "executionSpecReady": bool(execution_spec.get("readyForExecutionSpecReview")),
            "executionSpecValidRowCount": execution_spec.get("validRowCount", 0),
            "standaloneExporterStatus": standalone_exporter.get("status"),
            "standaloneExporterTargetInstalledAndCompiled": bool(standalone_exporter.get("targetInstalledAndCompiled")),
        },
        "reasonZh": (
            "HFM crypto CFD symbol 与 Moss 回测 profile 可用于只读影子研究。"
            if ready
            else state.get("nextRequiredActionZh") or "还没发现 HFM crypto CFD 的 Bases、EA specs、registry 或 contract spec 证据。"
        ),
        "safety": {
            **SAFETY,
            "hfmCryptoExecutionAllowed": False,
            "mt5OrderSendAllowed": False,
            "copyTradeExecutionAllowed": False,
        },
    }
    if write:
        out = runtime_dir / "agent"
        out.mkdir(parents=True, exist_ok=True)
        (out / "QuantGod_HFMCryptoShadowLane.json").write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    return payload
