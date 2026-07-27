const notice = document.getElementById('notice');
const subscriptionForm = document.getElementById('subscriptionForm');
const subscriptionPreviewBox = document.getElementById('subscriptionPreview');
const mikanSubscriptionState = window.FeedDockMikanSubscriptionState;
const navigation = window.FeedDockNavigation;
const subscriptionSourceState = window.FeedDockSubscriptionSources;
if (!mikanSubscriptionState) throw new Error('Mikan subscription state module is unavailable');
if (!navigation) throw new Error('Navigation module is unavailable');
if (!subscriptionSourceState) throw new Error('Subscription source module is unavailable');
let subscriptionsById = new Map();
let currentSubscriptions = [];
const selectedSubscriptionIds = new Set();
let subscriptionManagementMode = false;
let currentMikanDetailItem = null;
let currentMikanCatalogData = null;
let currentDownloadRoot = '/media';
let applicationPreferences = null;
let subscriptionSources = subscriptionSourceState.normalizeCatalog([]);
let activeSubscriptionSource = subscriptionSourceState.getSource(subscriptionSources, 'other');
let activeCatalogSource = 'mikan';
let subscriptionSortMode = 'updated';
const mikanWeekdayDrafts = new Map();
const PANEL_STATE_KEY = 'feeddock.panelState.v1';
const MIKAN_WEEKDAY_STATE_KEY = 'feeddock.mikanWeekdayState.v1';

function showAppView(view, options = {}) {
  return navigation.showView(view, options);
}

function setSourceLink(element, url) {
  const value = String(url || '').trim();
  element.classList.toggle('hidden', !value);
  if (value) element.href = value;
  else element.removeAttribute('href');
}

function renderSubscriptionSourceContext(source) {
  activeSubscriptionSource = subscriptionSourceState.normalizeSource(source);
  const context = document.getElementById('subscriptionSourceContext');
  context.dataset.source = activeSubscriptionSource.id;
  document.getElementById('subscriptionSourceBadge').textContent = activeSubscriptionSource.short_label || activeSubscriptionSource.label;
  document.getElementById('subscriptionSourceName').textContent = activeSubscriptionSource.label;
  document.getElementById('subscriptionSourceDescription').textContent = activeSubscriptionSource.description;
  document.getElementById('subscriptionSourceCaution').textContent = activeSubscriptionSource.caution || '';
  setSourceLink(document.getElementById('subscriptionSourceOfficial'), activeSubscriptionSource.official_url);
  setSourceLink(document.getElementById('subscriptionSourceHelp'), activeSubscriptionSource.help_url);
  document.getElementById('useDefaultSourceFeed').classList.toggle('hidden', !subscriptionSourceState.canUseDefaultFeed(activeSubscriptionSource));
  subscriptionForm.elements.rss_url.placeholder = activeSubscriptionSource.placeholder || 'https://example.com/feed.xml';
}

async function loadSubscriptionSources() {
  const payload = await api('/api/subscription-sources');
  subscriptionSources = subscriptionSourceState.normalizeCatalog(payload);
  const currentUrl = subscriptionForm.elements.rss_url.value.trim();
  renderSubscriptionSourceContext(
    currentUrl ? subscriptionSourceState.detectSource(subscriptionSources, currentUrl) : activeSubscriptionSource,
  );
  renderCatalogSourceTabs();
}

function catalogSources() {
  return subscriptionSources.filter((source) => ['mikan', 'anibt', 'ag'].includes(source.id));
}

function renderCatalogSourceTabs() {
  const container = document.getElementById('catalogSourceTabs');
  if (!container) return;
  container.replaceChildren();
  catalogSources().forEach((source) => {
    const button = text('button', source.short_label || source.label, `small secondary${source.id === activeCatalogSource ? ' is-active' : ''}`);
    button.type = 'button';
    button.addEventListener('click', () => openCatalogSource(source.id, { autoLoad: true }));
    container.append(button);
  });
}

function renderCatalogSourceContext() {
  const source = subscriptionSourceState.getSource(subscriptionSources, activeCatalogSource);
  const badge = document.getElementById('catalogSourceBadge');
  badge.textContent = source.short_label || source.label;
  badge.className = `provider-badge ${source.id}`;
  document.getElementById('catalogSourceTitle').textContent = `${source.label} 番剧周历`;
  document.getElementById('catalogSourceDescription').textContent = source.id === 'mikan'
    ? '从 Mikan 季度目录选择番剧和字幕组。'
    : `${source.description} 周历支持本地搜索、缓存读取和强制更新。`;
  renderCatalogSourceTabs();
}

async function openCatalogSource(sourceId, { autoLoad = false } = {}) {
  if (!subscriptionSources.some((item) => item.id === sourceId)) await loadSubscriptionSources();
  activeCatalogSource = ['mikan', 'anibt', 'ag'].includes(sourceId) ? sourceId : 'mikan';
  currentMikanCatalogData = null;
  mikanWeekdayDrafts.clear();
  document.getElementById('mikanCatalog').replaceChildren();
  renderCatalogSourceContext();
  showAppView('add-catalog');
  const state = document.getElementById('mikanCatalogState');
  const source = subscriptionSourceState.getSource(subscriptionSources, activeCatalogSource);
  state.textContent = `点击“读取缓存”加载 ${source.label} 独立缓存；“强制更新”只请求 ${source.label} 原站。`;
  state.className = 'hint';
  if (autoLoad) await loadMikanCatalog(document.getElementById('mikanCatalogForm'), false);
}

async function openSubscriptionEditor(source = 'other') {
  if (!subscriptionSources.some((item) => item.id === source)) await loadSubscriptionSources();
  resetSubscriptionForm();
  const preset = subscriptionSourceState.getSource(subscriptionSources, source);
  renderSubscriptionSourceContext(preset);
  document.getElementById('subscriptionFormTitle').textContent = `添加订阅 · ${preset.label}`;
  setFormValue(subscriptionForm, 'primary_rss_name', preset.rss_name);
  showAppView('add-subscription');
  subscriptionForm.elements.name.focus();
}

function setManagementMode(enabled) {
  subscriptionManagementMode = Boolean(enabled);
  document.body.classList.toggle('subscription-management-mode', subscriptionManagementMode);
  document.getElementById('subscriptionBatchToolbar').classList.toggle('hidden', !subscriptionManagementMode);
  document.getElementById('toggleManagementMode').textContent = subscriptionManagementMode ? '退出批量管理' : '批量管理';
  if (!subscriptionManagementMode) selectedSubscriptionIds.clear();
  renderSubscriptions(currentSubscriptions);
  updateSubscriptionSelectionSummary();
}

function updateSubscriptionSelectionSummary() {
  document.getElementById('selectedSubscriptionCount').textContent = `已选择 ${selectedSubscriptionIds.size} 项`;
  const visible = filteredSubscriptions(currentSubscriptions);
  const allSelected = visible.length > 0 && visible.every((sub) => selectedSubscriptionIds.has(sub.id));
  const selectAll = document.getElementById('selectAllSubscriptions');
  selectAll.checked = allSelected;
  selectAll.indeterminate = !allSelected && visible.some((sub) => selectedSubscriptionIds.has(sub.id));
}

function filteredSubscriptions(subscriptions) {
  const query = String(document.getElementById('subscriptionSearch')?.value || '').trim().toLowerCase();
  const state = document.getElementById('subscriptionStateFilter')?.value || '';
  const filtered = subscriptions.filter((sub) => {
    const haystack = [sub.name, sub.canonical_title, sub.primary_rss_name, sub.rss_url].join(' ').toLowerCase();
    if (query && !haystack.includes(query)) return false;
    if (state === 'enabled' && !sub.enabled) return false;
    if (state === 'disabled' && sub.enabled) return false;
    if (state === 'error' && !sub.last_error) return false;
    return true;
  });
  const pinyin = (left, right) => String(left.name || '').localeCompare(String(right.name || ''), 'zh-CN-u-co-pinyin', { sensitivity: 'base', numeric: true });
  filtered.sort((left, right) => {
    if (subscriptionSortMode === 'rating') {
      return (Number(right.metadata_rating || 0) - Number(left.metadata_rating || 0)) || pinyin(left, right);
    }
    if (subscriptionSortMode === 'pinyin') return pinyin(left, right);
    return String(right.updated_at || '').localeCompare(String(left.updated_at || '')) || pinyin(left, right);
  });
  return filtered;
}


function subscriptionSourceLabel(sub) {
  if (sub.source_type === 'other') return sub.primary_rss_name || sub.source_label || '其它 RSS';
  if (sub.source_label) return sub.source_label;
  const detected = subscriptionSourceState.detectSource(subscriptionSources, sub.rss_url);
  return detected.id === 'other' ? (sub.primary_rss_name || detected.label) : detected.label;
}

function showNotice(message, ok = true) {
  notice.textContent = message;
  notice.className = `notice ${ok ? 'ok' : 'bad'}`;
  window.clearTimeout(showNotice.timer);
  showNotice.timer = window.setTimeout(() => notice.classList.add('hidden'), 7000);
}

async function api(path, options = {}) {
  const response = await fetch(path, {
    headers: { 'Content-Type': 'application/json', ...(options.headers || {}) },
    ...options,
  });
  if (response.status === 401) {
    window.location.replace('/login');
    throw new Error('登录已失效');
  }
  if (response.status === 428) {
    window.location.replace('/change-password');
    throw new Error('请先修改初始密码');
  }
  if (!response.ok) {
    let message = `HTTP ${response.status}`;
    try { message = (await response.json()).detail || message; } catch (_) {}
    throw new Error(message);
  }
  return response.json();
}

function text(tag, value, className = '') {
  const el = document.createElement(tag);
  el.textContent = value ?? '';
  if (className) el.className = className;
  return el;
}

function fmtDate(value) {
  return value ? new Date(value).toLocaleString('zh-CN') : '—';
}

function titleWithYear(title, year) {
  const cleaned = String(title || '').trim().replace(/\s*\(\d{4}\)\s*$/, '');
  return year ? `${cleaned} (${year})` : cleaned;
}

function setFormValue(form, name, value) {
  const element = form.elements[name];
  if (!element) return;
  if (element.type === 'checkbox') element.checked = Boolean(value);
  else element.value = value ?? '';
}

function resetSubscriptionForm() {
  subscriptionForm.reset();
  setFormValue(subscriptionForm, 'subscription_id', '');
  setFormValue(subscriptionForm, 'source_type', '');
  setFormValue(subscriptionForm, 'source_anime_id', '');
  setFormValue(subscriptionForm, 'canonical_key', '');
  setFormValue(subscriptionForm, 'naming_mode', 'auto');
  setFormValue(subscriptionForm, 'media_type', 'tv');
  setFormValue(subscriptionForm, 'metadata_year', 0);
  setFormValue(subscriptionForm, 'tmdb_id', 0);
  setFormValue(subscriptionForm, 'bangumi_id', 0);
  setFormValue(subscriptionForm, 'anilist_id', 0);
  setFormValue(subscriptionForm, 'season_mode', 'title');
  setFormValue(subscriptionForm, 'scrape_mode', 'off');
  setFormValue(subscriptionForm, 'metadata_confirmed', false);
  setFormValue(subscriptionForm, 'metadata_review_skipped', false);
  setFormValue(subscriptionForm, 'season', 1);
  setFormValue(subscriptionForm, 'episode_group', 0);
  setFormValue(subscriptionForm, 'episode_offset', 0);
  setFormValue(subscriptionForm, 'total_episodes', 0);
  setFormValue(subscriptionForm, 'stale_days', 0);
  setFormValue(subscriptionForm, 'total_episodes_source', '');
  setFormValue(subscriptionForm, 'save_path_template', '{base}/{media_folder}/Season {season:02}');
  setFormValue(subscriptionForm, 'file_name_template', '{title} - S{season:02}E{episode:02}');
  setFormValue(subscriptionForm, 'rename_enabled', true);
  setFormValue(subscriptionForm, 'scrape_enabled', false);
  setFormValue(subscriptionForm, 'custom_download_path', currentDownloadRoot);
  setFormValue(subscriptionForm, 'enabled', true);
  const metadataQuery = document.getElementById('metadataSearchQuery');
  metadataQuery.value = '';
  metadataQuery.dataset.subscriptionName = '';
  document.getElementById('metadataSearchResults').textContent = '尚未搜索。';
  document.getElementById('metadataSearchResults').className = 'metadata-results muted';
  document.getElementById('subscriptionFormTitle').textContent = '添加订阅';
  renderSubscriptionSourceContext(subscriptionSourceState.getSource(subscriptionSources, 'other'));
  document.getElementById('saveSubscription').textContent = '保存订阅';
  document.getElementById('cancelSubscriptionEdit').classList.add('hidden');
  subscriptionPreviewBox.textContent = '尚未预览。';
  subscriptionPreviewBox.className = 'preview-box muted';
}

function syncMetadataSearchQuery({ force = false } = {}) {
  const input = document.getElementById('metadataSearchQuery');
  const subscriptionName = subscriptionForm.elements.name.value.trim();
  const previousSubscriptionName = input.dataset.subscriptionName || '';
  if (force || !input.value.trim() || input.value === previousSubscriptionName) {
    input.value = subscriptionName;
    input.dataset.subscriptionName = subscriptionName;
  }
}

