"""Compact Chinese text rendering for Telegram Gateway observability."""

from __future__ import annotations

from typing import Any

try:
    from telegram_digest import build_digest, clean_text
except ModuleNotFoundError:  # pragma: no cover - package import path
    from tools.telegram_digest import build_digest, clean_text


def gateway_ops_to_chinese_text(status: dict[str, Any]) -> str:
    delivery = status.get("deliveryObservability") if isinstance(status.get("deliveryObservability"), dict) else {}
    pending = int(status.get("pendingCount") or 0)
    sent = int(status.get("actualSentCount") or delivery.get("actualSentCount") or 0)
    failed = int(status.get("failedCount") or delivery.get("failedCount") or 0)
    push_allowed = bool(status.get("pushAllowed"))
    commands_requested = bool(status.get("commandsEnvRequested"))

    reasons: list[str] = []
    if commands_requested:
        conclusion = "检测到命令开关请求，已硬阻断；网关仍只允许出站推送。"
        level = "danger"
        reasons.append("Telegram 命令执行永久关闭。")
        next_action = "把 QG_TELEGRAM_COMMANDS_ALLOWED 保持为 0。"
    elif failed:
        conclusion = f"最近有 {failed} 条推送失败，需要检查通道配置。"
        level = "danger"
        failure_reason = delivery.get("lastFailureReason")
        if failure_reason:
            reasons.append(clean_text(failure_reason))
        next_action = "检查 Bot 配置和最近一次失败记录。"
    elif not push_allowed:
        conclusion = "推送已关闭；队列、去重和审计仍可正常运行。"
        level = "info"
        reasons.append("本机 QG_TELEGRAM_PUSH_ALLOWED=0。")
        next_action = "保持关闭；需要启用时由操作者明确开启推送。"
    elif pending:
        conclusion = f"有 {pending} 条消息等待网关投递。"
        level = "warning"
        next_action = "等待网关按去重和限频规则投递。"
    else:
        conclusion = "推送网关运行正常，目前没有待处理消息。"
        level = "ok"
        next_action = "无需处理。"

    delivery_state = clean_text(delivery.get("stateZh"))
    if delivery_state and delivery_state not in conclusion:
        reasons.append(delivery_state)
    generated_at = (
        delivery.get("lastActualSentAtIso")
        or delivery.get("lastSuppressedAtIso")
        or delivery.get("lastFailureAtIso")
    )
    return build_digest(
        title="Telegram 网关",
        level=level,
        conclusion=conclusion,
        metrics=[
            f"推送 {'开启' if push_allowed else '关闭'}",
            f"待投递 {pending}",
            f"已发送 {sent}",
            f"失败 {failed}",
        ],
        reasons=reasons,
        next_action=next_action,
        generated_at=generated_at,
    )
