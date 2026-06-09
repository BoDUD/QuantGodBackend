from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict

AGENT_VERSION = "v2.6"
STATUS_FILE = "QuantGod_GAStatus.json"
LATEST_GENERATION_FILE = "QuantGod_GAGenerationLatest.json"
GENERATION_LEDGER_FILE = "QuantGod_GAGenerationLedger.jsonl"
CANDIDATE_RUNS_FILE = "QuantGod_GACandidateRuns.jsonl"
ELITE_FILE = "QuantGod_GAEliteStrategies.json"
BLOCKER_FILE = "QuantGod_GABlockerSummary.json"
EVOLUTION_PATH_FILE = "QuantGod_GAEvolutionPath.json"
FITNESS_CACHE_FILE = "QuantGod_GAFitnessCache.json"
LINEAGE_FILE = "QuantGod_GALineage.json"
RUN_LIMIT_FILE = "QuantGod_GARunLimiter.json"

DEFAULT_POPULATION_SIZE = 16
DEFAULT_ELITE_COUNT = 4
DEFAULT_MUTATION_RATE = 0.18
DEFAULT_CROSSOVER_RATE = 0.35

SAFETY_BOUNDARY: Dict[str, Any] = {
    "usdJpyOnly": True,
    "strategyJsonOnly": True,
    "orderSendAllowed": False,
    "closeAllowed": False,
    "cancelAllowed": False,
    "livePresetMutationAllowed": False,
    "externalMarketRealMoneyAllowed": False,
    "telegramCommandExecutionAllowed": False,
    "gaDirectLiveAllowed": False,
}


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def ga_dir(runtime_dir: Path) -> Path:
    return runtime_dir / "ga"