function subscriptionPayload({ forPreview = false, formData = null } = {}) {
  const data = formData || new FormData(subscriptionForm);
  const get = (name) => String(data.get(name) || '').trim();
  const integer = (name, fallback = 0) => {
    const value = Number.parseInt(get(name), 10);
    return Number.isFinite(value) ? value : fallback;
  };
  const checkbox = (name) => Boolean(subscriptionForm.elements[name]?.checked);
  const payload = {
    name: get('name'), source_type: get('source_type'), source_anime_id: get('source_anime_id'), canonical_key: get('canonical_key'), reference_title: get('reference_title'), tmdb_title: get('tmdb_title'),
    manual_title: get('manual_title'), naming_mode: get('naming_mode') || 'auto',
    media_type: get('media_type') || 'tv', bgm_url: get('bgm_url'), air_date: get('air_date') || null,
    metadata_year: integer('metadata_year', 0), metadata_source: get('metadata_source'),
    metadata_overview: get('metadata_overview'), poster_url: get('poster_url'), backdrop_url: get('backdrop_url'),
    metadata_confirmed: get('metadata_confirmed') === 'true', metadata_review_skipped: get('metadata_review_skipped') === 'true',
    tmdb_id: integer('tmdb_id', 0),
    bangumi_id: integer('bangumi_id', 0), anilist_id: integer('anilist_id', 0), auto_metadata: checkbox('auto_metadata'),
    season: integer('season', 1), season_mode: get('season_mode') || 'title', primary_rss_name: get('primary_rss_name'), rss_url: get('rss_url'),
    backup_rss_name: get('backup_rss_name'), backup_rss_url: get('backup_rss_url') || null,
    include_keywords: get('include_keywords'), exclude_keywords: get('exclude_keywords'),
    episode_regex: get('episode_regex'), episode_group: integer('episode_group', 0),
    episode_offset: integer('episode_offset', 0), total_episodes: integer('total_episodes', 0),
    total_episodes_locked: checkbox('total_episodes_locked'), total_episodes_source: get('total_episodes_source'),
    rename_enabled: checkbox('rename_enabled'), file_name_template: get('file_name_template') || '{title} - S{season:02}E{episode:02}',
    scrape_enabled: false, scrape_mode: 'off',
    save_path_template: get('save_path_template') || '{base}/{media_folder}/Season {season:02}',
    custom_download_path: get('custom_download_path'), missing_detection: checkbox('missing_detection'),
    only_latest: checkbox('only_latest'), auto_disable_when_complete: checkbox('auto_disable_when_complete'),
    stale_days: integer('stale_days', 0), enabled: checkbox('enabled'),
  };
  if (forPreview) {
    payload.sample_title = get('sample_title');
    if (!payload.rss_url) payload.rss_url = 'https://preview.invalid/feed.xml';
    if (!payload.name) payload.name = payload.manual_title || payload.tmdb_title || payload.reference_title || '未命名订阅';
  }
  return payload;
}

async function loadAuth() {
  const status = await api('/api/auth/status');
  if (!status.authenticated) {
    window.location.replace('/login');
    return;
  }
  if (status.must_change_password) {
    window.location.replace('/change-password');
    return;
  }
  document.getElementById('currentUser').textContent = status.username;
  const loginUser = document.getElementById('loginSettingsUser');
  if (loginUser) loginUser.textContent = status.username;
}

async function loadDashboard() {
  const data = await api('/api/dashboard');
  const values = [data.enabled_subscriptions, data.queued, data.skipped, data.errors];
  document.querySelectorAll('#stats strong').forEach((el, i) => { el.textContent = values[i]; });
}

async function loadConfig() {
  const data = await api('/api/config');
  let qbitState = '未配置';
  if (data.qbit_url) qbitState = data.configured ? data.qbit_url : `${data.qbit_url}（配置不完整）`;
  document.getElementById('configSummary').textContent =
    `轮询 ${data.poll_interval_minutes} 分钟 · qBittorrent ${qbitState} · 保存根目录 ${data.download_path}`;

  // Local values do not access GitHub. Remote release information is only
  // fetched after the user explicitly clicks the check button.
  document.getElementById('currentVersion').textContent = data.app_version || '—';
  document.getElementById('deployedImage').textContent = data.deployed_image || '—';
  document.getElementById('updaterState').textContent = data.updater_configured ? '已启用' : '未启用';
  const catalogState = document.getElementById('mikanCatalogState');
  if (catalogState && !document.getElementById('mikanCatalog').children.length) {
    catalogState.textContent = `首次没有缓存时会请求所选站点的目录数据；之后页面优先读取持久化缓存，已浏览季度默认每 ${data.mikan_cache_hours || 6} 小时后台更新一次。`;
  }
}

async function loadDownloaderSettings() {
  const data = await api('/api/downloader/settings');
  const form = document.getElementById('downloaderForm');
  form.elements.qbit_url.value = data.qbit_url || '';
  form.elements.qbit_username.value = data.qbit_username || '';
  form.elements.qbit_password.value = '';
  form.elements.qbit_password.placeholder = data.qbit_password_configured
    ? '已保存密码；留空表示不修改'
    : '请输入 qBittorrent WebUI 密码';
  form.elements.qbit_category.value = data.qbit_category || 'rss';
  currentDownloadRoot = data.download_path || '/media';
  form.elements.download_path.value = currentDownloadRoot;
  if (!subscriptionForm.elements.custom_download_path.value) subscriptionForm.elements.custom_download_path.value = currentDownloadRoot;
  const metadataForm = document.getElementById('metadataSettingsForm');
  if (metadataForm && !metadataForm.elements.media_local_root.value) metadataForm.elements.media_local_root.value = currentDownloadRoot;
  form.elements.clear_password.checked = false;

  const source = data.source === 'web' ? '网页保存' : 'Compose 环境变量';
  const status = data.configured ? '配置完整' : '尚未配置完整';
  document.getElementById('qbitConfigState').textContent = `${status} · 当前来源：${source}`;
}

function downloaderPayload() {
  const form = document.getElementById('downloaderForm');
  const password = form.elements.qbit_password.value;
  return {
    qbit_url: form.elements.qbit_url.value.trim(),
    qbit_username: form.elements.qbit_username.value.trim(),
    qbit_password: password ? password : null,
    clear_password: form.elements.clear_password.checked,
    qbit_category: form.elements.qbit_category.value.trim() || 'rss',
    download_path: form.elements.download_path.value.trim(),
  };
}

async function saveDownloaderSettings() {
  const result = await api('/api/downloader/settings', {
    method: 'PUT',
    body: JSON.stringify(downloaderPayload()),
  });
  await Promise.all([loadDownloaderSettings(), loadConfig()]);
  return result;
}

function initializeCollapsiblePanels() {
  let states = {};
  try { states = JSON.parse(localStorage.getItem(PANEL_STATE_KEY) || '{}'); } catch (_) {}
  document.querySelectorAll('.panel[data-panel-id]').forEach((panel) => {
    const head = panel.querySelector(':scope > .panel-head');
    if (!head || head.querySelector('.panel-toggle')) return;
    const id = panel.dataset.panelId;
    const collapsed = Boolean(states[id]);
    panel.classList.toggle('is-collapsed', collapsed);
    const button = text('button', collapsed ? '展开' : '收起', 'small secondary panel-toggle');
    button.type = 'button';
    button.setAttribute('aria-expanded', String(!collapsed));
    button.addEventListener('click', () => {
      const next = !panel.classList.contains('is-collapsed');
      panel.classList.toggle('is-collapsed', next);
      button.textContent = next ? '展开' : '收起';
      button.setAttribute('aria-expanded', String(!next));
      let current = {};
      try { current = JSON.parse(localStorage.getItem(PANEL_STATE_KEY) || '{}'); } catch (_) {}
      current[id] = next;
      localStorage.setItem(PANEL_STATE_KEY, JSON.stringify(current));
    });
    head.append(button);
  });
}

async function loadApplicationSettings() {
  const data = await api('/api/application/settings');
  applicationPreferences = data;
  subscriptionSortMode = data.page?.subscription_sort || 'updated';
  const theme = data.page?.theme_color || 'blue';
  document.documentElement.dataset.themeColor = theme;
  try { localStorage.setItem('feeddock-theme-color', theme); } catch (_) {}
  const page = document.getElementById('pageSettingsForm');
  page.elements.theme_color.value = theme;
  page.elements.subscription_sort.value = subscriptionSortMode;
  const downloader = document.getElementById('downloaderForm');
  downloader.elements.retry_count.value = data.download?.retry_count ?? 2;
  downloader.elements.concurrent_limit.value = data.download?.concurrent_limit ?? 3;
  downloader.elements.seeding_minutes.value = data.download?.seeding_minutes ?? -1;
  const automation = document.getElementById('automationSettingsForm');
  automation.elements.rss_enabled.checked = data.rss?.enabled !== false;
  automation.elements.rss_timeout_seconds.value = data.rss?.timeout_seconds ?? 20;
  automation.elements.auto_skip_existing.checked = Boolean(data.rss?.auto_skip_existing);
  automation.elements.auto_disable_complete.checked = Boolean(data.rss?.auto_disable_complete);
  const trackers = document.getElementById('trackersSettingsForm');
  trackers.elements.trackers_enabled.checked = data.trackers?.enabled !== false;
  trackers.elements.trackers_update_url.value = data.trackers?.update_url || 'https://cf.trackerslist.com/best.txt';
  document.getElementById('trackersState').textContent = `已缓存 ${data.trackers?.tracker_count || 0} 个 Tracker${data.trackers?.updated_at ? ` · 更新于 ${fmtDate(data.trackers.updated_at)}` : ''}`;
  renderSubscriptions(currentSubscriptions);
}

function applicationSettingsPayload() {
  const page = document.getElementById('pageSettingsForm');
  const downloader = document.getElementById('downloaderForm');
  const automation = document.getElementById('automationSettingsForm');
  const trackers = document.getElementById('trackersSettingsForm');
  return {
    theme_color: page.elements.theme_color.value,
    subscription_sort: page.elements.subscription_sort.value,
    retry_count: Number(downloader.elements.retry_count.value),
    concurrent_limit: Number(downloader.elements.concurrent_limit.value),
    seeding_minutes: Number(downloader.elements.seeding_minutes.value),
    rss_enabled: automation.elements.rss_enabled.checked,
    rss_timeout_seconds: Number(automation.elements.rss_timeout_seconds.value),
    auto_skip_existing: automation.elements.auto_skip_existing.checked,
    auto_disable_complete: automation.elements.auto_disable_complete.checked,
    trackers_enabled: trackers.elements.trackers_enabled.checked,
    trackers_update_url: trackers.elements.trackers_update_url.value.trim(),
  };
}

async function saveApplicationSettings() {
  const data = await api('/api/application/settings', { method: 'PUT', body: JSON.stringify(applicationSettingsPayload()) });
  applicationPreferences = data;
  await loadApplicationSettings();
  return data;
}

async function loadMetadataSettings() {
  const data = await api('/api/metadata/settings');
  const form = document.getElementById('metadataSettingsForm');
  form.elements.tmdb_read_access_token.value = '';
  form.elements.tmdb_read_access_token.placeholder = data.tmdb_token_configured ? '已保存；留空表示不修改' : '请填写 TMDB Read Access Token';
  form.elements.bangumi_access_token.value = '';
  form.elements.bangumi_access_token.placeholder = data.bangumi_token_configured ? '已保存；留空表示不修改' : '公开查询通常可留空';
  form.elements.metadata_language.value = data.metadata_language || data.language || 'zh-CN';
  form.elements.tmdb_api_base.value = data.tmdb_api_base || 'https://api.themoviedb.org';
  form.elements.tmdb_image_base.value = data.tmdb_image_base || 'https://image.tmdb.org';
  form.elements.auto_scrape_enabled.checked = Boolean(data.auto_scrape_enabled);
  form.elements.follow_days.value = data.follow_days || 14;
  form.elements.bangumi_ini_enabled.checked = Boolean(data.bangumi_ini_enabled);
  form.elements.media_local_root.value = data.media_local_root || currentDownloadRoot;
  form.elements.clear_tmdb_token.checked = false;
  form.elements.clear_bangumi_token.checked = false;
  document.getElementById('metadataConfigState').textContent = `TMDB ${data.tmdb_token_configured ? '已配置' : '未配置'} · NFO/图片刮削 ${data.auto_scrape_enabled ? '已启用' : '未启用'} · bangumi.ini ${data.bangumi_ini_enabled ? '已启用' : '未启用'}`;
}

function metadataSettingsPayload() {
  const form = document.getElementById('metadataSettingsForm');
  return {
    tmdb_read_access_token: form.elements.tmdb_read_access_token.value.trim() || null,
    clear_tmdb_token: form.elements.clear_tmdb_token.checked,
    bangumi_access_token: form.elements.bangumi_access_token.value.trim() || null,
    clear_bangumi_token: form.elements.clear_bangumi_token.checked,
    metadata_language: form.elements.metadata_language.value.trim() || 'zh-CN',
    tmdb_api_base: form.elements.tmdb_api_base.value.trim() || 'https://api.themoviedb.org',
    tmdb_image_base: form.elements.tmdb_image_base.value.trim() || 'https://image.tmdb.org',
    auto_scrape_enabled: form.elements.auto_scrape_enabled.checked,
    follow_days: Number(form.elements.follow_days.value),
    bangumi_ini_enabled: form.elements.bangumi_ini_enabled.checked,
    media_local_root: form.elements.media_local_root.value.trim(),
    emby_url: '',
    emby_api_key: null,
    clear_emby_api_key: true,
    tmm_url: '',
    tmm_api_key: null,
    clear_tmm_api_key: true,
    tmm_enabled: false,
  };
}

