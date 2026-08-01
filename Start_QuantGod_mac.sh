#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
WORKSPACE_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$SCRIPT_DIR"

load_env_file() {
  local env_file="$1"
  local line
  [[ -f "$env_file" ]] || return 0
  while IFS= read -r line || [[ -n "$line" ]]; do
    line="${line#$'\xef\xbb\xbf'}"
    line="${line#export }"
    [[ -z "$line" || "$line" == \#* || "$line" != *=* ]] && continue
    export "$line"
  done < "$env_file"
}

is_import_snapshot_dir() {
  local candidate="$1"
  [[ "$candidate" == *"runtime/mac_import/mt5_files_snapshot"* ]]
}

assert_shadow_readonly_ea_source() {
  local source_file="$1"
  "$QG_PYTHON_BIN" - "$source_file" <<'PY'
from pathlib import Path
import re
import sys

source_path = Path(sys.argv[1])
source = source_path.read_text(encoding="utf-8-sig")
forbidden = {
    "trade library": r"#include\s*<Trade/Trade\.mqh>",
    "CTrade object": r"\bCTrade\b|\bg_trade\b",
    "order mutation": r"\bOrderSend(?:Async)?\s*\(",
    "CTrade mutation": r"\.(?:Buy|Sell|PositionClose|PositionModify|OrderDelete|OrderModify)\s*\(",
    "raw trade action": r"TRADE_ACTION_(?:DEAL|PENDING|SLTP|MODIFY|REMOVE)",
}
violations = [label for label, pattern in forbidden.items() if re.search(pattern, source)]
if violations:
    print(
        f"Refusing MT5 startup: {source_path.name} contains broker mutation surfaces: "
        + ", ".join(violations),
        file=sys.stderr,
    )
    raise SystemExit(2)
PY
}

patch_ini_section_key() {
  local file="$1"
  local section="$2"
  local key="$3"
  local value="$4"
  "$QG_PYTHON_BIN" - "$file" "$section" "$key" "$value" <<'PY'
from pathlib import Path
import sys

path = Path(sys.argv[1])
section = sys.argv[2]
key = sys.argv[3]
value = sys.argv[4]

encoding = "utf-8"
if path.exists():
    raw = path.read_bytes()
    if raw.startswith(b"\xff\xfe") or raw.startswith(b"\xfe\xff"):
        encoding = "utf-16"
    text = raw.decode(encoding)
else:
    text = ""
lines = text.splitlines()
out = []
in_section = False
seen_section = False
key_written = False
target_section = f"[{section}]".lower()
target_key = key.lower()

for line in lines:
    stripped = line.strip()
    if stripped.startswith("[") and stripped.endswith("]"):
        if in_section and not key_written:
            out.append(f"{key}={value}")
            key_written = True
        in_section = stripped.lower() == target_section
        if in_section:
            seen_section = True
        out.append(line)
        continue

    if in_section and "=" in stripped and stripped.split("=", 1)[0].strip().lower() == target_key:
        out.append(f"{key}={value}")
        key_written = True
    else:
        out.append(line)

if in_section and not key_written:
    out.append(f"{key}={value}")

if not seen_section:
    if out and out[-1] != "":
        out.append("")
    out.append(f"[{section}]")
    out.append(f"{key}={value}")

path.write_text("\n".join(out) + "\n", encoding=encoding)
PY
}

start_screen() {
  local name="$1"
  local log_file="$2"
  local command="$3"
  mkdir -p "$(dirname "$log_file")"
  : > "$log_file"
  if command -v screen >/dev/null 2>&1; then
    quit_screen "$name"
    screen -dmS "$name" /bin/zsh -lc "$command >> '$log_file' 2>&1"
    echo "Started screen: $name"
  else
    /bin/zsh -lc "$command >> '$log_file' 2>&1" &
    echo "Started background process for $name. Log: $log_file"
  fi
}

quit_screen() {
  local name="$1"
  local session
  command -v screen >/dev/null 2>&1 || return 0
  while IFS= read -r session; do
    [[ -n "$session" ]] || continue
    screen -S "$session" -X quit >/dev/null 2>&1 || true
  done < <({ screen -ls 2>/dev/null || true; } | awk -v name="$name" '$1 ~ "^[0-9]+\\." name "$" { print $1 }')
  screen -S "$name" -X quit >/dev/null 2>&1 || true
}

bootout_launch_agent() {
  local label="$1"
  local plist="$HOME/Library/LaunchAgents/${label}.plist"
  command -v launchctl >/dev/null 2>&1 || return 0
  [[ -f "$plist" ]] || return 0
  launchctl bootout "gui/$(id -u)" "$plist" >/dev/null 2>&1 || true
}

load_env_file "$SCRIPT_DIR/.env.local"
load_env_file "$SCRIPT_DIR/.env.usdjpy.local"
load_env_file "$SCRIPT_DIR/.env.auto.local"
load_env_file "$SCRIPT_DIR/.env.telegram.local"
load_env_file "$SCRIPT_DIR/.env.deepseek.local"

if [[ "${QG_STOP_LEGACY_LAUNCH_AGENTS:-1}" == "1" ]]; then
  for label in \
    com.quantgod.backend-api \
    com.quantgod.frontend-dev \
    com.quantgod.usdjpy-history-sync \
    com.quantgod.daily-autopilot \
    com.quantgod.ai-telegram-monitor; do
    bootout_launch_agent "$label"
  done
fi

RUNTIME_CONFIGURED=0
if [[ -n "${QG_RUNTIME_DIR:-}" || -n "${QG_MT5_FILES_DIR:-}" ]]; then
  RUNTIME_CONFIGURED=1
fi

export QG_DASHBOARD_HOST="${QG_DASHBOARD_HOST:-127.0.0.1}"
export QG_DASHBOARD_PORT="${QG_DASHBOARD_PORT:-8080}"
export QG_FRONTEND_HOST="${QG_FRONTEND_HOST:-127.0.0.1}"
export QG_FRONTEND_PORT="${QG_FRONTEND_PORT:-5173}"
export QG_PYTHON_BIN="${QG_PYTHON_BIN:-python3}"
export NODE_OPTIONS="${NODE_OPTIONS:---max-old-space-size=768}"
export QG_RUNTIME_DIR="${QG_RUNTIME_DIR:-./Dashboard}"
export QG_MT5_FILES_DIR="${QG_MT5_FILES_DIR:-./Dashboard}"
export QG_FOCUS_SYMBOL="${QG_FOCUS_SYMBOL:-USDJPYc}"
export QG_ALLOWED_SYMBOLS="${QG_ALLOWED_SYMBOLS:-USDJPYc}"
export QG_DISABLE_NON_FOCUS_SYMBOLS="${QG_DISABLE_NON_FOCUS_SYMBOLS:-1}"
export QG_AUTOMATION_SYMBOLS="${QG_AUTOMATION_SYMBOLS:-USDJPYc}"
export QG_MT5_AI_MONITOR_SYMBOLS="${QG_MT5_AI_MONITOR_SYMBOLS:-USDJPYc}"
export QG_ACCOUNT_MODE="${QG_ACCOUNT_MODE:-cent}"
export QG_ACCOUNT_CURRENCY_UNIT="${QG_ACCOUNT_CURRENCY_UNIT:-USC}"
export QG_CENT_ACCOUNT_ACCELERATION="${QG_CENT_ACCOUNT_ACCELERATION:-1}"
export QG_TELEGRAM_COMMANDS_ALLOWED="${QG_TELEGRAM_COMMANDS_ALLOWED:-0}"
export QG_AGENT_V25_SEND_TELEGRAM="${QG_AGENT_V25_SEND_TELEGRAM:-0}"
export QG_AGENT_OPS_HEALTH_ENABLED="${QG_AGENT_OPS_HEALTH_ENABLED:-1}"
export QG_PRODUCTION_BURN_IN_ENABLED="${QG_PRODUCTION_BURN_IN_ENABLED:-1}"
export QG_PRODUCTION_BURN_IN_INTERVAL_SECONDS="${QG_PRODUCTION_BURN_IN_INTERVAL_SECONDS:-300}"
export QG_PRODUCTION_BURN_IN_SAMPLE_INTERVAL_MINUTES="${QG_PRODUCTION_BURN_IN_SAMPLE_INTERVAL_MINUTES:-5}"
export QG_PRODUCTION_BURN_IN_WINDOW_HOURS="${QG_PRODUCTION_BURN_IN_WINDOW_HOURS:-72}"
export QG_PRODUCTION_BURN_IN_MAX_STALE_MINUTES="${QG_PRODUCTION_BURN_IN_MAX_STALE_MINUTES:-15}"

FRONTEND_DIR="${QG_FRONTEND_ROOT:-$WORKSPACE_ROOT/QuantGodFrontend}"
MT5_APP_PATH="${QG_MT5_APP_PATH:-$HOME/Applications/MetaTrader 5.app}"
MT5_PREFIX="${QG_MT5_WINE_PREFIX:-$HOME/Library/Application Support/net.metaquotes.wine.metatrader5}"
MT5_ROOT="${QG_MT5_ROOT:-$MT5_PREFIX/drive_c/Program Files/MetaTrader 5}"
MT5_MQL5="$MT5_ROOT/MQL5"
MT5_FILES="$MT5_MQL5/Files"
MT5_EXPERTS="$MT5_MQL5/Experts"
MT5_PRESETS="$MT5_MQL5/Presets"
WINE64="$MT5_APP_PATH/Contents/SharedSupport/wine/bin/wine64"
MT5_SHADOW_CONFIG="$MT5_PREFIX/drive_c/qg/QuantGod_MT5_HFM_Shadow_mac.ini"

export QG_MT5_TERMINAL_PATH="${QG_MT5_TERMINAL_PATH:-$MT5_ROOT/terminal64.exe}"
export QG_MT5_PYTHON_BIN="${QG_MT5_PYTHON_BIN:-$QG_PYTHON_BIN}"
export QG_USDJPY_HISTORY_SYNC_ENABLED="${QG_USDJPY_HISTORY_SYNC_ENABLED:-1}"
export QG_USDJPY_HISTORY_INTERVAL_SECONDS="${QG_USDJPY_HISTORY_INTERVAL_SECONDS:-7200}"
export QG_USDJPY_HISTORY_MONTHS="${QG_USDJPY_HISTORY_MONTHS:-12}"
export QG_USDJPY_HISTORY_TIMEFRAMES="${QG_USDJPY_HISTORY_TIMEFRAMES:-M1,M5,M15,H1,H4}"
export QG_USDJPY_HISTORY_MAX_BARS="${QG_USDJPY_HISTORY_MAX_BARS:-300000}"
export QG_USDJPY_HISTORY_MAX_LAG_HOURS="${QG_USDJPY_HISTORY_MAX_LAG_HOURS:-96}"
export QG_USDJPY_MT5_SYMBOL="${QG_USDJPY_MT5_SYMBOL:-USDJPYc}"
export QG_MT5_MAX_BARS="${QG_MT5_MAX_BARS:-1000000}"
export QG_PARAMLAB_HFM_ROOT="${QG_PARAMLAB_HFM_ROOT:-$SCRIPT_DIR/runtime/ParamLab_Tester_Sandbox/live_hfm_placeholder}"
export QG_PARAMLAB_TESTER_ROOT="${QG_PARAMLAB_TESTER_ROOT:-$SCRIPT_DIR/runtime/HFM_MT5_Tester_Isolated}"
export QG_MT5_TESTER_ROOT="${QG_MT5_TESTER_ROOT:-$QG_PARAMLAB_TESTER_ROOT}"

MT5_SHADOW_SCREEN="${QG_MT5_SHADOW_SCREEN:-quantgod-mt5-shadow}"
BACKEND_API_SCREEN="${QG_BACKEND_API_SCREEN:-quantgod-backend-api}"
FRONTEND_SCREEN="${QG_FRONTEND_SCREEN:-quantgod-frontend-dev}"
AGENT_V25_SCREEN="${QG_AGENT_V25_SCREEN:-quantgod-agent-v25}"
AGENT_V25_SUPERVISOR_SCREEN="${QG_AGENT_V25_SUPERVISOR_SCREEN:-quantgod-agent-v25-supervisor}"
HISTORY_SYNC_SCREEN="${QG_USDJPY_HISTORY_SYNC_SCREEN:-quantgod-usdjpy-history-sync}"
LEGACY_DAILY_AUTOPILOT_SCREEN="${QG_DAILY_AUTOPILOT_SCREEN:-quantgod-daily-autopilot}"

RUNTIME_SOURCE="${QG_MAC_RUNTIME_SOURCE:-auto}"
MT5_START_MODE="${QG_MT5_START_MODE:-shadow}"
MT5_START_SYMBOL="${QG_MT5_START_SYMBOL:-USDJPYc}"
BACKEND_API_ENABLED="${QG_BACKEND_API_ENABLED:-1}"
FRONTEND_ENABLED="${QG_FRONTEND_ENABLED:-1}"
AGENT_V25_ENABLED="${QG_AGENT_V25_ENABLED:-1}"
LEGACY_DAILY_AUTOPILOT_ENABLED="${QG_LEGACY_DAILY_AUTOPILOT_ENABLED:-0}"

RUNTIME_IS_IMPORT_SNAPSHOT=0
if is_import_snapshot_dir "$QG_RUNTIME_DIR"; then
  RUNTIME_IS_IMPORT_SNAPSHOT=1
fi

if [[ -d "$MT5_ROOT" && ( "$RUNTIME_SOURCE" == "mt5" || ( "$RUNTIME_SOURCE" == "auto" && ( "$RUNTIME_CONFIGURED" == "0" || "$RUNTIME_IS_IMPORT_SNAPSHOT" == "1" ) ) ) ]]; then
  export QG_RUNTIME_DIR="$MT5_FILES"
  export QG_MT5_FILES_DIR="$MT5_FILES"
fi

case "$MT5_START_MODE" in
  shadow|off)
    ;;
  *)
    echo "Unsupported QG_MT5_START_MODE=$MT5_START_MODE; tracked startup only permits shadow or off." >&2
    exit 2
    ;;
