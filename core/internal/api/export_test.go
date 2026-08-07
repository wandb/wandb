package api

// Exported for tests so that they exercise the same token exchange
// behavior as production.
const TokenExchangeRetryMax = tokenExchangeRetryMax

var TokenExchangeRetryPolicy = tokenExchangeRetryPolicy
