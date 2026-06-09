from __future__ import annotations

from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

SCHEMA_VERSION = "quantgod.usdjpy_strategy_policy_lab.v1"
STRATEGY_CATALOG_VERSION = "quantgod.usdjpy_strategy_catalog.v1"
FOCUS_SYMBOL = "USDJPYc"
FOCUS_SYMBOL_ALIASES = {"USDJPY", "USDJPYc", "USDJPYm", "USDJPYpro", "USDJPY."}
DEFAULT_STRATEGIES = [
    "RSI_Reversal",
    "MA_Cross",
    "BB_Triple",
    "MACD_Divergence",
    "SR_Breakout",
    "USDJPY_TOKYO_RANGE_BREAKOUT",
    "USDJPY_NIGHT_REVERSION_SAFE",
    "USDJPY_H4_TREND_PULLBACK",
]
NEW_USDJPY_STRATEGIES = [
    "USDJPY_TOKYO_RANGE_BREAKOUT",
    "USDJPY_NIGHT_REVERSION_SAFE",
    "USDJPY_H4_TREND_PULLBACK",
]
STRATEGY_DISPLAY_NAMES = {
    "RSI_Reversal": "RSI 反转",
    "MA_Cross": "均线交叉",
    "BB_Triple": "布林三重过滤",
    "MACD_Divergence": "MACD 背离",
    "SR_Breakout": "支撑阻力突破",
    "USDJPY_TOKYO_RANGE_BREAKOUT": "东京箱体突破",
    "USDJPY_NIGHT_REVERSION_SAFE": "夜盘安全均值回归",
    "USDJPY_H4_TREND_PULLBACK": "H4 趋势回调",
}
DIRECTIONS = ("LONG", "SHORT")

STRATEGY_ALIASES = {
    "RSI_REVERSAL_SHADOW": "RSI_Reversal",
    "USDJPY_RSI_H1_LIVE_CANDIDATE": "RSI_Reversal",
    "QG_RSI_REV_MT5": "RSI_Reversal",
    "BB_TRIPLE_SHADOW": "BB_Triple",
    "BB_TRIPLE_H1_LEGACY_CANDIDATE": "BB_Triple",
    "MACD_DIVERGENCE_H1_LEGACY_CANDIDATE": "MACD_Divergence",
    "MACD_DIVERGENCE_SHADOW": "MACD_Divergence",
    "SR_BREAKOUT_SHADOW": "SR_Breakout",
    "SR_BREAKOUT_H1_LEGACY_CANDIDATE": "SR_Breakout",
}

STATUS_RUNNABLE = "RUNNABLE"
STATUS_WATCH_ONLY = "WATCH_ONLY"
STATUS_INSUFFICIENT_DATA = "INSUFFICIENT_DATA"
STATUS_PAUSED = "PAUSED"

ENTRY_STANDARD = "STANDARD_ENTRY"
ENTRY_OPPORTUNITY = "OPPORTUNITY_ENTRY"
ENTRY_BLOCKED = "BLOCKED"

READ_ONLY_SAFETY = {
    "localOnly": True,
    "focusOnly": True,
    "focusSymbol": FOCUS_SYMBOL,
    "readOnlyDataPlane": True,
    "advisoryOnly": True,
    "dryRunOnly": True,
    "shadowTradingOnly": True,
    "operatorApprovalRequired": False,
    "unattendedLiveExpansionAllowed": True,
    "liveScopeExpansionMode": "autonomous_governance_stage_gated",
    "orderSendAllowed": False,
    "closeAllowed": False,
    "cancelAllowed": False,
    "modifyAllowed": False,
    "livePresetMutationAllowed": False,
    "writesMt5Preset": False,
    "writesMt5OrderRequest": False,
    "telegramCommandExecutionAllowed": False,
    "webhookReceiverAllowed": False,
    "credentialStorageAllowed": False,
}