esac

EA_SOURCE="$SCRIPT_DIR/MQL5/Experts/QuantGod_MultiStrategy.mq5"
assert_shadow_readonly_ea_source "$EA_SOURCE"

echo "QuantGod v2.5 Mac one-click launcher"
echo "Backend: $SCRIPT_DIR"
echo "Frontend: $FRONTEND_DIR"
echo "Runtime: $QG_RUNTIME_DIR"
echo "Focus symbol: $QG_FOCUS_SYMBOL"
echo "MT5 start mode: $MT5_START_MODE"
echo "MT5 start symbol: $MT5_START_SYMBOL"
echo "MT5 terminal path: $QG_MT5_TERMINAL_PATH"
echo "MT5 Python bin: $QG_MT5_PYTHON_BIN"
echo "MT5 chart max bars: $QG_MT5_MAX_BARS"
echo "USDJPY history sync: $QG_USDJPY_HISTORY_SYNC_ENABLED every ${QG_USDJPY_HISTORY_INTERVAL_SECONDS}s for ${QG_USDJPY_HISTORY_MONTHS} months, maxLag=${QG_USDJPY_HISTORY_MAX_LAG_HOURS}h"
echo "Node heap cap: $NODE_OPTIONS"
echo "Frontend: http://$QG_FRONTEND_HOST:$QG_FRONTEND_PORT/vue/?workspace=mt5"
echo "Backend API: http://$QG_DASHBOARD_HOST:$QG_DASHBOARD_PORT/vue/"

