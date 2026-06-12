---
name: quantgod-trading-agent
description: Build, audit, and validate QuantGod trading-agent workflows in the local repository. Use when the user asks Codex to create a trading agent from plain language, diagnose slow entries, run Strategy JSON GA Factory/evolution with personality locks, review USDJPY opportunity-entry lane safety, inspect MT5/HFM startup guards, or create a read-only Moss/Hyperliquid shadow-follow lane. This skill is for QuantGodBackend/QuantGodFrontend/QuantGodDocs work and must stay advisory, shadow-only, and no-live-execution unless a separately reviewed future execution lane explicitly exists.
---

# QuantGod Trading Agent

Use this skill to operate the QuantGod trading-agent toolchain safely. Work from the current repository state, inspect files before relying on memory, and preserve existing user changes.

## Safety Invariants

Keep these true in every change:

- Do not place, close, cancel, or modify orders.
- Do not store private keys, wallet mnemonics, API secrets, tokens, or Hyperliquid agent-wallet credentials.
- Do not enable Telegram command execution, webhook execution, or live preset mutation.
- Keep Strategy Factory and GA outputs in `SHADOW`, `FAST_SHADOW`, `TESTER_ONLY`, or `PAPER_LIVE_SIM`.
- Keep Hyperliquid/Moss support read-only unless a separate future execution lane is explicitly designed and reviewed.
- Preserve USDJPY focus for Strategy JSON and MT5 live-pilot work.

## Workflow

1. Inspect current state with `rg`, targeted file reads, and relevant tests.
2. Map the user request to one or more lanes:
   - Plain-language Strategy Factory intent plan.
   - Entry-latency attribution.
   - USDJPY policy / cent opportunity sampling.
   - EA startup guard modes.
   - Strategy JSON GA Factory and personality-lock evolution.
   - Moss/Hyperliquid read-only shadow lane.
3. Implement through existing local CLIs and modules where possible.
4. Update backend tests, frontend guards, API/docs contracts, and operator docs when behavior changes.
5. Run the narrow tests for the touched lane, plus safety guards.

## Command Map

Run commands from `QuantGodBackend` unless noted.

```bash
python3 tools/run_entry_latency.py --runtime-dir ./runtime build --write
python3 tools/run_strategy_ga_factory.py --runtime-dir ./runtime intent-plan --write --prompt "USDJPY 震荡短线，多空都做，低风险，回撤超过百分之十停手"
python3 tools/run_strategy_ga_factory.py --runtime-dir ./runtime build --write
python3 tools/run_hyperliquid_shadow_lane.py --runtime-dir ./runtime build --write --target-agent-url "https://moss.site/agent/agt..."
python3 tools/run_hyperliquid_shadow_lane.py --runtime-dir ./runtime build --write --target-agent-url "https://moss.site/agent/agt..." --target-agent-profile-json ./runtime/moss_agent_profile.json
python3 tools/run_automation_chain.py --runtime-dir ./runtime --symbols USDJPYc loop --interval-seconds 300
python3 -m unittest discover -s tests -p 'test_entry_latency.py' -v
python3 -m unittest discover -s tests -p 'test_usdjpy_strategy_lab.py' -v
python3 -m unittest discover -s tests -p 'test_strategy_ga_factory.py' -v
python3 -m unittest discover -s tests -p 'test_hyperliquid_shadow_lane.py' -v
node --test tests/node/test_automation_chain_guard.mjs
node --test tests/node/test_strategy_ga_factory_guard.mjs
```

Run frontend checks from `QuantGodFrontend`:

```bash
node --test tests/frontend_strategy_ga_factory_guard.test.mjs
node --test tests/frontend_automation_chain_guard.test.mjs
npm run build
```

Run docs checks from `QuantGodDocs`:

```bash
python3 -m unittest discover -s tests -p 'test_docs_quality_gate.py' -v
python3 -m json.tool docs/contracts/api-contract.json >/tmp/qg_api_contract_check.json
```

## Lane Notes

Plain-language Strategy Factory:
- Use `tools/strategy_ga_factory/intent_builder.py`.
- Generated seeds must validate as Strategy JSON and remain shadow-only.
- Intent plans should expose the five-dimensional signal plan and 30+ structured parameters.
- Keep locked personality outside the seed body when needed so the Strategy JSON safety scanner does not reject safe field names.

Entry-latency attribution:
- Use `tools/entry_latency/report.py` and automation-chain integration.
- Attribute slow/missing entry across market data, policy, EA guard, and order-attempt stages.
- Missing evidence must fail closed.

Opportunity entry:
- Use `centSamplingGate` in `tools/usdjpy_strategy_lab/policy_builder.py`.
- `OPPORTUNITY_ENTRY` is for the cent learning account only; USD account is paper mirror unless strict USD deployment gates pass.

EA startup guard:
- `PilotStartupEntryGuardMode` supports `H1_STRICT`, `FAST_WARMUP`, and `BACKTEST_OFF`.
- Live pilot can use `FAST_WARMUP`; backtests should use `BACKTEST_OFF`.
- Startup guard mode cannot bypass spread, news, session, kill switch, position, or policy gates.

GA Factory and evolution:
- Use `tools/strategy_ga/personality_lock.py` for mutation/crossover audits.
- Preserve symbol, strategy family, direction, lane, stage, max lot, and opportunity multiplier.
- If a mutation changes the risk kernel, treat it as a failed personality-lock audit.
- Factory builds should write `QuantGod_GAFactoryReflectionReport.json` so winners, losers, blockers and next-generation scope are visible.

Hyperliquid/Moss shadow:
- Use `tools/hyperliquid_shadow_lane`.
- Accept only `moss.site/agent/agt...` links as target metadata.
- If available, accept a local exported profile JSON for ROI, max drawdown, runtime, liquidation count and trade count.
- Write read-only mapping plans with zero follow ratio and zero max notional.
- Never request wallet signatures, generate private keys, or create agent wallets in this lane; 不授权钱包、不下单。

## References

Read `references/current-system.md` when you need the file map, API map, or test matrix.
