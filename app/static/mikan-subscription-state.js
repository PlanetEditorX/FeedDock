(function initializeMikanSubscriptionState(root, factory) {
  const api = factory();
  if (typeof module === 'object' && module.exports) module.exports = api;
  root.FeedDockMikanSubscriptionState = api;
}(typeof globalThis !== 'undefined' ? globalThis : this, () => {
  'use strict';

  function positiveInteger(value) {
    const normalized = String(value ?? '').trim();
    if (!/^\d+$/.test(normalized)) return 0;
    const parsed = Number(normalized);
    return Number.isSafeInteger(parsed) && parsed > 0 ? parsed : 0;
  }

  function defaultBaseUrl() {
    const origin = globalThis.location && globalThis.location.origin;
    return origin || 'http://localhost';
  }

  function extractBangumiId(value, baseUrl = defaultBaseUrl()) {
    if (typeof value !== 'string' || !value.trim()) return 0;
    try {
      const url = new URL(value.trim(), baseUrl);
      for (const [key, rawValue] of url.searchParams.entries()) {
        if (key.toLowerCase() === 'bangumiid') return positiveInteger(rawValue);
      }
    } catch (_) {
      // A malformed or unsupported URL is simply not a Mikan subscription.
    }
    return 0;
  }

  function collectSubscribedBangumiIds(subscriptions) {
    const subscribedIds = new Set();
    for (const subscription of subscriptions || []) {
      if (!subscription || typeof subscription !== 'object') continue;
      for (const value of [subscription.rss_url, subscription.backup_rss_url]) {
        const bangumiId = extractBangumiId(value);
        if (bangumiId) subscribedIds.add(bangumiId);
      }
    }
    return subscribedIds;
  }

  function updateCatalogSubscriptionState(catalog, subscribedIds) {
    if (!catalog || typeof catalog !== 'object') return 0;
    const normalizedIds = new Set();
    for (const value of subscribedIds || []) {
      const bangumiId = positiveInteger(value);
      if (bangumiId) normalizedIds.add(bangumiId);
    }
    let changedCount = 0;

    for (const row of catalog.rows || []) {
      for (const item of row.items || []) {
        const subscribed = normalizedIds.has(positiveInteger(item.bangumi_id));
        if (Boolean(item.subscribed) === subscribed) continue;
        item.subscribed = subscribed;
        changedCount += 1;
      }
    }
    return changedCount;
  }

  return Object.freeze({
    extractBangumiId,
    collectSubscribedBangumiIds,
    updateCatalogSubscriptionState,
  });
}));