echo "Maintaining runtime logs..."
maintain_runtime_log_root() {
  local root="$1"
  [[ -n "$root" && -d "$root" ]] || return 0
  "$QG_PYTHON_BIN" "$SCRIPT_DIR/tools/maintain_runtime_logs.py" \
    --runtime-root "$root" || echo "Runtime log maintenance failed for $root"
}

maintain_runtime_logs() {
  local root resolved
  local seen="|"
  local -a roots
  local -a extra_roots
  roots=(
    "${QG_RUNTIME_LOG_ROOT:-$SCRIPT_DIR/runtime}"
    "$SCRIPT_DIR/runtime"
    "${QG_RUNTIME_DIR:-}"
    "${QG_MT5_FILES_DIR:-}"
    "${QG_LAUNCHD_LOG_ROOT:-$HOME/.quantgod/logs}"
  )
  if [[ -n "${QG_RUNTIME_LOG_EXTRA_ROOTS:-}" ]]; then
    IFS=':' read -r -a extra_roots <<< "$QG_RUNTIME_LOG_EXTRA_ROOTS"
    roots+=("${extra_roots[@]}")
  fi
  for root in "${roots[@]}"; do
    [[ -n "$root" && -d "$root" ]] || continue
    resolved="$(cd "$root" && pwd -P 2>/dev/null || printf '%s' "$root")"
    case "$seen" in
      *"|$resolved|"*) continue ;;
    esac
    seen="${seen}${resolved}|"
    maintain_runtime_log_root "$resolved"
  done
}

