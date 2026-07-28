(function initializeSubscriptionSorting(root, factory) {
  const api = factory();
  if (typeof module === 'object' && module.exports) module.exports = api;
  root.FeedDockSubscriptionSorting = api;
})(typeof globalThis !== 'undefined' ? globalThis : this, function subscriptionSortingFactory() {
  const MODES = Object.freeze(['weekday', 'updated', 'created', 'name', 'rating']);
  const MODE_ALIASES = Object.freeze({ pinyin: 'name' });

  function normalizeMode(value) {
    const mode = String(value || '').trim().toLowerCase();
    const normalized = MODE_ALIASES[mode] || mode;
    return MODES.includes(normalized) ? normalized : 'updated';
  }

  function compareName(left, right) {
    return String(left?.name || '').localeCompare(
      String(right?.name || ''),
      'zh-CN-u-co-pinyin',
      { sensitivity: 'base', numeric: true },
    );
  }

  function compareIsoDateDesc(left, right, field) {
    return String(right?.[field] || '').localeCompare(String(left?.[field] || ''));
  }

  function weekdayIndex(value) {
    const raw = String(value || '').trim();
    if (!/^\d{4}-\d{2}-\d{2}$/.test(raw)) return 99;
    const parsed = new Date(`${raw}T12:00:00Z`);
    if (Number.isNaN(parsed.getTime())) return 99;
    const day = parsed.getUTCDay();
    return day === 0 ? 7 : day;
  }

  function sortSubscriptions(subscriptions, mode) {
    const normalized = normalizeMode(mode);
    return [...(Array.isArray(subscriptions) ? subscriptions : [])].sort((left, right) => {
      if (normalized === 'weekday') {
        return (weekdayIndex(left?.air_date) - weekdayIndex(right?.air_date))
          || compareName(left, right);
      }
      if (normalized === 'created') {
        return compareIsoDateDesc(left, right, 'created_at') || compareName(left, right);
      }
      if (normalized === 'name') return compareName(left, right);
      if (normalized === 'rating') {
        return (Number(right?.metadata_rating || 0) - Number(left?.metadata_rating || 0))
          || compareName(left, right);
      }
      return compareIsoDateDesc(left, right, 'updated_at') || compareName(left, right);
    });
  }

  return { MODES, normalizeMode, weekdayIndex, sortSubscriptions };
});
