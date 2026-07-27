(function initializeSubscriptionSources(root, factory) {
  const api = factory();
  if (typeof module === 'object' && module.exports) module.exports = api;
  root.FeedDockSubscriptionSources = api;
})(typeof globalThis !== 'undefined' ? globalThis : this, function subscriptionSourcesFactory() {
  const FALLBACK_SOURCE = Object.freeze({
    id: 'other', label: '其它 RSS', short_label: '其它', description: '添加任意标准 RSS 订阅地址。',
    rss_name: '', placeholder: 'https://example.com/feed.xml', default_feed_url: '', official_url: '', help_url: '',
    hosts: [], catalog_view: '', caution: '请确认 RSS 条目包含磁力链接或可直接下载的种子附件。',
  });

  function normalizeSource(source) {
    if (!source || typeof source !== 'object') return { ...FALLBACK_SOURCE };
    return {
      ...FALLBACK_SOURCE,
      ...source,
      id: String(source.id || 'other').trim().toLowerCase(),
      label: String(source.label || source.id || '其它 RSS').trim(),
      hosts: Array.isArray(source.hosts) ? source.hosts.map((host) => String(host).toLowerCase()) : [],
    };
  }

  function normalizeCatalog(payload) {
    const rows = Array.isArray(payload) ? payload : payload?.sources;
    const catalog = (Array.isArray(rows) ? rows : []).map(normalizeSource);
    if (!catalog.some((source) => source.id === 'other')) catalog.push({ ...FALLBACK_SOURCE });
    return catalog;
  }

  function getSource(catalog, sourceId) {
    const id = String(sourceId || '').trim().toLowerCase();
    return normalizeCatalog(catalog).find((source) => source.id === id)
      || normalizeCatalog(catalog).find((source) => source.id === 'other')
      || { ...FALLBACK_SOURCE };
  }

  function hostMatches(hostname, allowedHost) {
    const host = String(hostname || '').toLowerCase().replace(/\.$/, '');
    const allowed = String(allowedHost || '').toLowerCase().replace(/\.$/, '');
    return Boolean(host && allowed && (host === allowed || host.endsWith(`.${allowed}`)));
  }

  function detectSource(catalog, url) {
    let hostname = '';
    try { hostname = new URL(String(url || '')).hostname; } catch (_) { return getSource(catalog, 'other'); }
    return normalizeCatalog(catalog).find((source) => source.id !== 'other' && source.hosts.some((host) => hostMatches(hostname, host)))
      || getSource(catalog, 'other');
  }

  function canUseDefaultFeed(source) {
    return Boolean(normalizeSource(source).default_feed_url);
  }

  return { FALLBACK_SOURCE, normalizeSource, normalizeCatalog, getSource, detectSource, canUseDefaultFeed, hostMatches };
});