async function applyMetadataCandidateToForm(candidate) {
  const season = Number.parseInt(subscriptionForm.elements.season.value || '1', 10) || 0;
  const seasonMode = subscriptionForm.elements.season_mode.value || 'title';
  const queryTitle = subscriptionForm.elements.name.value.trim() || candidate.title || '';
  const params = new URLSearchParams({ provider: candidate.provider, metadata_id: String(candidate.id), media_type: candidate.media_type || 'tv', season: String(season), season_mode: seasonMode, query_title: queryTitle });
  const detail = await api(`/api/metadata/detail?${params}`);
  setFormValue(subscriptionForm, 'media_type', detail.media_type || 'tv');
  setFormValue(subscriptionForm, 'season', detail.recommended_season || detail.season || season || 1);
  setFormValue(subscriptionForm, 'metadata_year', detail.year || 0);
  setFormValue(subscriptionForm, 'metadata_source', detail.provider);
  setFormValue(subscriptionForm, 'metadata_overview', detail.overview || '');
  setFormValue(subscriptionForm, 'poster_url', detail.poster_url || '');
  setFormValue(subscriptionForm, 'backdrop_url', detail.backdrop_url || '');
  if (detail.air_date) setFormValue(subscriptionForm, 'air_date', detail.air_date);
  if (!subscriptionForm.elements.total_episodes_locked.checked && detail.total_episodes > 0) {
    setFormValue(subscriptionForm, 'total_episodes', detail.total_episodes);
    setFormValue(subscriptionForm, 'total_episodes_source', detail.provider);
  }
  const displayTitle = titleWithYear(detail.title, detail.year);
  if (detail.provider === 'tmdb') {
    setFormValue(subscriptionForm, 'tmdb_id', detail.id);
    setFormValue(subscriptionForm, 'tmdb_title', displayTitle);
    setFormValue(subscriptionForm, 'naming_mode', 'tmdb');
  } else if (detail.provider === 'bangumi') {
    setFormValue(subscriptionForm, 'bangumi_id', detail.id);
    setFormValue(subscriptionForm, 'reference_title', displayTitle);
    setFormValue(subscriptionForm, 'bgm_url', detail.detail_url || `https://bangumi.tv/subject/${detail.id}`);
    if (!subscriptionForm.elements.tmdb_id.value || subscriptionForm.elements.tmdb_id.value === '0') setFormValue(subscriptionForm, 'naming_mode', 'bangumi');
  } else {
    setFormValue(subscriptionForm, 'anilist_id', detail.id);
    setFormValue(subscriptionForm, 'reference_title', displayTitle);
    if (!subscriptionForm.elements.tmdb_id.value || subscriptionForm.elements.tmdb_id.value === '0') setFormValue(subscriptionForm, 'naming_mode', 'anilist');
  }
  setFormValue(subscriptionForm, 'name', displayTitle);
  setFormValue(subscriptionForm, 'metadata_confirmed', true);
  setFormValue(subscriptionForm, 'metadata_review_skipped', false);
  const seasons = (detail.available_seasons || []).map(row => `S${String(row.season_number).padStart(2, '0')} ${row.name || ''}`).join('、');
  showNotice(`已读取 ${detail.provider.toUpperCase()}；采用第 ${detail.recommended_season || detail.season || 1} 季；总集数 ${detail.total_episodes || '未知'}${seasons ? `；可用季度 ${seasons}` : ''}`);
}

function renderMetadataResults(results) {
  const container = document.getElementById('metadataSearchResults');
  container.replaceChildren();
  container.className = 'metadata-results';
  if (!results.length) { container.append(text('p', '没有找到匹配条目。', 'empty')); return; }
  results.forEach((candidate) => {
    const card = document.createElement('article'); card.className = 'metadata-card';
    if (candidate.poster_url) { const img = document.createElement('img'); img.src = candidate.poster_url; img.loading = 'lazy'; img.alt = ''; card.append(img); }
    const body = document.createElement('div'); body.className = 'metadata-card-body';
    const heading = document.createElement('div'); heading.className = 'metadata-card-title';
    heading.append(text('strong', titleWithYear(candidate.title || candidate.original_title, candidate.year)));
    heading.append(text('span', `${candidate.provider.toUpperCase()} · ${candidate.year || '年份未知'} · 匹配 ${(Number(candidate.score || 0) * 100).toFixed(0)}%`, 'muted'));
    body.append(heading);
    if (candidate.original_title && candidate.original_title !== candidate.title) body.append(text('span', `原名：${candidate.original_title}`, 'muted'));
    if (candidate.overview) body.append(text('p', candidate.overview.slice(0, 180), 'metadata-overview'));
    const actions = document.createElement('div'); actions.className = 'card-actions';
    const choose = text('button', '选择此条目'); choose.type = 'button'; choose.addEventListener('click', async () => { choose.disabled = true; try { await applyMetadataCandidateToForm(candidate); } catch (error) { showNotice(error.message, false); } finally { choose.disabled = false; } }); actions.append(choose);
    if (candidate.detail_url) actions.append(externalLink('查看来源', candidate.detail_url));
    body.append(actions); card.append(body); container.append(card);
  });
}

async function loadGlobalRules() {
  const data = await api('/api/rules/global');
  document.getElementById('globalRulesForm').elements.exclude_rules.value = data.exclude_rules || '';
}

async function loadUpdateStatus(showResult = false) {
  const data = await api('/api/update/status');
  document.getElementById('currentVersion').textContent = data.current_version || '—';
  document.getElementById('latestVersion').textContent = data.latest_version || '—';
  document.getElementById('deployedImage').textContent = data.deployed_image || '—';
  document.getElementById('updaterState').textContent = data.updater_configured ? '已启用' : '未启用';
  document.getElementById('versionSummary').textContent = data.message || '未获取到版本信息';

  const releaseLink = document.getElementById('releaseLink');
  if (data.release_url) {
    releaseLink.href = data.release_url;
    releaseLink.classList.remove('hidden');
  } else releaseLink.classList.add('hidden');

  const apply = document.getElementById('applyUpdate');
  if (data.update_available && data.updater_configured) apply.classList.remove('hidden');
  else apply.classList.add('hidden');

  if (showResult) {
    const ok = !data.message.includes('失败') && !data.message.includes('上限');
    showNotice(data.message, ok);
  }
}

function applyDiscoveryPreset(preset) {
  if (!preset) return;
  resetSubscriptionForm();
  const fields = [
    'name', 'source_type', 'source_anime_id', 'canonical_key', 'reference_title', 'tmdb_title', 'bgm_url', 'air_date', 'season', 'season_mode',
    'primary_rss_name', 'rss_url', 'backup_rss_name', 'backup_rss_url',
    'include_keywords', 'exclude_keywords', 'episode_regex', 'episode_group',
    'episode_offset', 'total_episodes', 'save_path_template', 'custom_download_path',
    'missing_detection', 'only_latest', 'auto_disable_when_complete', 'stale_days', 'enabled', 'sample_title', 'bangumi_id',
  ];
  fields.forEach((field) => setFormValue(subscriptionForm, field, preset[field]));
  syncMetadataSearchQuery({ force: true });
  document.getElementById('subscriptionFormTitle').textContent = `添加订阅：${preset.name || '未命名番剧'}`;
  subscriptionPreviewBox.textContent = preset.sample_title
    ? `已带入样本标题：${preset.sample_title}\n请点击“预览规则和路径”确认集数与保存位置。`
    : '已带入 RSS，请补充规则后点击“预览规则和路径”。';
  subscriptionPreviewBox.className = 'preview-box muted';
  closeMikanModal();
  showAppView('add-subscription');
  searchMetadata({ automatic: true });
  showNotice('已填入订阅表单，正在自动搜索元数据');
}

function externalLink(label, href) {
  const link = text('a', label);
  link.href = href;
  link.target = '_blank';
  link.rel = 'noreferrer noopener';
  return link;
}

async function copyText(value) {
  try {
    await navigator.clipboard.writeText(value);
  } catch (_) {
    const area = document.createElement('textarea');
    area.value = value;
    area.style.position = 'fixed';
    area.style.opacity = '0';
    document.body.append(area);
    area.select();
    document.execCommand('copy');
    area.remove();
  }
  showNotice('RSS 地址已复制');
}

function closeMikanModal() {
  document.getElementById('mikanDetailModal').classList.add('hidden');
  document.body.classList.remove('modal-open');
}

function openMikanModal(title) {
  document.getElementById('mikanDetailTitle').textContent = title || '番剧详情';
  document.getElementById('mikanDetailBody').replaceChildren(text('p', '正在读取字幕组和 RSS…', 'muted'));
  document.getElementById('mikanDetailModal').classList.remove('hidden');
  document.body.classList.add('modal-open');
}

function cacheStatusText(data) {
  const statusLabels = {
    cache: '本地缓存',
    cache_miss_fetched: '首次拉取并缓存',
    force_refreshed: '刚刚强制更新',
    cache_migrated: '旧缓存已自动修复',
    legacy_cache_refresh_failed: '旧缓存修复失败，暂时使用旧数据',
    stale_cache_refresh_failed: '更新失败，暂时使用旧缓存',
  };
  const parts = [statusLabels[data.cache_status] || '本地缓存'];
  if (data.cached_at) parts.push(`缓存时间 ${fmtDate(data.cached_at)}`);
  if (data.next_refresh_at) parts.push(`下次后台刷新 ${fmtDate(data.next_refresh_at)}`);
  if (data.is_stale) parts.push('等待后台刷新');
  if (data.refresh_error) parts.push(`上次刷新失败：${data.refresh_error}`);
  return parts.join(' · ');
}

function normalizeCatalogIdentityTitle(value) {
  return String(value || '')
    .normalize('NFKC')
    .toLocaleLowerCase()
    .replace(/[\s\-‐‑‒–—―_:：·・~～!！?？,，.。/\\|()（）\[\]【】{}]+/g, '');
}

function subscriptionMatchesCatalogItem(subscription, item) {
  const itemKey = String(item.canonical_key || '').trim();
  const subscriptionKey = String(subscription.canonical_key || '').trim();
  if (itemKey && subscriptionKey && itemKey === subscriptionKey) return true;

  const subjectId = Number(item.subject_id || 0);
  if (subjectId > 0 && Number(subscription.bangumi_id || 0) === subjectId) return true;

  const itemSourceId = String(item.source_anime_id || '').trim();
  if (
    itemSourceId
    && String(subscription.source_type || '') === activeCatalogSource
    && String(subscription.source_anime_id || '').trim() === itemSourceId
  ) return true;

  const aliases = new Set(
    [item.title, item.title_original, item.title_english, ...(item.aliases || [])]
      .map(normalizeCatalogIdentityTitle)
      .filter(Boolean),
  );
  return [subscription.name, subscription.reference_title, subscription.manual_title, subscription.tmdb_title]
    .map(normalizeCatalogIdentityTitle)
    .filter(Boolean)
    .some((value) => aliases.has(value));
}

function syncMikanCatalogSubscriptionState(subscriptions) {
  if (!currentMikanCatalogData) return 0;
  let changedCount = 0;
  const currentSourceLabel = subscriptionSourceState.getSource(subscriptionSources, activeCatalogSource).label;
  currentMikanCatalogData.rows.forEach((row) => row.items.forEach((item) => {
    const matches = subscriptions.filter((subscription) => subscriptionMatchesCatalogItem(subscription, item));
    const sourceLabels = [];
    matches.forEach((subscription) => {
      const label = subscriptionSourceState.getSource(
        subscriptionSources,
        subscription.source_type || 'other',
      ).label;
      if (!sourceLabels.includes(label)) sourceLabels.push(label);
    });
    const subscribedHere = matches.some(
      (subscription) => String(subscription.source_type || '') === activeCatalogSource,
    );
    const otherLabels = sourceLabels.filter((label) => label !== currentSourceLabel);
    const badge = subscribedHere
      ? `✓ 已订阅${otherLabels.length ? ` · ${otherLabels.join('、')} 也已订阅` : ''}`
      : (sourceLabels.length ? `${sourceLabels.join('、')} 已订阅` : '');
    const next = {
      subscribed: matches.length > 0,
      subscribed_here: subscribedHere,
      subscribed_sources: sourceLabels,
      subscription_badge: badge,
    };
    if (
      Boolean(item.subscribed) !== next.subscribed
      || Boolean(item.subscribed_here) !== next.subscribed_here
      || String(item.subscription_badge || '') !== next.subscription_badge
      || JSON.stringify(item.subscribed_sources || []) !== JSON.stringify(next.subscribed_sources)
    ) {
      Object.assign(item, next);
      changedCount += 1;
    }
  }));
  if (changedCount) renderMikanCatalog(currentMikanCatalogData);
  return changedCount;
}