SECRET_KEYS = {
    "password",
    "passwd",
    "token",
    "api_key",
    "apikey",
    "secret",
    "authorization",
    "bearer",
    "private_key",
    "mnemonic",
}
EXECUTION_KEYS = {
    "orderSendAllowed",
    "closeAllowed",
    "cancelAllowed",
    "modifyAllowed",
    "livePresetMutationAllowed",
    "writesMt5Preset",
    "writesMt5OrderRequest",
    "telegramCommandExecutionAllowed",
    "webhookReceiverAllowed",
    "brokerExecutionAllowed",
}


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def normalize_symbol(symbol: Any) -> str:
    text = str(symbol or "").strip()
    if text in FOCUS_SYMBOL_ALIASES or text.upper().startswith("USDJPY"):
        return FOCUS_SYMBOL
    return text


def normalize_strategy_name(strategy: Any) -> str:
    text = str(strategy or "").strip()
    if not text:
        return "UNKNOWN_STRATEGY"
    upper = text.upper()
    if upper in STRATEGY_ALIASES:
        return STRATEGY_ALIASES[upper]
    for known in DEFAULT_STRATEGIES:
        if upper == known.upper():
            return known
    return text


def is_focus_symbol(symbol: Any) -> bool:
    return normalize_symbol(symbol) == FOCUS_SYMBOL


def direction_cn(direction: Any) -> str:
    value = str(direction or "").strip().upper()
    if value in {"LONG", "BUY", "多", "买", "买入"}:
        return "买入观察"
    if value in {"SHORT", "SELL", "空", "卖", "卖出"}:
        return "卖出观察"
    return "方向待确认"


def status_cn(status: Any) -> str:
    mapping = {
        STATUS_RUNNABLE: "允许运行",
        STATUS_WATCH_ONLY: "仅影子观察",
        STATUS_INSUFFICIENT_DATA: "样本不足",
        STATUS_PAUSED: "暂停",
        ENTRY_STANDARD: "标准入场候选",
        ENTRY_OPPORTUNITY: "机会入场候选",
        ENTRY_BLOCKED: "阻断",
    }
    return mapping.get(str(status or ""), str(status or "未知"))


def assert_no_secret_or_execution_flags(payload: Any, path: str = "root") -> None:
    if isinstance(payload, dict):
        for key, value in payload.items():
            lower = str(key).lower()
            if lower in SECRET_KEYS or any(secret in lower for secret in SECRET_KEYS):
                raise ValueError(f"secret-like field is forbidden at {path}.{key}")
            if key in EXECUTION_KEYS and bool(value):
                raise ValueError(f"truthy execution flag is forbidden at {path}.{key}")
            assert_no_secret_or_execution_flags(value, f"{path}.{key}")
    elif isinstance(payload, list):
        for idx, item in enumerate(payload):
            assert_no_secret_or_execution_flags(item, f"{path}[{idx}]")


@dataclass
class RouteScore:
    symbol: str
    strategy: str
    direction: str
    regime: str = "UNKNOWN"
    timeframe: str = "UNKNOWN"
    sampleCount: int = 0
    winRate: float = 0.0
    avgR: float = 0.0
    avgPips: float = 0.0
    profitFactor: float = 0.0
    mfeP50: float = 0.0
    mfeP70: float = 0.0
    maeP70: float = 0.0
    mfeCaptureRate: float = 0.0
    lossStreak: int = 0
    status: str = STATUS_INSUFFICIENT_DATA
    score: float = 0.0
    reasons: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class PolicyItem:
    symbol: str
    strategy: str
    direction: str
    regime: str
    entryMode: str
    allowed: bool
    recommendedLot: float
    maxLot: float
    score: float
    entryStrictness: str
    exitMode: str
    breakevenDelayR: float
    trailStartR: float
    timeStopBars: int
    reasons: List[str] = field(default_factory=list)
    newsGate: Dict[str, Any] = field(default_factory=dict)
    hardGateStatus: str = "UNKNOWN"
    hardGateReasons: List[str] = field(default_factory=list)
    runtimeFreshnessTier: str = "UNKNOWN"
    signalQuorum: int = 0
    signalQuorumRequired: int = 2
    signalComponents: Dict[str, Any] = field(default_factory=dict)
    tacticalConfirmations: Dict[str, Any] = field(default_factory=dict)
    entryDecision: str = ENTRY_BLOCKED
    spreadGate: Dict[str, Any] = field(default_factory=dict)
    centSamplingGate: Dict[str, Any] = field(default_factory=dict)
    safety: Dict[str, Any] = field(default_factory=lambda: dict(READ_ONLY_SAFETY))

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)
