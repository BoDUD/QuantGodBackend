# archive 目录

`archive/` 用来保留后端研究和回测相关的长期材料。这里不是实时运行目录，也不是 MT5/HFM 凭据目录。

## 当前约定

- `backtests/`：后端回测摘要、候选结果和人工复核材料。
- `param-lab/`：ParamLab 历史批次、报告回灌和恢复记录。
- `hfm-crypto/`：HFM Crypto CFD shadow 研究样本、symbol 证据和 Moss 回测映射材料。

## Git 规则

大体积运行产物、临时 HTML、原始 tester 报告和每日 runtime ledger 默认不提交。只有当材料已经整理成复盘证据、治理输入或文档引用时，才应进入 Git。

## 安全边界

不要把账号、密码、token、HFM 交易凭据、Telegram token、OpenRouter key 或钱包私钥放入本目录。