function renderMikanDetail(detail) {
  const container = document.getElementById('mikanDetailBody');
  container.replaceChildren();
  const source = subscriptionSourceState.getSource(subscriptionSources, detail.provider || activeCatalogSource);
  const summary = document.createElement('div');
  summary.className = 'mikan-detail-summary';
  const summaryText = document.createElement('div');
  summaryText.append(text('strong', `${detail.groups.length} 个可用 RSS`));
  summaryText.append(text('span', cacheStatusText(detail), 'muted cache-meta'));
  summary.append(summaryText);
  const summaryActions = document.createElement('div');
  summaryActions.className = 'card-actions';
  const refreshButton = text('button', '强制更新资源', 'small secondary');
  refreshButton.type = 'button';
  refreshButton.addEventListener('click', async () => {
    if (!currentMikanDetailItem) return;
    refreshButton.disabled = true; refreshButton.textContent = '正在更新…';
    try { await openMikanDetail(currentMikanDetailItem, true); showNotice(`${source.label} 资源缓存已更新`); }
    finally { refreshButton.disabled = false; refreshButton.textContent = '强制更新资源'; }
  });
  summaryActions.append(refreshButton);
  if (detail.detail_url) summaryActions.append(externalLink(`打开 ${source.label} 页面`, detail.detail_url));
  summary.append(summaryActions); container.append(summary);
  if (!detail.groups.length) {
    container.append(text('p', `当前条目无法生成 ${source.label} RSS，可能缺少站点所需的番剧 ID。`, 'empty'));
    return;
  }
  const list = document.createElement('div'); list.className = 'mikan-rss-list';
  for (const group of detail.groups) {
    const row = document.createElement('article'); row.className = 'mikan-rss-row';
    const info = document.createElement('div'); info.className = 'mikan-rss-info';
    info.append(text('h3', group.name)); info.append(text('code', group.rss_url, 'rss-code'));
    if (group.preview_error) info.append(text('span', `资源预览失败：${group.preview_error}`, 'muted error-text'));
    if (Array.isArray(group.entries) && group.entries.length) {
      const preview = document.createElement('div'); preview.className = 'source-resource-preview';
      group.entries.forEach((entry) => {
        const line = document.createElement('div'); line.className = 'source-resource-entry';
        line.append(text('span', entry.title || '未命名资源'));
        if (entry.source_url) line.append(externalLink('详情', entry.source_url));
        preview.append(line);
      });
      info.append(preview);
    }
    const actions = document.createElement('div'); actions.className = 'card-actions';
    const subscribe = text('button', '订阅', 'small'); subscribe.type = 'button'; subscribe.addEventListener('click', () => applyDiscoveryPreset(group.preset));
    const copy = text('button', '复制 RSS', 'small secondary'); copy.type = 'button'; copy.addEventListener('click', () => copyText(group.rss_url));
    actions.append(subscribe, copy); if (group.detail_url) actions.append(externalLink('站点页面', group.detail_url));
    row.append(info, actions); list.append(row);
  }
  container.append(list);
}

async function openMikanDetail(item, forceRefresh = false) {
  currentMikanDetailItem = item;
  const source = subscriptionSourceState.getSource(subscriptionSources, activeCatalogSource);
  document.getElementById('catalogDetailBadge').textContent = source.short_label || source.label;
  document.getElementById('catalogDetailBadge').className = `provider-badge ${source.id}`;
  openMikanModal(item.title);
  try {
    let detail;
    if (activeCatalogSource === 'mikan') {
      const params = new URLSearchParams({ base_url: item.base_url || '', title: item.title || '' });
      const path = forceRefresh ? `/api/discovery/mikan/${item.bangumi_id}/refresh?${params}` : `/api/discovery/mikan/${item.bangumi_id}?${params}`;
      detail = await api(path, forceRefresh ? { method: 'POST' } : {});
    } else {
      const params = new URLSearchParams({
        title: item.title || '', subject_id: String(item.subject_id || 0),
        source_anime_id: String(item.source_anime_id || ''), mikan_id: String(item.mikan_id || 0),
        original_title: item.title_original || '', english_title: item.title_english || '',
        aliases: (item.aliases || []).join('\n'), force_refresh: forceRefresh ? 'true' : 'false',
      });
      detail = await api(`/api/discovery/catalog/${activeCatalogSource}/detail?${params}`);
    }
    document.getElementById('mikanDetailTitle').textContent = detail.title;
    renderMikanDetail(detail); return detail;
  } catch (error) {
    document.getElementById('mikanDetailBody').replaceChildren(text('p', error.message, 'error-text')); throw error;
  }
}

function mikanWeekdayKey(data, row) {
  return `${activeCatalogSource}|${data.year}|${data.season}|${row.weekday}`;
}

function getMikanWeekdayCollapsed(key) {
  try { return Boolean(JSON.parse(localStorage.getItem(MIKAN_WEEKDAY_STATE_KEY) || '{}')[key]); }
  catch (_) { return false; }
}

function setMikanWeekdayCollapsed(key, collapsed) {
  let states = {};
  try { states = JSON.parse(localStorage.getItem(MIKAN_WEEKDAY_STATE_KEY) || '{}'); } catch (_) {}
  states[key] = collapsed;
  localStorage.setItem(MIKAN_WEEKDAY_STATE_KEY, JSON.stringify(states));
}

function createMikanCard(item, { editing = false, hiddenDraft = false, onToggle = null } = {}) {
  const card = document.createElement(editing ? 'article' : 'button');
  if (!editing) card.type = 'button';
  card.className = 'mikan-anime-card';
  if (item.subscribed) card.classList.add('is-subscribed');
  if (editing) card.classList.add('is-filter-editing');
  if (hiddenDraft) card.classList.add('is-filter-hidden');
  if (!editing) {
    card.disabled = item.available === false;
    if (item.available !== false) card.addEventListener('click', () => openMikanDetail(item));
  }

  const cover = document.createElement('div');
  cover.className = 'mikan-cover';
  const coverSource = item.cover_proxy_url || item.cover_url;
  if (coverSource) {
    const image = document.createElement('img');
    image.src = coverSource;
    image.alt = item.title;
    image.loading = 'lazy';
    image.decoding = 'async';
    image.width = 66;
    image.height = 88;
    image.referrerPolicy = 'no-referrer';
    image.addEventListener('error', () => {
      // The proxy already performs local-first cache lookup and remote fallback.
      // Do not bypass it with a direct Mikan request when an image fails.
      image.remove();
      cover.append(text('span', item.title.slice(0, 1) || '番'));
    });
    cover.append(image);
  } else cover.append(text('span', item.title.slice(0, 1) || '番'));

  const info = document.createElement('div');
  info.className = 'mikan-anime-info';
  const titleRow = document.createElement('div');
  titleRow.className = 'mikan-anime-title-row';
  titleRow.append(text('strong', item.title));
  if (item.subscribed) titleRow.append(text('span', item.subscription_badge || '✓ 已订阅', 'mikan-subscribed-badge'));
  info.append(titleRow);
  if (item.update_at) info.append(text('span', item.update_at, 'muted'));
  info.append(text(
    'span',
    editing ? (hiddenDraft ? '保存后隐藏' : '当前显示') : (item.action_text || (activeCatalogSource === 'mikan' ? '点击查看字幕组 RSS' : '点击查看 RSS 与资源')),
    'catalog-card-action',
  ));
  card.append(cover, info);

  if (editing) {
    const label = document.createElement('label');
    label.className = 'mikan-filter-check';
    const checkbox = document.createElement('input');
    checkbox.type = 'checkbox';
    checkbox.checked = hiddenDraft;
    checkbox.setAttribute('aria-label', `隐藏 ${item.title}`);
    const caption = text('span', '隐藏');
    const applyValue = () => {
      card.classList.toggle('is-filter-hidden', checkbox.checked);
      const action = card.querySelector('.catalog-card-action');
      if (action) action.textContent = checkbox.checked ? '保存后隐藏' : '当前显示';
      if (onToggle) onToggle(checkbox.checked);
    };
    checkbox.addEventListener('change', applyValue);
    card.addEventListener('click', (event) => {
      if (event.target === checkbox || event.target === label || label.contains(event.target)) return;
      checkbox.checked = !checkbox.checked;
      applyValue();
    });
    label.append(checkbox, caption);
    card.append(label);
  }
  return card;
}

async function saveCatalogWeekdayPreferences(data, row, hiddenKeys) {
  const items = row.items.map((item) => ({
    canonical_key: item.canonical_key,
    title: item.title || '',
    bangumi_id: Number(item.subject_id || 0),
    hidden: hiddenKeys.has(item.canonical_key),
    reason: '',
  })).filter((item) => item.canonical_key);
  await api('/api/discovery/preferences/hidden', {
    method: 'PUT',
    body: JSON.stringify({ items }),
  });
  if (activeCatalogSource === 'mikan') {
    const hiddenBangumiIds = row.items
      .filter((item) => hiddenKeys.has(item.canonical_key))
      .map((item) => Number(item.bangumi_id || item.mikan_id || 0))
      .filter((value) => value > 0);
    await api('/api/discovery/mikan/catalog/filters', {
      method: 'PUT',
      body: JSON.stringify({
        year: Number(data.year),
        season: data.season,
        weekday: row.weekday,
        hidden_bangumi_ids: hiddenBangumiIds,
      }),
    });
  }
  row.items.forEach((item) => { item.hidden = hiddenKeys.has(item.canonical_key); });
  row.hidden_count = row.items.filter((item) => item.hidden).length;
  if (currentMikanCatalogData) {
    currentMikanCatalogData.hidden_count = currentMikanCatalogData.rows.reduce(
      (sum, currentRow) => sum + currentRow.items.filter((item) => item.hidden).length,
      0,
    );
  }
  return new Set(hiddenKeys);
}

function renderMikanCatalog(data) {
  currentMikanCatalogData = data;
  const container = document.getElementById('mikanCatalog');
  const state = document.getElementById('mikanCatalogState');
  container.replaceChildren();

  const totalCount = data.rows.reduce((sum, row) => sum + row.items.length, 0);
  const hiddenCount = data.rows.reduce(
    (sum, row) => sum + row.items.filter((item) => item.hidden).length,
    0,
  );
  const visibleCount = totalCount - hiddenCount;
  if (!totalCount) {
    const emptyMessage = data.query
      ? `${data.year} ${data.season}没有匹配“${data.query}”的番剧。`
      : `${data.year} ${data.season}没有解析到番剧。`;
    state.textContent = `${emptyMessage} · ${cacheStatusText(data)}`;
    state.className = 'hint';
    return;
  }

  const hiddenSummary = hiddenCount ? ` · 已隐藏 ${hiddenCount} 部` : '';
  const sourceLabel = subscriptionSourceState.getSource(subscriptionSources, activeCatalogSource).label;
  const periodSummary = data.period_notice ? ` · ${data.period_notice}` : '';
  state.textContent = `${sourceLabel} · ${data.year} ${data.season} · ${data.rows.length} 个播出日 · 显示 ${visibleCount}/${totalCount} 部${hiddenSummary} · ${cacheStatusText(data)}${periodSummary}${data.attribution ? ` · ${data.attribution}` : ""}`;
  state.className = 'hint';

  for (const row of data.rows) {
    const key = mikanWeekdayKey(data, row);
    const editing = mikanWeekdayDrafts.has(key);
    const draft = mikanWeekdayDrafts.get(key) || new Set();
    const hiddenInRow = row.items.filter((item) => item.hidden).length;
    const visibleItems = editing ? row.items : row.items.filter((item) => !item.hidden);

    const section = document.createElement('section');
    section.className = 'mikan-weekday-section';
    if (editing) section.classList.add('is-filter-editing');

    const heading = document.createElement('div');
    heading.className = 'mikan-weekday-head';
    const titleBox = document.createElement('div');
    titleBox.className = 'mikan-weekday-title';
    titleBox.append(text('h3', row.weekday));
    const countText = editing
      ? `${row.items.length} 部 · 已选择隐藏 ${draft.size} 部`
      : `${row.items.length - hiddenInRow} 部显示${hiddenInRow ? ` · ${hiddenInRow} 部已隐藏` : ''}`;
    titleBox.append(text('span', countText, 'muted'));

    const actions = document.createElement('div');
    actions.className = 'mikan-weekday-actions';
    if (editing) {
      const showAll = text('button', '本周全部显示', 'small secondary');
      showAll.type = 'button';
      showAll.addEventListener('click', async () => {
        showAll.disabled = true;
        try {
          await saveCatalogWeekdayPreferences(data, row, new Set());
          mikanWeekdayDrafts.delete(key);
          renderMikanCatalog(data);
          showNotice(`${row.weekday}的全部番剧已恢复显示`);
        } catch (error) {
          showNotice(error.message, false);
          showAll.disabled = false;
        }
      });

      const cancel = text('button', '取消', 'small secondary');
      cancel.type = 'button';
      cancel.addEventListener('click', () => {
        mikanWeekdayDrafts.delete(key);
        renderMikanCatalog(data);
      });

      const save = text('button', '保存过滤', 'small');
      save.type = 'button';
      save.addEventListener('click', async () => {
        save.disabled = true;
        try {
          await saveCatalogWeekdayPreferences(data, row, draft);
          mikanWeekdayDrafts.delete(key);
          renderMikanCatalog(data);
          showNotice(`${row.weekday}过滤设置已保存`);
        } catch (error) {
          showNotice(error.message, false);
          save.disabled = false;
        }
      });
      actions.append(showAll, cancel, save);
    } else {
      const edit = text('button', '编辑过滤', 'small secondary');
      edit.type = 'button';
      edit.disabled = Boolean(data.query);
      if (data.query) edit.title = '请先清空标题搜索，再编辑完整星期过滤';
      edit.addEventListener('click', () => {
        mikanWeekdayDrafts.set(
          key,
          new Set(row.items.filter((item) => item.hidden).map((item) => item.canonical_key).filter(Boolean)),
        );
        renderMikanCatalog(data);
      });
      actions.append(edit);
    }
    const collapsed = getMikanWeekdayCollapsed(key);
    const collapse = text('button', collapsed ? '展开本周' : '收起本周', 'small secondary');
    collapse.type = 'button';
    collapse.addEventListener('click', () => {
      setMikanWeekdayCollapsed(key, !getMikanWeekdayCollapsed(key));
      renderMikanCatalog(data);
    });
    actions.append(collapse);
    heading.append(titleBox, actions);

    const grid = document.createElement('div');
    grid.className = 'mikan-anime-grid';
    if (collapsed) grid.classList.add('hidden');
    if (!visibleItems.length) {
      const empty = text(
        'p',
        editing
          ? '本周没有番剧。'
          : `本周 ${hiddenInRow} 部番剧已全部隐藏，点击“编辑过滤”可以恢复。`,
        'mikan-weekday-empty',
      );
      grid.append(empty);
    } else {
      visibleItems.forEach((item) => {
        const canonicalKey = item.canonical_key;
        grid.append(createMikanCard(item, {
          editing,
          hiddenDraft: draft.has(canonicalKey),
          onToggle: (hidden) => {
            if (hidden) draft.add(canonicalKey);
            else draft.delete(canonicalKey);
            renderMikanCatalog(data);
          },
        }));
      });
    }
    section.append(heading, grid);
    container.append(section);
  }
}

