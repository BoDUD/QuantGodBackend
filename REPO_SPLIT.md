# 后端拆分状态

本仓库是 QuantGod 四仓库工作区中的后端成员。

## 本仓库保留内容

- MT5/MQL5 engine、preset、tester 配置。
- Node dashboard/API server。
- Python tools、AI/Governance/ParamLab/HFM Crypto CFD/MT5 bridge。
- 后端 contract tests 与 CI guard。
- 本地启动脚本和受保护的 MT5 live/shadow/backtest 工作流。

## 已迁出内容

- `frontend/` → `BoDUD/QuantGodFrontend`
- `cloudflare/` → `BoDUD/QuantGodInfra`
- 完整 `docs/` → `BoDUD/QuantGodDocs`

## 构建联动

`QuantGodFrontend` 构建输出到 `dist/`。`QuantGodInfra` 的 `sync-frontend-dist` 会把它复制到 `QuantGodBackend/Dashboard/vue-dist`，让后端继续通过 `/vue/` 提供本地 operator workbench。

## 维护规则

后端变更只处理交易证据、API、EA、工具链、测试和安全边界。UI 布局、样式、KlineCharts、Monaco、工作台组件都应在 `QuantGodFrontend` 修改。
