# QuantGod Trading Agent Current System

## Backend Files

- Entry latency: `tools/entry_latency/`, `tools/run_entry_latency.py`
- Automation chain integration: `tools/automation_chain/runner.py`, `tools/automation_chain/telegram_text.py`
- USDJPY policy and cent sampling: `tools/usdjpy_strategy_lab/policy_builder.py`, `tools/usdjpy_strategy_lab/schema.py`
- EA startup guard: `MQL5/Experts/QuantGod_MultiStrategy.mq5`, `MQL5/Presets/QuantGod_MT5_HFM_*.set`
- Strategy Factory intent: `tools/strategy_ga_factory/intent_builder.py`, `tools/run_strategy_ga_factory.py`
- Personality lock: `tools/strategy_ga/personality_lock.py`, `tools/strategy_ga/mutation.py`, `tools/strategy_ga/crossover.py`
- GA Factory reflection report: `runtime/ga_factory/QuantGod_GAFactoryReflectionReport.json`
- Hyperliquid shadow lane: `tools/hyperliquid_shadow_lane/`, `tools/run_hyperliquid_shadow_lane.py`
- API routes: `Dashboard/strategy_ga_factory_api_routes.js`

## Frontend Files

- Automation visibility: `src/components/AutomationChainPanel.vue`, `src/services/automationChainApi.js`
- GA Factory / intent / Hyperliquid shadow UI: `src/components/USDJPYGAFactoryPanel.vue`
- Evolution workspace integration: `src/components/USDJPYEvolutionPanel.vue`
- Strategy Factory service facade: `src/services/strategyGaFactoryApi.js`

## Docs Files

- Strategy Factory and Hyperliquid shadow: `docs/ops/strategy-ga-factory.md`
- Automation chain and latency: `docs/ops/automation-chain-runner.md`
- MT5 startup guard: `docs/ops/mt5-hfm-live-pilot.md`
- USDJPY policy / cent sampling: `docs/ops/usdjpy-strategy-policy-lab.md`
- API contract markdown: `docs/backend/api-contract.md`
- API contract JSON: `docs/contracts/api-contract.json`

## API Endpoints

- `GET /api/strategy-ga-factory/status`
- `POST /api/strategy-ga-factory/build`
- `GET /api/strategy-ga-factory/intent-plan`
- `POST /api/strategy-ga-factory/intent-plan/build?prompt=...`
- `GET /api/strategy-ga-factory/hyperliquid-shadow`
- `POST /api/strategy-ga-factory/hyperliquid-shadow/build?targetAgentUrl=...&targetAgentProfileJson=...`
- `GET /api/automation-chain/status`
- `POST /api/automation-chain/run`

## Regression Tests

Backend:

- `python3 -m unittest discover -s tests -p 'test_entry_latency.py' -v`
- `python3 -m unittest discover -s tests -p 'test_automation_chain.py' -v`
- `python3 -m unittest discover -s tests -p 'test_usdjpy_strategy_lab.py' -v`
- `python3 -m unittest discover -s tests -p 'test_strategy_ga_factory.py' -v`
- `python3 -m unittest discover -s tests -p 'test_hyperliquid_shadow_lane.py' -v`
- `python3 -m unittest discover -s tests -p 'test_mt5_rsi_exit_protection.py' -v`
- `python3 -m unittest discover -s tests -p 'test_preset_schema_validator.py' -v`
- `node --test tests/node/test_automation_chain_guard.mjs`
- `node --test tests/node/test_strategy_ga_factory_guard.mjs`

Frontend:

- `node --test tests/frontend_strategy_ga_factory_guard.test.mjs`
- `node --test tests/frontend_usdjpy_evolution_guard.test.mjs`
- `node --test tests/frontend_automation_chain_guard.test.mjs`
- `npm run build`

Docs:

- `python3 -m unittest discover -s tests -p 'test_docs_quality_gate.py' -v`
- `python3 -m json.tool docs/contracts/api-contract.json >/tmp/qg_api_contract_check.json`