maintain_runtime_logs

if [[ -d "$MT5_ROOT" ]]; then
  echo "Syncing QuantGod files into MT5..."
  mkdir -p "$MT5_FILES" "$MT5_EXPERTS" "$MT5_PRESETS" "$MT5_PREFIX/drive_c/qg"
  rsync -a Dashboard/vue-dist/ "$MT5_FILES/vue-dist/" || true
  cp Dashboard/dashboard_server.js "$MT5_FILES/dashboard_server.js"
  rsync -a --include='QuantGod_*' --include='*/' --exclude='*' Dashboard/ "$MT5_FILES/"
  if [[ -d "$QG_MT5_FILES_DIR" ]]; then
    SRC_MT5_FILES="$(cd "$QG_MT5_FILES_DIR" && pwd -P)"
    DST_MT5_FILES="$(cd "$MT5_FILES" && pwd -P)"
    if [[ "$SRC_MT5_FILES" != "$DST_MT5_FILES" ]]; then
      rsync -a --include='QuantGod_*' --include='*/' --exclude='*' "$QG_MT5_FILES_DIR/" "$MT5_FILES/"
    fi
  fi
  cp "$EA_SOURCE" "$MT5_EXPERTS/QuantGod_MultiStrategy.mq5"
  cp MQL5/Presets/QuantGod_MT5_HFM_Shadow.set "$MT5_PRESETS/QuantGod_MT5_HFM_Shadow.set"
  "$QG_PYTHON_BIN" tools/hydrate_mt5_shadow_config.py \
    --template MQL5/Config/QuantGod_MT5_HFM_Shadow.ini \
    --target "$MT5_SHADOW_CONFIG" \
    --common-ini "$MT5_ROOT/config/common.ini" \
    --symbol "$MT5_START_SYMBOL" \
    --max-bars "$QG_MT5_MAX_BARS"
  if [[ -f "$MT5_ROOT/config/terminal.ini" ]]; then
    patch_ini_section_key "$MT5_ROOT/config/terminal.ini" "Charts" "MaxBars" "$QG_MT5_MAX_BARS"
  fi

  EA_BUILD_DIR="$MT5_PREFIX/drive_c/qg"
  EA_BUILD_SOURCE="$EA_BUILD_DIR/QuantGod_MultiStrategy.mq5"
  EA_BUILD_OUTPUT="$EA_BUILD_DIR/QuantGod_MultiStrategy.ex5"
  EA_COMPILE_MARKER="$EA_BUILD_DIR/.QuantGod_MultiStrategy.compile-started"
  EA_INSTALLED_OUTPUT="$MT5_EXPERTS/QuantGod_MultiStrategy.ex5"
  EA_DISABLED_OUTPUT="$MT5_EXPERTS/QuantGod_MultiStrategy.ex5.execution-lane-removed"
  EA_INSTALL_TMP="$MT5_EXPERTS/.QuantGod_MultiStrategy.ex5.new.$$"
  rm -f "$EA_BUILD_OUTPUT" "$EA_COMPILE_MARKER" "$EA_INSTALL_TMP"
  if [[ -f "$EA_INSTALLED_OUTPUT" ]]; then
    mv -f "$EA_INSTALLED_OUTPUT" "$EA_DISABLED_OUTPUT"
  fi

  if [[ -x "$WINE64" ]]; then
    echo "Compiling QuantGod_MultiStrategy.mq5 with MetaEditor..."
    cp "$EA_SOURCE" "$EA_BUILD_SOURCE"
    : > "$EA_COMPILE_MARKER"
    set +e
    WINEPREFIX="$MT5_PREFIX" "$WINE64" \
      'C:\Program Files\MetaTrader 5\metaeditor64.exe' \
      '/compile:C:\qg\QuantGod_MultiStrategy.mq5' \
      '/log:C:\qg\compile.log'
    COMPILE_CODE=$?
    set -e
    # MetaEditor may detach from Wine before it flushes the EX5. Poll for a
    # bounded interval and accept only an artifact newer than this run's marker.
    EA_COMPILE_WAIT_SECONDS="${QG_MT5_COMPILE_WAIT_SECONDS:-120}"
    EA_COMPILE_READY=0
    for ((EA_COMPILE_WAITED = 0; EA_COMPILE_WAITED < EA_COMPILE_WAIT_SECONDS; EA_COMPILE_WAITED++)); do
      if [[ -s "$EA_BUILD_OUTPUT" && "$EA_BUILD_OUTPUT" -nt "$EA_COMPILE_MARKER" ]]; then
        EA_COMPILE_READY=1
        break
      fi
      sleep 1
    done
    if [[ "$COMPILE_CODE" -ne 0 || "$EA_COMPILE_READY" != "1" ]]; then
      rm -f "$EA_BUILD_OUTPUT" "$EA_COMPILE_MARKER" "$EA_INSTALL_TMP"
      echo "MetaEditor did not produce a fresh safe QuantGod_MultiStrategy.ex5. Exit code: $COMPILE_CODE" >&2
      echo "Check: $MT5_PREFIX/drive_c/qg/compile.log"
      echo "The previous EA binary remains quarantined as $EA_DISABLED_OUTPUT and MT5 will not be launched." >&2
      exit 3
    fi
    cp "$EA_BUILD_OUTPUT" "$EA_INSTALL_TMP"
    mv -f "$EA_INSTALL_TMP" "$EA_INSTALLED_OUTPUT"
    rm -f "$EA_DISABLED_OUTPUT" "$EA_COMPILE_MARKER"
    echo "Fresh Shadow/ReadOnly EA compiled and atomically installed into MT5 Experts."

    if [[ "${QG_PREPARE_ISOLATED_TESTER:-1}" != "0" ]]; then
      echo "Preparing isolated Strategy Tester root..."
      "$QG_PYTHON_BIN" tools/prepare_isolated_mt5_tester.py \
        --source-root "$MT5_ROOT" \
        --tester-root "$QG_PARAMLAB_TESTER_ROOT" \
        --status "$SCRIPT_DIR/runtime/QuantGod_IsolatedTesterStatus.json" \
        --refresh || echo "Isolated tester preparation failed; AUTO_TESTER_WINDOW will stay locked."
    fi

    if [[ "$MT5_START_MODE" == "off" ]]; then
      echo "MT5 launch skipped because QG_MT5_START_MODE=off."
    else
      echo "Starting MT5 with the read-only HFM shadow config..."
      start_screen "$MT5_SHADOW_SCREEN" "$SCRIPT_DIR/runtime/mt5_hfm_shadow_screen.log" \
        "cd '$MT5_ROOT' && exec env WINEPREFIX='$MT5_PREFIX' '$WINE64' terminal64.exe /portable '/config:C:\\qg\\QuantGod_MT5_HFM_Shadow_mac.ini'"
    fi
  fi