function initializeCatalogSelectors() {
  const yearSelect = document.getElementById('catalogYear');
  const now = new Date();
  const currentYear = now.getFullYear();
  for (let year = currentYear + 1; year >= 2010; year -= 1) {
    const option = document.createElement('option');
    option.value = String(year);
    option.textContent = String(year);
    option.selected = year === currentYear;
    yearSelect.append(option);
  }
  const month = now.getMonth() + 1;
  const season = month <= 3 ? '冬' : month <= 6 ? '春' : month <= 9 ? '夏' : '秋';
  document.getElementById('catalogSeason').value = season;
}

async function loadMikanCatalog(form, forceRefresh = false) {
  mikanWeekdayDrafts.clear();
  const loadButton = document.getElementById('loadMikanCatalog');
  const refreshButton = document.getElementById('forceRefreshMikanCatalog');
  const activeButton = forceRefresh ? refreshButton : loadButton;
  const state = document.getElementById('mikanCatalogState');
  const year = form.elements.year.value;
  const season = form.elements.season.value;
  const query = form.elements.query.value.trim();
  loadButton.disabled = true;
  refreshButton.disabled = true;
  activeButton.textContent = forceRefresh ? '正在强制更新…' : '正在读取缓存…';
  const source = subscriptionSourceState.getSource(subscriptionSources, activeCatalogSource);
  state.textContent = forceRefresh
    ? `正在更新 ${source.label} 的 ${year} ${season}番剧周历…`
    : `正在读取 ${source.label} 的 ${year} ${season}缓存…`;
  state.className = 'hint';
  try {
    const params = new URLSearchParams({ year, season });
    if (query) params.set('q', query);
    const path = activeCatalogSource === 'mikan'
      ? (forceRefresh ? `/api/discovery/mikan/catalog/refresh?${params}` : `/api/discovery/mikan/catalog?${params}`)
      : (forceRefresh ? `/api/discovery/catalog/${activeCatalogSource}/refresh?${params}` : `/api/discovery/catalog/${activeCatalogSource}?${params}`);
    const data = await api(path, forceRefresh ? { method: 'POST' } : {});
    renderMikanCatalog(data);
    if (forceRefresh) showNotice(`${source.label} 番剧周历缓存已更新`);
  } catch (error) {
    if (!document.getElementById('mikanCatalog').children.length) {
      document.getElementById('mikanCatalog').replaceChildren();
    }
    state.textContent = error.message;
    state.className = 'hint error-text';
  } finally {
    loadButton.disabled = false;
    refreshButton.disabled = false;
    loadButton.textContent = '读取缓存';
    refreshButton.textContent = '强制更新';
  }
}

function populateSubscriptionForm(sub) {
  const fields = [
    'name', 'source_type', 'source_anime_id', 'canonical_key', 'reference_title', 'tmdb_title', 'manual_title', 'naming_mode', 'media_type',
    'bgm_url', 'air_date', 'metadata_year', 'metadata_source', 'metadata_overview', 'poster_url', 'backdrop_url', 'metadata_confirmed', 'metadata_review_skipped', 'tmdb_id', 'bangumi_id', 'anilist_id', 'auto_metadata', 'season', 'season_mode',
    'primary_rss_name', 'rss_url', 'backup_rss_name', 'backup_rss_url',
    'include_keywords', 'exclude_keywords', 'episode_regex', 'episode_group',
    'episode_offset', 'total_episodes', 'total_episodes_locked', 'total_episodes_source',
    'rename_enabled', 'file_name_template', 'scrape_enabled', 'scrape_mode', 'save_path_template',
    'custom_download_path', 'missing_detection', 'only_latest', 'auto_disable_when_complete', 'stale_days', 'enabled',
  ];
  fields.forEach((field) => setFormValue(subscriptionForm, field, sub[field]));
  syncMetadataSearchQuery({ force: true });
  setFormValue(subscriptionForm, 'subscription_id', sub.id);
  setFormValue(subscriptionForm, 'sample_title', sub.reference_title || sub.name);
  renderSubscriptionSourceContext(subscriptionSourceState.getSource(subscriptionSources, sub.source_type || 'other'));
  document.getElementById('subscriptionFormTitle').textContent = `编辑订阅：${sub.name}`;
  document.getElementById('saveSubscription').textContent = '保存修改';
  document.getElementById('cancelSubscriptionEdit').classList.remove('hidden');
  subscriptionPreviewBox.textContent = '请点击“预览规则和路径”确认修改后的结果。';
  subscriptionPreviewBox.className = 'preview-box muted';
  showAppView('add-subscription');
}

function renderSubscriptions(data) {
  const container = document.getElementById('subscriptions');
  const visibleSubscriptions = filteredSubscriptions(data);
  container.replaceChildren();
  if (!data.length) {
    const empty = document.createElement('div'); empty.className = 'empty-state';
    empty.append(text('h3', '还没有订阅'));
    empty.append(text('p', '从 Mikan、ANI.BT 或 Anime Garden 原站番剧目录选择作品，也可以手动添加其它 RSS。', 'muted'));
    const actions = document.createElement('div'); actions.className = 'form-actions';
    ['mikan', 'anibt', 'ag'].forEach((sourceId, index) => {
      const source = subscriptionSourceState.getSource(subscriptionSources, sourceId);
      const button = text('button', source.short_label || source.label, index ? 'secondary' : '');
      button.type = 'button'; button.addEventListener('click', () => openCatalogSource(sourceId, { autoLoad: true }).catch((error) => showNotice(error.message, false))); actions.append(button);
    });
    const other = text('button', '其它 RSS', 'secondary'); other.type = 'button'; other.addEventListener('click', () => openSubscriptionEditor('other').catch((error) => showNotice(error.message, false)));
    actions.append(other); empty.append(actions); container.append(empty);
    updateSubscriptionSelectionSummary();
    return;
  }
  if (!visibleSubscriptions.length) {
    container.append(text('p', '没有符合当前筛选条件的订阅。', 'empty'));
    updateSubscriptionSelectionSummary();
    return;
  }
  for (const sub of visibleSubscriptions) {
    const card = document.createElement('article');
    card.className = `subscription-card metadata-subscription-card${selectedSubscriptionIds.has(sub.id) ? ' is-selected' : ''}`;
    const selector = document.createElement('input'); selector.type = 'checkbox'; selector.className = 'subscription-select';
    selector.checked = selectedSubscriptionIds.has(sub.id); selector.setAttribute('aria-label', `选择 ${sub.name}`);
    selector.addEventListener('change', () => {
      if (selector.checked) selectedSubscriptionIds.add(sub.id); else selectedSubscriptionIds.delete(sub.id);
      card.classList.toggle('is-selected', selector.checked); updateSubscriptionSelectionSummary();
    });
    card.append(selector);
    if (sub.poster_url) {
      const img = document.createElement('img');
      img.className = 'subscription-poster'; img.src = sub.poster_url; img.loading = 'lazy'; img.decoding = 'async';
      img.alt = `${sub.canonical_title || sub.name} 海报`; card.append(img);
    }
    const content = document.createElement('div'); content.className = 'subscription-card-content';
    content.append(text('span', subscriptionSourceLabel(sub), 'subscription-source-label'));
    const titleRow = document.createElement('div'); titleRow.className = 'subscription-title';
    titleRow.append(text('h3', sub.canonical_title || sub.name));
    if (Number(sub.metadata_rating || 0) > 0) titleRow.append(text('span', `★ ${Number(sub.metadata_rating).toFixed(1)}`, 'rating-badge'));
    titleRow.append(text('span', sub.last_error ? '异常' : sub.enabled ? '启用' : '停用', `badge ${sub.last_error ? 'error' : sub.enabled ? 'queued' : 'skipped'}`)); content.append(titleRow);
    if (sub.metadata_overview) content.append(text('p', sub.metadata_overview, 'subscription-overview'));
    const details = document.createElement('details'); details.className = 'subscription-details';
    details.append(text('summary', '订阅详情'));
    const meta = document.createElement('div'); meta.className = 'subscription-meta';
    meta.append(text('span', `原订阅名：${sub.name}`));
    meta.append(text('span', `媒体目录：${sub.media_folder || '—'}`));
    meta.append(text('span', `评分：${Number(sub.metadata_rating || 0) > 0 ? Number(sub.metadata_rating).toFixed(1) : '—'}`));
    meta.append(text('span', `来源：${sub.metadata_source || (sub.metadata_review_skipped ? '已跳过' : '未确认')} · TMDB ${sub.tmdb_id || '—'} · Bangumi ${sub.bangumi_id || '—'} · AniList ${sub.anilist_id || '—'}`));
    meta.append(text('span', `季 ${sub.season}（${sub.season_mode || 'manual'}） · 总集数 ${sub.total_episodes || '未知'}（${sub.total_episodes_source || '未同步'}${sub.total_episodes_locked ? '，已锁定' : ''}）`));
    meta.append(text('span', `下载根目录：${sub.custom_download_path || currentDownloadRoot} · 模板：${sub.save_path_template}`));
    meta.append(text('span', `命名：${sub.rename_enabled ? sub.file_name_template : '关闭'} · 完结自动停用：${sub.auto_disable_when_complete ? '开启' : '关闭'} · 未更新告警：${sub.stale_days ? `${sub.stale_days} 天` : '关闭'}`));
    meta.append(text('span', `主 RSS：${sub.primary_rss_name || '未命名'} · ${sub.rss_url}`));
    details.append(meta);
    details.append(text('p', `上次元数据同步：${fmtDate(sub.metadata_last_synced_at)} ｜ 上次检查：${fmtDate(sub.last_checked_at)}${sub.last_error ? ` ｜ ${sub.last_error}` : ''}`, `${sub.last_error ? 'error-text' : 'muted'} subscription-activity`));
    content.append(details);
    const controls = document.createElement('div'); controls.className = 'card-actions';
    const edit = text('button', '编辑', 'secondary'); edit.addEventListener('click', () => populateSubscriptionForm(sub));
    const sync = text('button', '同步元数据', 'secondary'); sync.addEventListener('click', async () => { try { await api(`/api/subscriptions/${sub.id}/metadata/sync`, { method: 'POST', body: JSON.stringify({ provider: 'auto' }) }); showNotice('元数据和总集数已同步'); await reloadAll(); } catch (error) { showNotice(error.message, false); } });
    const toggle = text('button', sub.enabled ? '停用' : '启用', 'secondary'); toggle.addEventListener('click', async () => { await api(`/api/subscriptions/${sub.id}`, { method: 'PATCH', body: JSON.stringify({ enabled: !sub.enabled }) }); showNotice('订阅状态已更新'); await reloadAll(); });
    const remove = text('button', '删除', 'danger'); remove.addEventListener('click', async () => { if (!window.confirm(`确定删除“${sub.name}”及其历史记录吗？`)) return; await api(`/api/subscriptions/${sub.id}`, { method: 'DELETE' }); selectedSubscriptionIds.delete(sub.id); if (subscriptionForm.elements.subscription_id.value === String(sub.id)) resetSubscriptionForm(); showNotice('订阅已删除'); await reloadAll(); });
    controls.append(edit, sync, toggle, remove); content.append(controls); card.append(content); container.append(card);
  }
  updateSubscriptionSelectionSummary();
}

async function loadSubscriptions() {
  const data = await api('/api/subscriptions');
  currentSubscriptions = data;
  subscriptionsById = new Map(data.map((sub) => [String(sub.id), sub]));
  for (const id of [...selectedSubscriptionIds]) if (!data.some((sub) => sub.id === id)) selectedSubscriptionIds.delete(id);
  syncMikanCatalogSubscriptionState(data);
  renderSubscriptions(data);
}

