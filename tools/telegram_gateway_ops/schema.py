from __future__ import annotations
"""Schema constants for Telegram Gateway observability payloads."""

from typing import Any, Dict, List

try:
    from tools.usdjpy_evidence_os.schema import SAFETY_BOUNDARY
except ModuleNotFoundError:  # pragma: no cover
    from usdjpy_evidence_os.schema import SAFETY_BOUNDARY


AGENT_VERSION = "p4-5"
SCHEMA_OPS_STATUS = "quantgod.telegram_gateway_ops.status.v1"

OPS_TOPICS: List[str] = [
    "DAILY_AUTOPILOT_V2_REPORT",
    "GA_EVOLUTION_REPORT",
    "USDJPY_AUTONOMOUS_AGENT_REPORT",
]

SAFETY: Dict[str, Any] = {
    **SAFETY_BOUNDARY,
    "telegramGatewayOpsOnly": True,
    "pushOnly": True,
    "gatewayReceivesCommands": False,
    "telegramCommandExecutionAllowed": False,
    "orderSendAllowed": False,
    "closeAllowed": False,
    "cancelAllowed": False,
    "livePresetMutationAllowed": False,
    "writesMt5OrderRequest": False,
    "externalMarketRealMoneyAllowed": False,
}
