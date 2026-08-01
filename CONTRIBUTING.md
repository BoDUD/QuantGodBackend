# Contributing to QuantGod

## Repository role

`QuantGodBackend` is responsible for: 后端、MT5、Node API、AI、Governance、ParamLab 与测试。

## Repository boundaries

Keep changes inside the correct split repository:

- Backend changes belong in `QuantGodBackend`.
- Frontend UI and API client changes belong in `QuantGodFrontend`.
- Workspace automation and local deployment helpers belong in `QuantGodInfra`.
- Architecture, API contracts, runbooks, phase docs, and maintenance docs belong in `QuantGodDocs`.

## Safety rules

- Do not add trading execution affordances to frontend research or evidence panels.
- Do not bypass Kill Switch, authorization lock, dryRun, Version Gate, or live preset mutation guard.
- Do not store credentials, private account data, tokens, or broker login details in Git.
- Preserve readonly API boundaries unless a later approved design explicitly changes them.
- Preserve Telegram push-only behavior; do not add Telegram trading commands.

## Local checks

Before pushing, run the repository's normal test suite and the governance check:

```bash
python scripts/check_repo_governance.py
```

Run any additional repository-specific checks listed in the README or CI workflow.

## Commit style

Use clear commit messages such as:

```text
fix: harden workspace API client guard
feat: add structured MT5 monitor evidence panel
docs: update API contract runbook
```

## Pull request expectations

A PR should explain scope, touched repository, safety impact, and validation commands. Avoid mixing backend, frontend, infra, and docs changes unless the change is explicitly cross-repository.