async function loadItems() {
  const status = document.getElementById('statusFilter').value;
  const data = await api(`/api/items?limit=100${status ? `&status=${encodeURIComponent(status)}` : ''}`);
  const tbody = document.getElementById('items'); tbody.replaceChildren();
  if (!data.length) { const row = document.createElement('tr'); const cell = text('td', '暂无记录'); cell.colSpan = 7; row.append(cell); tbody.append(row); return; }
  for (const item of data) {
    const row = document.createElement('tr'); row.append(text('td', fmtDate(item.created_at)));
    const titleCell = document.createElement('td');
    if (item.source_url) { const link = text('a', item.title); link.href = item.source_url; link.target = '_blank'; link.rel = 'noreferrer noopener'; titleCell.append(link); } else titleCell.textContent = item.title;
    row.append(titleCell); row.append(text('td', item.episode || '—'));
    const statusCell = document.createElement('td'); statusCell.append(text('span', ({ queued: '已推送', scheduled: '等待定时推送', skipped: '已跳过', error: '错误', discovered: '发现' })[item.status] || item.status, `badge ${item.status}`));
    if (item.status === 'queued') statusCell.append(text('small', ` ${item.download_progress || 0}%`, 'muted')); row.append(statusCell);
    const handling = [
      item.rename_status || (item.desired_name ? '等待处理' : '未启用'),
      item.desired_name || '',
      item.rename_message || '',
      item.scrape_message ? `刮削：${item.scrape_message}` : '',
      item.trackers_message ? `Trackers：${item.trackers_message}` : '',
    ].filter(Boolean).join('\n');
    row.append(text('td', handling, item.rename_status === 'error' || item.scrape_status === 'error' || item.trackers_status === 'error' ? 'error-text' : '')); row.append(text('td', item.reason || '—'));
    const actionCell = document.createElement('td');
    if (item.status === 'error') { const retry = text('button', '重试下载', 'small secondary'); retry.addEventListener('click', async () => { const result = await api(`/api/items/${item.id}/retry`, { method: 'POST' }); showNotice(result.message, result.ok); await reloadAll(); }); actionCell.append(retry); }
    else if (item.scrape_status === 'error' || item.trackers_status === 'error') { const retry = text('button', '重试处理', 'small secondary'); retry.addEventListener('click', async () => { const result = await api('/api/actions/normalize-torrents', { method: 'POST' }); showNotice(result.message || '处理完成', result.ok); await reloadAll(); }); actionCell.append(retry); }
    row.append(actionCell); tbody.append(row);
  }
}

async function loadLogSettings() {
  const settings = await api('/api/logs/settings');
  const select = document.getElementById('logLevelSetting');
  if (select) select.value = settings.level || 'INFO';
  const path = document.getElementById('logFilePath');
  if (path) path.textContent = `文件日志：${settings.file || '/data/logs/feeddock.log'}`;
}

async function loadLogs() {
  const data = await api('/api/logs?limit=100');
  const container = document.getElementById('logs');
  container.replaceChildren();
  if (!data.length) {
    container.append(text('p', '暂无日志。', 'empty'));
    return;
  }
  for (const log of data) {
    const row = document.createElement('div');
    row.className = `log-row log-${String(log.level || 'INFO').toLowerCase()}`;
    row.append(text('time', fmtDate(log.created_at)));
    row.append(text('span', log.level, `badge ${log.level === 'ERROR' ? 'error' : log.level === 'DEBUG' ? 'scheduled' : 'queued'}`));
    row.append(text('strong', log.message));
    if (log.details) {
      const details = document.createElement('details');
      details.className = 'log-details';
      if (log.level === 'ERROR') details.open = true;
      details.append(text('summary', log.level === 'ERROR' ? '错误详情（已展开）' : '查看详细内容'));
      details.append(text('pre', log.details));
      row.append(details);
    }
    container.append(row);
  }
}

async function loadSystemStatus() {
  const data = await api('/api/system/status');
  document.getElementById('systemActionState').textContent = data.message;
  document.getElementById('restartSystem').disabled = !data.restart_supported;
  document.getElementById('shutdownSystem').disabled = !data.shutdown_supported;
}

async function reloadAll() {
  try {
    await loadAuth();
    await Promise.all([
      loadDashboard(), loadConfig(), loadApplicationSettings(), loadDownloaderSettings(), loadMetadataSettings(), loadGlobalRules(), loadSubscriptionSources(),
      loadSubscriptions(), loadItems(), loadLogs(), loadLogSettings(), loadAutomationSettings(), loadProxySettings(), loadNotificationSettings(), loadSystemStatus(),
    ]);
  } catch (error) {
    showNotice(error.message, false);
  }
}

function downloadJson(payload, filename) {
  const blob = new Blob([`${JSON.stringify(payload, null, 2)}\n`], { type: 'application/json' });
  const url = URL.createObjectURL(blob);
  const link = document.createElement('a');
  link.href = url; link.download = filename; document.body.append(link); link.click(); link.remove();
  URL.revokeObjectURL(url);
}

async function exportSubscriptionData(ids = []) {
  const params = new URLSearchParams();
  ids.forEach((id) => params.append('ids', String(id)));
  const payload = await api(`/api/subscriptions/export${params.size ? `?${params}` : ''}`);
  const stamp = new Date().toISOString().slice(0, 10);
  downloadJson(payload, `feeddock-subscriptions-${stamp}.json`);
  showNotice(`已导出 ${payload.subscriptions.length} 条订阅`);
}

function closeSubscriptionImportModal() {
  document.getElementById('subscriptionImportModal').classList.add('hidden');
  document.body.classList.remove('modal-open');
}

function openSubscriptionImportModal({ collection = false } = {}) {
  const title = document.getElementById('subscriptionImportTitle');
  const hint = document.getElementById('subscriptionImportHint');
  title.textContent = collection ? '添加合集' : '导入订阅';
  hint.textContent = collection
    ? 'FeedDock 将合集作为一组订阅定义批量添加。可粘贴订阅数组，或选择 FeedDock 导出的 JSON。'
    : '选择 FeedDock 导出的 JSON 文件，或直接粘贴 JSON。';
  document.getElementById('subscriptionImportModal').classList.remove('hidden');
  document.body.classList.add('modal-open');
}

async function importSubscriptionData() {
  const raw = document.getElementById('subscriptionImportJson').value.trim();
  if (!raw) throw new Error('请先选择 JSON 文件或粘贴订阅 JSON');
  let parsed;
  try { parsed = JSON.parse(raw); } catch (error) { throw new Error(`JSON 格式错误：${error.message}`); }
  const subscriptions = Array.isArray(parsed) ? parsed : parsed.subscriptions;
  if (!Array.isArray(subscriptions) || !subscriptions.length) throw new Error('JSON 中没有 subscriptions 数组');
  const result = await api('/api/subscriptions/import', {
    method: 'POST',
    body: JSON.stringify({ subscriptions, conflict: document.getElementById('subscriptionImportConflict').value }),
  });
  closeSubscriptionImportModal();
  document.getElementById('subscriptionImportJson').value = '';
  document.getElementById('subscriptionImportFile').value = '';
  selectedSubscriptionIds.clear();
  await reloadAll();
  showAppView('subscriptions');
  showNotice(`导入完成：新增 ${result.created}，更新 ${result.updated}，跳过 ${result.skipped}`);
}

async function runSubscriptionBatch(action) {
  const ids = [...selectedSubscriptionIds];
  if (!ids.length) { showNotice('请先选择订阅', false); return; }
  if (action === 'delete' && !window.confirm(`确认删除选中的 ${ids.length} 条订阅及其历史记录？`)) return;
  const result = await api('/api/subscriptions/batch', { method: 'POST', body: JSON.stringify({ ids, action }) });
  selectedSubscriptionIds.clear();
  await reloadAll();
  showNotice(`批量操作完成：处理 ${result.affected} 条订阅`);
}


async function revealSavedSecret(input, secretName) {
  if (input.type === 'text') { input.type = 'password'; return; }
  if (!input.value) {
    const data = await api(`/api/secrets/${secretName}`);
    input.value = data.value || '';
  }
  input.type = 'text';
}

function initializePasswordToggles() {
  const mappings = {
    qbit_password: 'qbit_password', tmdb_read_access_token: 'tmdb_read_access_token',
    bangumi_access_token: 'bangumi_access_token', proxy_url: 'proxy_url',
    notification_telegram_bot_token: 'notification_telegram_bot_token',
    notification_bark_device_key: 'notification_bark_device_key',
    notification_webhook_url: 'notification_webhook_url',
    notification_webhook_headers_json: 'notification_webhook_headers_json',
  };
  Object.entries(mappings).forEach(([name, secret]) => {
    const input = document.querySelector(`[name="${name}"]`);
    if (!input || input.parentElement.classList.contains('password-field')) return;
    const wrapper = document.createElement('span'); wrapper.className = 'password-field';
    input.parentNode.insertBefore(wrapper, input); wrapper.append(input);
    const button = text('button', '👁', 'password-toggle'); button.type = 'button'; button.setAttribute('aria-label', '显示或隐藏已保存内容');
    button.addEventListener('click', async () => { try { await revealSavedSecret(input, secret); } catch (error) { showNotice(error.message, false); } });
    wrapper.append(button);
  });
}

async function loadAutomationSettings() {
  const [data, poll] = await Promise.all([api('/api/automation/settings'), api('/api/rss-poll/settings')]);
  const form = document.getElementById('automationSettingsForm');
  form.elements.rss_poll_interval_minutes.value = poll.minutes || 30;
  form.elements.download_enabled.checked = Boolean(data.download_enabled);
  form.elements.daily_time.value = data.daily_time || '02:00';
  form.elements.timezone.value = data.timezone || 'Asia/Shanghai';
}

async function loadNotificationSettings() {
  const data = await api('/api/notifications/settings');
  const form = document.getElementById('notificationSettingsForm');
  form.elements.enabled.checked = Boolean(data.enabled);
  form.elements.telegram_enabled.checked = Boolean(data.telegram_enabled);
  form.elements.telegram_chat_id.value = data.telegram_chat_id || '';
  form.elements.bark_enabled.checked = Boolean(data.bark_enabled);
  form.elements.bark_server_url.value = data.bark_server_url || 'https://api.day.app';
  form.elements.webhook_enabled.checked = Boolean(data.webhook_enabled);
  const events = new Set(data.events || []);
  form.querySelectorAll('input[name="events"]').forEach((input) => { input.checked = events.has(input.value); });
  const secrets = [
    ['notification_telegram_bot_token', data.telegram_bot_token_configured, '已保存 Token；留空保留'],
    ['notification_bark_device_key', data.bark_device_key_configured, '已保存 Key；留空保留'],
    ['notification_webhook_url', data.webhook_url_configured, '已保存地址；留空保留'],
    ['notification_webhook_headers_json', data.webhook_headers_configured, '已保存请求头；留空保留'],
  ];
  secrets.forEach(([name, configured, placeholder]) => {
    form.elements[name].value = '';
    form.elements[name].type = 'password';
    form.elements[name].placeholder = configured ? placeholder : form.elements[name].placeholder;
  });
  ['clear_telegram_bot_token','clear_bark_device_key','clear_webhook_url','clear_webhook_headers'].forEach((name) => { form.elements[name].checked = false; });
  const channels = (data.configured_channels || []).join('、') || '无';
  document.getElementById('notificationConfigState').textContent = `${data.enabled ? '已启用' : '未启用'} · 可用渠道：${channels}`;
}

function notificationPayload() {
  const form = document.getElementById('notificationSettingsForm');
  const valueOrNull = (name) => form.elements[name].value.trim() || null;
  return {
    enabled: form.elements.enabled.checked,
    events: [...form.querySelectorAll('input[name="events"]:checked')].map((input) => input.value),
    telegram_enabled: form.elements.telegram_enabled.checked,
    telegram_bot_token: valueOrNull('notification_telegram_bot_token'),
    clear_telegram_bot_token: form.elements.clear_telegram_bot_token.checked,
    telegram_chat_id: form.elements.telegram_chat_id.value.trim(),
    bark_enabled: form.elements.bark_enabled.checked,
    bark_server_url: form.elements.bark_server_url.value.trim() || 'https://api.day.app',
    bark_device_key: valueOrNull('notification_bark_device_key'),
    clear_bark_device_key: form.elements.clear_bark_device_key.checked,
    webhook_enabled: form.elements.webhook_enabled.checked,
    webhook_url: valueOrNull('notification_webhook_url'),
    clear_webhook_url: form.elements.clear_webhook_url.checked,
    webhook_headers_json: valueOrNull('notification_webhook_headers_json'),
    clear_webhook_headers: form.elements.clear_webhook_headers.checked,
  };
}

async function saveNotificationSettings() {
  const data = await api('/api/notifications/settings', { method: 'PUT', body: JSON.stringify(notificationPayload()) });
  await loadNotificationSettings();
  return data;
}

async function loadProxySettings() {
  const data = await api('/api/proxy/settings');
  const form = document.getElementById('proxySettingsForm');
  form.elements.enabled.checked = Boolean(data.enabled);
  form.elements.proxy_url.value = '';
  form.elements.proxy_url.placeholder = data.url_configured ? '已保存；点击小眼睛查看或留空保留' : 'http:// 或 socks5://';
  form.elements.no_proxy.value = data.no_proxy || 'localhost,127.0.0.1,host.docker.internal';
  form.elements.clear_proxy_url.checked = false;
}

