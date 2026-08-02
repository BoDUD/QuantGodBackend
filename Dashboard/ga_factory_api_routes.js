const strategyGAFactoryApiRoutes = require('./strategy_ga_factory_api_routes');
const { rejectGetTelegramSendQuery } = require('./telegram_preview_contract');

function isGAFactoryPath(requestUrl) {
  const pathname = String(requestUrl || '').split('?')[0];
  return pathname === '/api/ga-factory' || pathname.startsWith('/api/ga-factory/');
}

function rewriteRequest(req) {
  const originalUrl = req.url || '';
  req.url = originalUrl.replace('/api/ga-factory', '/api/strategy-ga-factory');
  return () => {
    req.url = originalUrl;
  };
}

async function handle(req, res, ctx) {
  if (
    rejectGetTelegramSendQuery(
      req,
      res,
      req.url,
      strategyGAFactoryApiRoutes.sendJson,
    )
  ) {
    return;
  }
  const restore = rewriteRequest(req);
  try {
    await strategyGAFactoryApiRoutes.handle(req, res, ctx);
  } finally {
    restore();
  }
}

module.exports = {
  handle,
  isGAFactoryPath,
  sendError: strategyGAFactoryApiRoutes.sendError,
};
