from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List


REPORT_SCHEMA = "quantgod.core_runtime_evidence_manifest.v1"
SCHEMA_VERSION = 1
REPORT_FILE = "QuantGod_CoreRuntimeEvidenceManifest.json"
REPORT_DIR = "integrity"

SAFETY: Dict[str, Any] = {
    "localOnly": True,
    "readOnlyAuditPlane": True,
    "advisoryOnly": True,
    "evidenceIntegrityOnly": True,
    "orderSendAllowed": False,
    "closeAllowed": False,
    "cancelAllowed": False,
    "modifyAllowed": False,
    "brokerExecutionAllowed": False,
    "mt5OrderSendAllowed": False,
    "writesMt5OrderRequest": False,
    "writesMt5Receipt": False,
    "livePresetMutationAllowed": False,
    "telegramCommandExecutionAllowed": False,
    "walletIntegrationAllowed": False,
}

CORE_ARTIFACTS: List[Dict[str, Any]] = [
    {
        "artifactId": "liveLoopStatus",
        "category": "live-loop",
        "path": "live/QuantGod_USDJPYLiveLoopStatus.json",
        "contentType": "json",
        "expectedSchemas": ["quantgod.usdjpy_live_loop_status.v1"],
        "required": True,
    },
    {
        "artifactId": "liveLoopLedger",
        "category": "live-loop",
        "path": "live/QuantGod_USDJPYLiveLoopLedger.csv",
        "contentType": "csv",
        "expectedSchemas": ["quantgod.usdjpy_live_loop_ledger.v1"],
        "required": True,
    },
    {
        "artifactId": "productionExecutionPolicy",
        "category": "production-policy",
        "path": "agent/QuantGod_ProductionExecutionPolicy.json",
        "contentType": "json",
        "expectedSchemas": ["quantgod.production_execution_policy.v1"],
        "required": True,
    },
    {
        "artifactId": "autoExecutionPolicy",
        "category": "production-policy",
        "path": "adaptive/QuantGod_AutoExecutionPolicy.json",
        "contentType": "json",
        "expectedSchemas": [
            "quantgod.auto_execution_policy.v1",
            "quantgod.usdjpy_auto_execution_policy.v1",
        ],
        "required": True,
    },
    {
        "artifactId": "autoExecutionPolicyLedger",
        "category": "production-policy",
        "path": "adaptive/QuantGod_AutoExecutionPolicyLedger.csv",
        "contentType": "csv",
        "expectedSchemas": ["quantgod.auto_execution_policy_ledger.v1"],
        "required": True,
    },
    {
        "artifactId": "gaFactoryArtifactManifest",
        "category": "ga-factory",
        "path": "ga_factory/QuantGod_GAFactoryArtifactManifest.json",
        "contentType": "json",
        "expectedSchemas": ["quantgod.strategy_ga_factory.artifact_manifest.v1"],
        "required": True,
        "requiresArtifactHashes": True,
    },
    {
        "artifactId": "historyProductionStatus",
        "category": "history-production",
        "path": "backtest/QuantGod_USDJPYHistoryProductionStatus.json",
        "contentType": "json",
        "expectedSchemas": ["quantgod.usdjpy_history_production_status.v1"],
        "required": True,
        "requiresHistoryPromotionGate": True,
    },
    {
        "artifactId": "strategyParityReport",
        "category": "strategy-parity",
        "path": "parity/QuantGod_StrategyParityReport.json",
        "contentType": "json",
        "expectedSchemas": ["quantgod.strategy_parity_report.v1"],
        "required": True,
        "requiresParityPromotionGate": True,
    },
    {
        "artifactId": "strategyParityLedger",
        "category": "strategy-parity",
        "path": "parity/QuantGod_StrategyParityLedger.csv",
        "contentType": "csv",
        "expectedSchemas": ["quantgod.strategy_parity_ledger.v1"],
        "required": True,
    },
    {
        "artifactId": "executionFeedbackQualityReport",
        "category": "execution-feedback",
        "path": "execution/QuantGod_LiveExecutionQualityReport.json",
        "contentType": "json",
        "expectedSchemas": ["quantgod.live_execution_quality_report.v1"],
        "required": True,
    },
    {
        "artifactId": "executionFeedbackLedger",
        "category": "execution-feedback",
        "path": "execution/QuantGod_LiveExecutionFeedback.jsonl",
        "contentType": "jsonl",
        "expectedSchemas": ["quantgod.execution_feedback.v1"],
        "required": True,
    },
    {
        "artifactId": "caseMemoryArtifactManifest",
        "category": "case-memory",
        "path": "case_memory/QuantGod_CaseMemoryArtifactManifest.json",
        "contentType": "json",
        "expectedSchemas": ["quantgod.case_memory_artifact_manifest.v1"],
        "required": True,
        "requiresArtifactHashes": True,
        "requiresCaseMemoryPromotionGate": True,
    },
    {
        "artifactId": "productionEvidenceValidationReport",
        "category": "production-validation",
        "path": "production_validation/QuantGod_ProductionEvidenceValidationReport.json",
        "contentType": "json",
        "expectedSchemas": ["quantgod.production_evidence_validation.v1"],
        "required": True,
    },
]


def manifest_path(runtime_dir: Path) -> Path:
    return Path(runtime_dir) / REPORT_DIR / REPORT_FILE