else
  echo "MT5 data folder not found yet: $MT5_ROOT"
  echo "Install/open MetaTrader 5 once, then run this script again."
fi

if [[ -d "$MT5_APP_PATH" && ! -x "$WINE64" ]]; then
  echo "MT5 launch skipped: the bundled compiler is unavailable, so EA provenance cannot be verified." >&2
fi

if [[ "$BACKEND_API_ENABLED" == "1" ]]; then
  start_screen "$BACKEND_API_SCREEN" "$SCRIPT_DIR/runtime/backend_api_screen.log" \
    "cd '$SCRIPT_DIR' && exec node Dashboard/dashboard_server.js"
fi

if [[ "$FRONTEND_ENABLED" == "1" && -d "$FRONTEND_DIR" ]]; then
  start_screen "$FRONTEND_SCREEN" "$SCRIPT_DIR/runtime/frontend_dev_screen.log" \
    "cd '$FRONTEND_DIR' && exec node ./node_modules/vite/bin/vite.js --host '$QG_FRONTEND_HOST' --port '$QG_FRONTEND_PORT'"
fi

if [[ "$AGENT_V25_ENABLED" == "1" ]]; then
  quit_screen "$LEGACY_DAILY_AUTOPILOT_SCREEN"
  # Agent supervisor keeps tools/run_mac_agent_v25_loop.sh --loop alive.
  start_screen "$AGENT_V25_SUPERVISOR_SCREEN" "$SCRIPT_DIR/runtime/agent_v25_supervisor_screen.log" \
    "cd '$SCRIPT_DIR' && exec bash tools/ensure_mac_agent_v25_loop.sh --loop"
