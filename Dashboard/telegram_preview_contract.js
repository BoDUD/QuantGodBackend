const PREVIEW_REASON = 'get_telegram_text_is_preview_only';
const REJECTION_ERROR = 'TELEGRAM_SEND_REJECTED_ON_GET_PREVIEW';

function isTelegramTextPreviewPath(pathname) {
  return String(pathname || '').endsWith('/telegram-text');
}

function normalizeTelegramPreviewPayload(payload) {
  const normalized = payload && typeof payload === 'object' && !Array.isArray(payload)
    ? payload
    : { ok: false, error: 'INVALID_TELEGRAM_PREVIEW_PAYLOAD', payload };
  const originalDelivery = normalized.delivery
    && typeof normalized.delivery === 'object'
    && !Array.isArray(normalized.delivery)
    ? normalized.delivery
    : {};
  const upstreamFailed = normalized.ok === false
    || Boolean(normalized.skipped)
    || Boolean(normalized.parseError)
    || (normalized.exitCode !== undefined && normalized.exitCode !== null && normalized.exitCode !== 0);
  return {
    ...normalized,
    ...(upstreamFailed ? { ok: false } : {}),
    previewOnly: true,
    sendRequested: false,
    sendRejected: false,
    sent: false,
    deliveryOk: false,
    delivery: {
      ...originalDelivery,
      ok: false,
      skipped: true,
      status: 'PREVIEW_ONLY',
      reason: PREVIEW_REASON,
    },
  };
}

function telegramSendQueryRejectedPayload(pathname) {
  return {
    ok: false,
    error: REJECTION_ERROR,
    endpoint: pathname,
    previewOnly: true,
    sendRequested: true,
    sendRejected: true,
    sent: false,
    deliveryOk: false,
    delivery: {
      ok: false,
      skipped: true,
      status: 'REJECTED',
      reason: 'GET telegram-text endpoints never deliver messages; remove the send query parameter',
    },
    safety: {
      readOnlyDataPlane: true,
      advisoryOnly: true,
      dryRunOnly: true,
      telegramCommandExecutionAllowed: false,
      orderSendAllowed: false,
      closeAllowed: false,
      cancelAllowed: false,
      livePresetMutationAllowed: false,
      writesMt5OrderRequest: false,
    },
  };
}

function rejectGetTelegramSendQuery(req, res, url, sendJson) {
  const parsedUrl = url instanceof URL
    ? url
    : new URL(String(url || req.url || '/'), 'http://127.0.0.1');
  if (
    String(req.method || '').toUpperCase() !== 'GET'
    || !isTelegramTextPreviewPath(parsedUrl.pathname)
    || !parsedUrl.searchParams.has('send')
  ) {
    return false;
  }
  sendJson(res, 400, telegramSendQueryRejectedPayload(parsedUrl.pathname));
  return true;
}

module.exports = {
  isTelegramTextPreviewPath,
  normalizeTelegramPreviewPayload,
  rejectGetTelegramSendQuery,
  telegramSendQueryRejectedPayload,
};