let reviewSubscription = null;
function closeMetadataReview() { document.getElementById('metadataReviewModal').classList.add('hidden'); document.body.classList.remove('modal-open'); reviewSubscription = null; }
function openMetadataReview(subscription) {
  reviewSubscription = subscription;
  document.getElementById('metadataReviewTitle').textContent = `确认：${subscription.name}`;
  document.getElementById('reviewQuery').value = subscription.name || subscription.reference_title || '';
  document.getElementById('reviewResults').textContent = '先尝试 TMDB；找不到正确条目时可切换 Bangumi 或 AniList，也可以完全跳过。';
  document.getElementById('metadataReviewModal').classList.remove('hidden'); document.body.classList.add('modal-open');
}

function renderReviewResults(results) {
  const container = document.getElementById('reviewResults'); container.replaceChildren(); container.className = 'metadata-results';
  if (!results.length) { container.append(text('p', '没有找到结果，可切换另一个来源或跳过。', 'empty')); return; }
  results.forEach(candidate => {
    const card = document.createElement('article'); card.className = 'metadata-card';
    if (candidate.poster_url) { const img=document.createElement('img'); img.src=candidate.poster_url; img.loading='lazy'; card.append(img); }
    const body=document.createElement('div'); body.className='metadata-card-body'; body.append(text('strong', titleWithYear(candidate.title,candidate.year)));
    if (candidate.overview) body.append(text('p',candidate.overview.slice(0,220),'metadata-overview'));
    const choose=text('button','确认此条目'); choose.type='button'; choose.addEventListener('click', async()=>{
      if (!reviewSubscription) return;
      const seasonMode=reviewSubscription.season_mode || 'title';
      await api(`/api/subscriptions/${reviewSubscription.id}/metadata/apply`, {method:'POST', body:JSON.stringify({provider:candidate.provider, metadata_id:candidate.id, media_type:candidate.media_type || 'tv', season:reviewSubscription.season || 1, season_mode:seasonMode})});
      closeMetadataReview(); await reloadAll(); showNotice(`已确认 ${candidate.provider.toUpperCase()} 元数据`);
    });
    body.append(choose); card.append(body); container.append(card);
  });
}

document.getElementById('downloaderForm').elements.download_path.addEventListener('input', (event) => {
  const value = event.currentTarget.value.trim();
  if (!value) return;
  currentDownloadRoot = value;
  document.getElementById('metadataSettingsForm').elements.media_local_root.value = value;
  if (!subscriptionForm.elements.subscription_id.value) subscriptionForm.elements.custom_download_path.value = value;
});

document.getElementById('downloaderForm').addEventListener('submit', async (event) => {
  event.preventDefault();
  try {
    await saveDownloaderSettings();
    await saveApplicationSettings();
    showNotice('下载设置已保存');
  } catch (error) { showNotice(error.message, false); }
});

document.getElementById('saveAndTestDownloader').addEventListener('click', async () => {
  try {
    await saveDownloaderSettings();
    await saveApplicationSettings();
    const result = await api('/api/actions/test-downloader', { method: 'POST' });
    showNotice(result.message, result.ok);
  } catch (error) { showNotice(error.message, false); }
});

document.getElementById('restoreDownloaderConfig').addEventListener('click', async () => {
  if (!window.confirm('确认删除网页保存的 qBittorrent 配置，并恢复 Compose 中的默认值？')) return;
  try {
    await api('/api/downloader/settings', { method: 'DELETE' });
    await Promise.all([loadDownloaderSettings(), loadConfig()]);
    showNotice('已恢复 Compose 默认配置');
  } catch (error) { showNotice(error.message, false); }
});

document.getElementById('mikanCatalogForm').addEventListener('submit', async (event) => {
  event.preventDefault();
  await loadMikanCatalog(event.currentTarget, false);
});

document.getElementById('forceRefreshMikanCatalog').addEventListener('click', async () => {
  await loadMikanCatalog(document.getElementById('mikanCatalogForm'), true);
});

document.getElementById('clearMikanCatalog').addEventListener('click', () => {
  const form = document.getElementById('mikanCatalogForm');
  form.elements.query.value = '';
  document.getElementById('mikanCatalog').replaceChildren();
  currentMikanCatalogData = null;
  mikanWeekdayDrafts.clear();
  const state = document.getElementById('mikanCatalogState');
  state.textContent = '已清空。点击“读取缓存”加载所选季度；只有“强制更新”会访问外部周历或站点。';
  state.className = 'hint';
});

document.getElementById('closeMikanModal').addEventListener('click', closeMikanModal);
document.querySelector('[data-close-mikan-modal]').addEventListener('click', closeMikanModal);
document.addEventListener('keydown', (event) => {
  if (event.key === 'Escape') closeMikanModal();
});

document.getElementById('metadataSettingsForm').addEventListener('submit', async (event) => {
  event.preventDefault();
  try { await api('/api/metadata/settings', { method: 'PUT', body: JSON.stringify(metadataSettingsPayload()) }); await loadMetadataSettings(); showNotice('元数据配置已保存'); } catch (error) { showNotice(error.message, false); }
});

document.getElementById('restoreMetadataSettings').addEventListener('click', async () => {
  if (!window.confirm('确认删除网页保存的元数据配置并恢复 Compose 默认值？')) return;
  try { await api('/api/metadata/settings', { method: 'DELETE' }); await loadMetadataSettings(); showNotice('已恢复 Compose 默认元数据配置'); } catch (error) { showNotice(error.message, false); }
});

async function searchMetadata({ automatic = false } = {}) {
  const provider = document.getElementById('metadataSearchProvider').value;
  const query = document.getElementById('metadataSearchQuery').value.trim() || subscriptionForm.elements.name.value.trim() || subscriptionForm.elements.reference_title.value.trim();
  if (!query) {
    if (!automatic) showNotice('请先输入订阅名称或元数据搜索词', false);
    return [];
  }
  const mediaType = subscriptionForm.elements.media_type.value || 'tv';
  const year = Number.parseInt(subscriptionForm.elements.metadata_year.value || '0', 10) || 0;
  const container = document.getElementById('metadataSearchResults'); container.textContent = '正在搜索…'; container.className = 'metadata-results muted';
  try {
    const params = new URLSearchParams({ provider, q: query, media_type: mediaType, year: String(year), limit: '10' });
    const results = await api(`/api/metadata/search?${params}`);
    renderMetadataResults(results);
    if (automatic && results.length) {
      try {
        await applyMetadataCandidateToForm(results[0]);
        showNotice(`已自动匹配 ${results[0].provider.toUpperCase()} 元数据，请确认后保存订阅`);
      } catch (error) {
        showNotice(`已找到候选结果，但自动填充失败：${error.message}`, false);
      }
    } else if (automatic) {
      showNotice('未找到元数据，请修改搜索词后手动搜索', false);
    }
    return results;
  } catch (error) {
    container.textContent = error.message;
    container.className = 'metadata-results error-text';
    if (automatic) showNotice('自动搜索失败，请修改搜索词后重试', false);
    return [];
  }
}

document.getElementById('searchMetadata').addEventListener('click', () => {
  searchMetadata();
});

subscriptionForm.elements.name.addEventListener('input', () => syncMetadataSearchQuery());
document.getElementById('metadataSearchQuery').addEventListener('input', (event) => {
  event.currentTarget.dataset.subscriptionName = '';
});

document.getElementById('normalizeTorrents').addEventListener('click', async () => {
  try { const result = await api('/api/actions/normalize-torrents', { method: 'POST' }); showNotice(`检查完成：规范化 ${result.renamed || 0}，下载完成 ${result.completed || 0}，等待 ${result.pending || 0}，需手动 ${result.manual_required || 0}，失败 ${result.errors || 0}`, !(result.errors)); await loadItems(); } catch (error) { showNotice(error.message, false); }
});

document.getElementById('globalRulesForm').addEventListener('submit', async (event) => {
  event.preventDefault();
  const value = event.currentTarget.elements.exclude_rules.value;
  try {
    await api('/api/rules/global', { method: 'PUT', body: JSON.stringify({ exclude_rules: value }) });
    showNotice('全局规则已保存');
  } catch (error) { showNotice(error.message, false); }
});

subscriptionForm.addEventListener('submit', async (event) => {
  event.preventDefault();
  const formElement = event.currentTarget;
  const formData = new FormData(formElement);
  const id = formElement.elements.subscription_id.value;
  try {
    const path = id ? `/api/subscriptions/${id}` : '/api/subscriptions';
    const method = id ? 'PATCH' : 'POST';
    const saved = await api(path, { method, body: JSON.stringify(subscriptionPayload({ formData })) });
    formElement.reset();
    resetSubscriptionForm();
    showNotice(id ? '订阅已更新' : '订阅已保存，正在自动刷新一次');
    await reloadAll();
    showAppView('subscriptions');
    if (!id && !saved.metadata_confirmed && !saved.metadata_review_skipped) openMetadataReview(saved);
  } catch (error) { showNotice(error.message, false); }
});

document.getElementById('previewSubscription').addEventListener('click', async () => {
  try {
    const result = await api('/api/subscriptions/preview', {
      method: 'POST',
      body: JSON.stringify(subscriptionPayload({ forPreview: true })),
    });
    subscriptionPreviewBox.textContent = [
      `匹配结果：${result.matched ? '通过' : '不通过'}（${result.match_reason}）`,
      `原始集数：${result.parsed_episode || '未识别（请粘贴真实 RSS 标题）'}`,
      `偏移后集数：${result.adjusted_episode || '未识别'}`,
      `命名预览集数：${result.episode_recognized ? result.preview_episode : `${result.preview_episode}（仅作 E01 示例）`}`,
      `媒体目录：${result.media_folder || '—'}`,
      `最终下载位置：${result.save_path}`,
      `规范文件名：${result.desired_name || '未生成'}`,
    ].join('\n');
    subscriptionPreviewBox.className = `preview-box ${result.matched ? 'good' : 'bad'}`;
    const namingDetails = subscriptionPreviewBox.closest('details');
    if (namingDetails) namingDetails.open = true;
    subscriptionPreviewBox.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
    showNotice(
      result.matched
        ? `预览完成：${result.desired_name || result.save_path}`
        : `预览未通过：${result.match_reason}`,
      result.matched,
    );
  } catch (error) {
    subscriptionPreviewBox.textContent = error.message;
    subscriptionPreviewBox.className = 'preview-box bad';
    const namingDetails = subscriptionPreviewBox.closest('details');
    if (namingDetails) namingDetails.open = true;
    showNotice(`预览失败：${error.message}`, false);
  }
});

document.getElementById('cancelSubscriptionEdit').addEventListener('click', () => { resetSubscriptionForm(); showAppView('subscriptions'); });

document.getElementById('refreshNow').addEventListener('click', async () => {
  navigation.closeMenus(document);
  try {
    const result = await api('/api/actions/refresh', { method: 'POST' });
    showNotice(`${result.message}，可在日志中查看检查与下载器推送进度`);
    window.setTimeout(reloadAll, 2500);
  } catch (error) { showNotice(error.message, false); }
});

document.getElementById('refreshMetadata').addEventListener('click', async () => {
  navigation.closeMenus(document);
  try {
    const result = await api('/api/actions/refresh-metadata', { method: 'POST' });
    showNotice(`${result.message}，可在日志中查看每个订阅的同步结果`);
    window.setTimeout(reloadAll, 2500);
  } catch (error) { showNotice(error.message, false); }
});

document.getElementById('scrapeCompletedMedia').addEventListener('click', async () => {
  navigation.closeMenus(document);
  try {
    const result = await api('/api/actions/scrape-completed', { method: 'POST' });
    showNotice(`${result.message}，可在日志中查看 NFO 与图片写入结果`);
    window.setTimeout(reloadAll, 2500);
  } catch (error) { showNotice(error.message, false); }
});

document.getElementById('testDownloader').addEventListener('click', async () => {
  try {
    const result = await api('/api/actions/test-downloader', { method: 'POST' });
    showNotice(result.message, result.ok);
  } catch (error) { showNotice(error.message, false); }
});

document.getElementById('checkUpdate').addEventListener('click', async (event) => {
  const button = event.currentTarget;
  button.disabled = true;
  button.textContent = '正在检查…';
  try { await loadUpdateStatus(true); }
  catch (error) { showNotice(error.message, false); }
  finally {
    button.disabled = false;
    button.textContent = '检查更新';
  }
});

document.getElementById('applyUpdate').addEventListener('click', async () => {
  if (!window.confirm('确认拉取新镜像并重启 FeedDock？页面可能会短暂断开。')) return;
  try {
    const result = await api('/api/update/apply', { method: 'POST' });
    showNotice(result.message, result.ok);
  } catch (error) { showNotice(error.message, false); }
});

document.getElementById('logout').addEventListener('click', async () => {
  await fetch('/api/auth/logout', { method: 'POST' });
  window.location.replace('/login');
});

document.getElementById('clearRecentItems').addEventListener('click', async () => {
  if (!window.confirm('确认清空最近条目显示？历史指纹会保留，旧 RSS 不会因此重复下载。')) return;
  try { const result = await api('/api/items', { method: 'DELETE' }); showNotice(result.message); await Promise.all([loadItems(), loadDashboard()]); } catch (error) { showNotice(error.message, false); }
});

document.getElementById('clearSystemLogs').addEventListener('click', async () => {
  if (!window.confirm('确认清空全部系统日志？')) return;
  try { const result = await api('/api/logs', { method: 'DELETE' }); showNotice(result.message); await loadLogs(); } catch (error) { showNotice(error.message, false); }
});