fi

if [[ "$QG_USDJPY_HISTORY_SYNC_ENABLED" == "1" ]]; then
  start_screen "$HISTORY_SYNC_SCREEN" "$SCRIPT_DIR/runtime/usdjpy_history_sync_screen.log" \
    "cd '$SCRIPT_DIR' && exec bash tools/run_mac_usdjpy_history_sync_loop.sh --loop"
fi

if [[ "$LEGACY_DAILY_AUTOPILOT_ENABLED" == "1" ]]; then
  start_screen "$LEGACY_DAILY_AUTOPILOT_SCREEN" "$SCRIPT_DIR/runtime/daily_autopilot_legacy_screen.log" \
    "cd '$SCRIPT_DIR' && exec bash tools/run_mac_daily_autopilot.sh --loop"
fi

open "http://$QG_FRONTEND_HOST:$QG_FRONTEND_PORT/vue/?workspace=mt5" || \
  open "http://$QG_DASHBOARD_HOST:$QG_DASHBOARD_PORT/vue/?workspace=mt5" || true

echo "QuantGod v2.5 launcher complete."
echo "Screens: $BACKEND_API_SCREEN, $FRONTEND_SCREEN, $AGENT_V25_SUPERVISOR_SCREEN, $AGENT_V25_SCREEN, $HISTORY_SYNC_SCREEN, $MT5_SHADOW_SCREEN"