document.getElementById('saveLogLevel').addEventListener('click', async () => {
  const level = document.getElementById('logLevelSetting').value;
  try {
    await api('/api/logs/settings', { method: 'PUT', body: JSON.stringify({ level }) });
    await Promise.all([loadLogSettings(), loadLogs()]);
    showNotice(`日志级别已切换为 ${level}`);
  } catch (error) { showNotice(error.message, false); }
});

document.getElementById('refreshSystemLogs').addEventListener('click', async () => {
  try { await loadLogs(); showNotice('日志已刷新'); }
  catch (error) { showNotice(error.message, false); }
});


document.getElementById('automationSettingsForm').elements.auto_skip_existing.addEventListener('change', (event) => {
  if (!event.currentTarget.checked) return;
  const invalid = currentSubscriptions.filter((sub) => sub.enabled && !sub.rename_enabled);
  if (invalid.length) showNotice(`仍有 ${invalid.length} 个启用订阅未开启自动重命名，保存前请先处理。`, false);
});

document.getElementById('pageSettingsForm').addEventListener('submit', async (event) => {
  event.preventDefault();
  try { await saveApplicationSettings(); showNotice('页面设置已保存'); } catch (error) { showNotice(error.message, false); }
});

document.getElementById('restoreApplicationSettings').addEventListener('click', async () => {
  if (!window.confirm('确认恢复主题、排序、下载策略、RSS 自动化和 Trackers 默认值？')) return;
  try { await api('/api/application/settings', { method: 'DELETE' }); await loadApplicationSettings(); showNotice('已恢复新增设置默认值'); } catch (error) { showNotice(error.message, false); }
});

document.getElementById('trackersSettingsForm').addEventListener('submit', async (event) => {
  event.preventDefault();
  try { await saveApplicationSettings(); showNotice('Trackers 设置已保存'); } catch (error) { showNotice(error.message, false); }
});

document.getElementById('refreshTrackers').addEventListener('click', async () => {
  try { await saveApplicationSettings(); const result = await api('/api/trackers/refresh', { method: 'POST' }); await loadApplicationSettings(); showNotice(result.message, result.ok); } catch (error) { showNotice(error.message, false); }
});

document.getElementById('automationSettingsForm').addEventListener('submit', async (event) => {
  event.preventDefault(); const f=event.currentTarget;
  try {
    await Promise.all([
      api('/api/automation/settings',{method:'PUT',body:JSON.stringify({download_enabled:f.elements.download_enabled.checked,scrape_enabled:false,daily_time:f.elements.daily_time.value,timezone:f.elements.timezone.value.trim()})}),
      api('/api/rss-poll/settings',{method:'PUT',body:JSON.stringify({minutes:Number(f.elements.rss_poll_interval_minutes.value)})}),
      saveApplicationSettings(),
    ]);
    await Promise.all([loadAutomationSettings(),loadApplicationSettings(),loadConfig()]);
    showNotice('RSS 设置已保存');
  } catch(error){showNotice(error.message,false);}
});
document.getElementById('runAutomationNow').addEventListener('click', async()=>{try{const r=await api('/api/automation/run',{method:'POST'});showNotice(r.message||'统一任务已执行');await reloadAll();}catch(e){showNotice(e.message,false);}});
document.getElementById('restoreAutomation').addEventListener('click', async()=>{const f=document.getElementById('automationSettingsForm');f.elements.rss_enabled.checked=true;f.elements.rss_timeout_seconds.value=20;f.elements.auto_skip_existing.checked=false;f.elements.auto_disable_complete.checked=false;await Promise.all([api('/api/automation/settings',{method:'DELETE'}),api('/api/rss-poll/settings',{method:'DELETE'}),saveApplicationSettings()]);await Promise.all([loadAutomationSettings(),loadApplicationSettings(),loadConfig()]);showNotice('已恢复默认 RSS 设置');});
document.getElementById('notificationSettingsForm').addEventListener('submit', async(event)=>{event.preventDefault();try{await saveNotificationSettings();showNotice('通知设置已保存');}catch(e){showNotice(e.message,false);}});
document.getElementById('testNotifications').addEventListener('click',async()=>{try{await saveNotificationSettings();const r=await api('/api/notifications/test',{method:'POST'});showNotice(r.message,r.ok);}catch(e){showNotice(e.message,false);}});
document.getElementById('restoreNotifications').addEventListener('click',async()=>{if(!window.confirm('确认清空网页保存的全部通知渠道和密钥？'))return;await api('/api/notifications/settings',{method:'DELETE'});await loadNotificationSettings();showNotice('通知设置已清空');});
document.getElementById('proxySettingsForm').addEventListener('submit', async(event)=>{event.preventDefault();const f=event.currentTarget;try{await api('/api/proxy/settings',{method:'PUT',body:JSON.stringify({enabled:f.elements.enabled.checked,proxy_url:f.elements.proxy_url.value.trim()||null,clear_proxy_url:f.elements.clear_proxy_url.checked,no_proxy:f.elements.no_proxy.value.trim()})});await loadProxySettings();showNotice('代理设置已保存');}catch(e){showNotice(e.message,false);}});
function renderNetworkDiagnostics(data) {
  const container = document.getElementById('networkDiagnostics');
  if (!container || !data) return;
  container.replaceChildren();
  container.classList.toggle('network-ok', Boolean(data.ok));
  container.classList.toggle('network-error', !data.ok);
  container.append(text('strong', data.summary || '网络诊断完成'));
  const resolver = data.resolver || {};
  container.append(text('p', `容器 DNS：${(resolver.nameservers || []).join('、') || '未读取到 nameserver'}`, 'hint'));
  const list = document.createElement('ul');
  (data.checks || []).forEach(check => {
    const address = check.ok ? (check.addresses || []).join(', ') : (check.message || '解析失败');
    list.append(text('li', `${check.ok ? '✓' : '✕'} ${check.label || check.host} (${check.host})：${address}`));
  });
  container.append(list);
  if (!data.ok) {
    const actions = document.createElement('ol');
    (data.remediation || []).forEach(item => actions.append(text('li', item)));
    container.append(actions);
  }
}

document.getElementById('testProxy').addEventListener('click',async()=>{try{const r=await api('/api/proxy/test',{method:'POST'});if(r.dns)renderNetworkDiagnostics(r.dns);showNotice(r.message,r.ok);}catch(e){showNotice(e.message,false);}});
document.getElementById('runNetworkDiagnostics').addEventListener('click',async()=>{try{const r=await api('/api/network/diagnostics');renderNetworkDiagnostics(r);showNotice(r.summary,r.ok);}catch(e){showNotice(e.message,false);}});
document.getElementById('restoreProxy').addEventListener('click',async()=>{await api('/api/proxy/settings',{method:'DELETE'});await loadProxySettings();showNotice('已恢复 Compose 代理设置');});
document.getElementById('closeMetadataReview').addEventListener('click', closeMetadataReview);
document.querySelector('[data-close-metadata-review]').addEventListener('click', closeMetadataReview);
document.getElementById('reviewSearch').addEventListener('click',async()=>{if(!reviewSubscription)return;const provider=document.getElementById('reviewProvider').value;const q=document.getElementById('reviewQuery').value.trim();const c=document.getElementById('reviewResults');c.textContent='正在搜索…';try{const params=new URLSearchParams({provider,q,media_type:reviewSubscription.media_type||'tv',year:String(reviewSubscription.metadata_year||0),limit:'10'});renderReviewResults(await api(`/api/metadata/search?${params}`));}catch(e){c.textContent=e.message;}});
document.getElementById('reviewSkip').addEventListener('click',async()=>{if(!reviewSubscription)return;await api(`/api/subscriptions/${reviewSubscription.id}/metadata/skip`,{method:'POST',body:JSON.stringify({skipped:true})});closeMetadataReview();await reloadAll();showNotice('已跳过外部元数据匹配，将使用手动名称');});

document.getElementById('useDefaultSourceFeed').addEventListener('click', () => {
  if (!activeSubscriptionSource.default_feed_url) return;
  const message = `${activeSubscriptionSource.label} 的全站 RSS 可能包含大量条目，确认填入后请配置“匹配/排除”规则。继续吗？`;
  if (!window.confirm(message)) return;
  setFormValue(subscriptionForm, 'rss_url', activeSubscriptionSource.default_feed_url);
  if (!subscriptionForm.elements.primary_rss_name.value.trim()) setFormValue(subscriptionForm, 'primary_rss_name', activeSubscriptionSource.rss_name);
  showNotice(`已填入 ${activeSubscriptionSource.label} 全站 RSS，请先设置过滤规则再保存`, false);
});

subscriptionForm.elements.rss_url.addEventListener('change', (event) => {
  const detected = subscriptionSourceState.detectSource(subscriptionSources, event.currentTarget.value);
  renderSubscriptionSourceContext(detected);
  if (detected.id !== 'other' && !subscriptionForm.elements.primary_rss_name.value.trim()) {
    setFormValue(subscriptionForm, 'primary_rss_name', detected.rss_name);
  }
});

document.querySelectorAll('[data-subscription-source]').forEach((button) => {
  button.addEventListener('click', () => {
    const source = button.dataset.subscriptionSource;
    if (!source) return;
    if (['mikan', 'anibt', 'ag'].includes(source)) {
      openCatalogSource(source, { autoLoad: true }).catch((error) => showNotice(error.message, false));
    } else {
      openSubscriptionEditor(source).catch((error) => showNotice(error.message, false));
    }
  });
});

document.addEventListener('feeddock:viewchange', (event) => {
  const { view, management } = event.detail;
  if (view === 'subscriptions') setManagementMode(management);
  else if (subscriptionManagementMode) setManagementMode(false);
});

document.querySelector('.app-brand').addEventListener('keydown', (event) => {
  if (event.key === 'Enter' || event.key === ' ') { event.preventDefault(); showAppView('subscriptions'); }
});

document.getElementById('subscriptionSearch').addEventListener('input', () => renderSubscriptions(currentSubscriptions));
document.getElementById('subscriptionStateFilter').addEventListener('change', () => renderSubscriptions(currentSubscriptions));
document.getElementById('toggleManagementMode').addEventListener('click', () => setManagementMode(!subscriptionManagementMode));
document.getElementById('selectAllSubscriptions').addEventListener('change', (event) => {
  filteredSubscriptions(currentSubscriptions).forEach((sub) => {
    if (event.currentTarget.checked) selectedSubscriptionIds.add(sub.id); else selectedSubscriptionIds.delete(sub.id);
  });
  renderSubscriptions(currentSubscriptions);
});
document.getElementById('batchEnableSubscriptions').addEventListener('click', () => runSubscriptionBatch('enable'));
document.getElementById('batchDisableSubscriptions').addEventListener('click', () => runSubscriptionBatch('disable'));
document.getElementById('batchDeleteSubscriptions').addEventListener('click', () => runSubscriptionBatch('delete'));
document.getElementById('batchExportSubscriptions').addEventListener('click', () => {
  const ids = [...selectedSubscriptionIds];
  if (!ids.length) { showNotice('请先选择需要导出的订阅', false); return; }
  exportSubscriptionData(ids).catch((error) => showNotice(error.message, false));
});
document.getElementById('batchImportSubscriptions').addEventListener('click', () => openSubscriptionImportModal());
document.getElementById('exportSubscriptions').addEventListener('click', () => exportSubscriptionData().catch((error) => showNotice(error.message, false)));
document.getElementById('openImportSubscriptions').addEventListener('click', () => openSubscriptionImportModal());
document.getElementById('openCollectionImport').addEventListener('click', () => openSubscriptionImportModal({ collection: true }));
document.getElementById('closeSubscriptionImport').addEventListener('click', closeSubscriptionImportModal);
document.getElementById('cancelSubscriptionImport').addEventListener('click', closeSubscriptionImportModal);
document.querySelector('[data-close-subscription-import]').addEventListener('click', closeSubscriptionImportModal);
document.getElementById('subscriptionImportFile').addEventListener('change', async (event) => {
  const [file] = event.currentTarget.files;
  if (!file) return;
  document.getElementById('subscriptionImportJson').value = await file.text();
});
document.getElementById('confirmSubscriptionImport').addEventListener('click', async () => {
  try { await importSubscriptionData(); } catch (error) { showNotice(error.message, false); }
});
document.getElementById('loginSettingsLogout').addEventListener('click', () => document.getElementById('logout').click());
document.getElementById('restartSystem').addEventListener('click', async () => {
  if (!window.confirm('确认重启 FeedDock？页面会短暂断开。')) return;
  try { const result = await api('/api/system/restart', { method: 'POST' }); showNotice(result.message); }
  catch (error) { showNotice(error.message, false); }
});
document.getElementById('shutdownSystem').addEventListener('click', async () => {
  if (!window.confirm('确认关闭 FeedDock 服务？容器自动重启策略可能再次启动服务。')) return;
  try { const result = await api('/api/system/shutdown', { method: 'POST' }); showNotice(result.message); }
  catch (error) { showNotice(error.message, false); }
});

document.getElementById('statusFilter').addEventListener('change', loadItems);
navigation.initialize();
initializeCollapsiblePanels();
initializePasswordToggles();
initializeCatalogSelectors();
resetSubscriptionForm();
reloadAll();
