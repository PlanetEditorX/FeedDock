const notice = document.getElementById('notice');
const subscriptionForm = document.getElementById('subscriptionForm');
const subscriptionPreviewBox = document.getElementById('subscriptionPreview');
let subscriptionsById = new Map();
let currentMikanDetailItem = null;
let currentMikanCatalogData = null;
let currentDownloadRoot = '/media';
const mikanWeekdayDrafts = new Map();
const PANEL_STATE_KEY = 'feeddock.panelState.v1';
const MIKAN_WEEKDAY_STATE_KEY = 'feeddock.mikanWeekdayState.v1';

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
    try { const payload = await response.json(); const detail = payload.detail; message = typeof detail === 'string' ? detail : (detail?.message || JSON.stringify(detail) || message); if (payload.request_id && !message.includes(payload.request_id)) message += ` [${payload.request_id}]`; } catch (_) {}
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
  setFormValue(subscriptionForm, 'naming_mode', 'auto');
  setFormValue(subscriptionForm, 'media_type', 'tv');
  setFormValue(subscriptionForm, 'metadata_year', 0);
  setFormValue(subscriptionForm, 'tmdb_id', 0);
  setFormValue(subscriptionForm, 'bangumi_id', 0);
  setFormValue(subscriptionForm, 'anilist_id', 0);
  setFormValue(subscriptionForm, 'season_mode', 'title');
  setFormValue(subscriptionForm, 'metadata_confirmed', false);
  setFormValue(subscriptionForm, 'metadata_review_skipped', false);
  setFormValue(subscriptionForm, 'season', 1);
  setFormValue(subscriptionForm, 'episode_group', 0);
  setFormValue(subscriptionForm, 'episode_offset', 0);
  setFormValue(subscriptionForm, 'total_episodes', 0);
  setFormValue(subscriptionForm, 'total_episodes_source', '');
  setFormValue(subscriptionForm, 'save_path_template', '{base}/{media_folder}/Season {season:02}');
  setFormValue(subscriptionForm, 'file_name_template', '{title} - S{season:02}E{episode:02}');
  setFormValue(subscriptionForm, 'rename_enabled', true);
  setFormValue(subscriptionForm, 'custom_download_path', currentDownloadRoot);
  setFormValue(subscriptionForm, 'enabled', true);
  document.getElementById('metadataSearchResults').textContent = '尚未搜索。';
  document.getElementById('metadataSearchResults').className = 'metadata-results muted';
  document.getElementById('subscriptionFormTitle').textContent = '添加订阅';
  document.getElementById('saveSubscription').textContent = '保存订阅';
  document.getElementById('cancelSubscriptionEdit').classList.add('hidden');
  subscriptionPreviewBox.textContent = '尚未预览。';
  subscriptionPreviewBox.className = 'preview-box muted';
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
    name: get('name'), reference_title: get('reference_title'), tmdb_title: get('tmdb_title'),
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
    save_path_template: get('save_path_template') || '{base}/{media_folder}/Season {season:02}',
    custom_download_path: get('custom_download_path'), missing_detection: checkbox('missing_detection'),
    only_latest: checkbox('only_latest'), enabled: checkbox('enabled'),
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
    catalogState.textContent = `首次没有缓存时会请求一次 Mikan；之后页面只读缓存，已浏览季度默认每 ${data.mikan_cache_hours || 6} 小时后台更新一次。`;
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

async function loadMetadataSettings() {
  const data = await api('/api/metadata/settings');
  const form = document.getElementById('metadataSettingsForm');
  form.elements.tmdb_read_access_token.value = '';
  form.elements.tmdb_read_access_token.placeholder = data.tmdb_token_configured ? '已保存；留空表示不修改' : '请填写 TMDB Read Access Token';
  form.elements.bangumi_access_token.value = '';
  form.elements.bangumi_access_token.placeholder = data.bangumi_token_configured ? '已保存；留空表示不修改' : '公开查询通常可留空';
  form.elements.metadata_language.value = data.metadata_language || data.language || 'zh-CN';
  form.elements.clear_tmdb_token.checked = false;
  form.elements.clear_bangumi_token.checked = false;
  document.getElementById('metadataConfigState').textContent = `TMDB ${data.tmdb_token_configured ? '已配置' : '未配置'} · Bangumi ${data.bangumi_token_configured ? '已配置' : '公开 API'} · AniList 公开 API · 仅用于命名与集数匹配`;
}

function metadataSettingsPayload() {
  const form = document.getElementById('metadataSettingsForm');
  return {
    tmdb_read_access_token: form.elements.tmdb_read_access_token.value.trim() || null,
    clear_tmdb_token: form.elements.clear_tmdb_token.checked,
    bangumi_access_token: form.elements.bangumi_access_token.value.trim() || null,
    clear_bangumi_token: form.elements.clear_bangumi_token.checked,
    metadata_language: form.elements.metadata_language.value.trim() || 'zh-CN',
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
    'name', 'reference_title', 'tmdb_title', 'bgm_url', 'air_date', 'season', 'season_mode',
    'primary_rss_name', 'rss_url', 'backup_rss_name', 'backup_rss_url',
    'include_keywords', 'exclude_keywords', 'episode_regex', 'episode_group',
    'episode_offset', 'total_episodes', 'save_path_template', 'custom_download_path',
    'missing_detection', 'only_latest', 'enabled', 'sample_title', 'bangumi_id',
  ];
  fields.forEach((field) => setFormValue(subscriptionForm, field, preset[field]));
  document.getElementById('subscriptionFormTitle').textContent = `添加订阅：${preset.name || '未命名番剧'}`;
  subscriptionPreviewBox.textContent = preset.sample_title
    ? `已带入样本标题：${preset.sample_title}\n请点击“预览规则和路径”确认集数与保存位置。`
    : '已带入 RSS，请补充规则后点击“预览规则和路径”。';
  subscriptionPreviewBox.className = 'preview-box muted';
  closeMikanModal();
  document.getElementById('subscriptionEditor').scrollIntoView({ behavior: 'smooth', block: 'start' });
  showNotice('已填入订阅表单，请确认规则和下载路径后保存');
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
  };
  const parts = [statusLabels[data.cache_status] || '本地缓存'];
  if (data.cached_at) parts.push(`缓存时间 ${fmtDate(data.cached_at)}`);
  if (data.next_refresh_at) parts.push(`下次后台刷新 ${fmtDate(data.next_refresh_at)}`);
  if (data.is_stale) parts.push('等待后台刷新');
  if (data.refresh_error) parts.push(`上次刷新失败：${data.refresh_error}`);
  return parts.join(' · ');
}

function renderMikanDetail(detail) {
  const container = document.getElementById('mikanDetailBody');
  container.replaceChildren();

  const summary = document.createElement('div');
  summary.className = 'mikan-detail-summary';
  const summaryText = document.createElement('div');
  summaryText.append(text('strong', `${detail.groups.length} 个字幕组 RSS`));
  summaryText.append(text('span', cacheStatusText(detail), 'muted cache-meta'));
  summary.append(summaryText);

  const summaryActions = document.createElement('div');
  summaryActions.className = 'card-actions';
  const refreshButton = text('button', '强制更新字幕组', 'small secondary');
  refreshButton.type = 'button';
  refreshButton.addEventListener('click', async () => {
    if (!currentMikanDetailItem) return;
    refreshButton.disabled = true;
    refreshButton.textContent = '正在更新…';
    try {
      await openMikanDetail(currentMikanDetailItem, true);
      showNotice('字幕组缓存已更新');
    } catch (_) {
      // openMikanDetail already renders the error.
    } finally {
      refreshButton.disabled = false;
      refreshButton.textContent = '强制更新字幕组';
    }
  });
  summaryActions.append(refreshButton);
  if (detail.detail_url) summaryActions.append(externalLink('打开 Mikan 番剧页', detail.detail_url));
  summary.append(summaryActions);
  container.append(summary);

  if (!detail.groups.length) {
    container.append(text('p', '没有解析到字幕组。可以打开 Mikan 番剧页，确认当前季度是否已有资源发布。', 'empty'));
    return;
  }

  const list = document.createElement('div');
  list.className = 'mikan-rss-list';
  for (const group of detail.groups) {
    const row = document.createElement('article');
    row.className = 'mikan-rss-row';

    const info = document.createElement('div');
    info.className = 'mikan-rss-info';
    info.append(text('h3', group.name));
    info.append(text('code', group.rss_url, 'rss-code'));

    const actions = document.createElement('div');
    actions.className = 'card-actions';
    const subscribe = text('button', '订阅', 'small');
    subscribe.type = 'button';
    subscribe.addEventListener('click', () => applyDiscoveryPreset(group.preset));
    const copy = text('button', '复制 RSS', 'small secondary');
    copy.type = 'button';
    copy.addEventListener('click', () => copyText(group.rss_url));
    actions.append(subscribe, copy);
    if (group.detail_url) actions.append(externalLink('字幕组页面', group.detail_url));
    row.append(info, actions);
    list.append(row);
  }
  container.append(list);
}

async function openMikanDetail(item, forceRefresh = false) {
  currentMikanDetailItem = item;
  openMikanModal(item.title);
  try {
    const params = new URLSearchParams({
      base_url: item.base_url || '',
      title: item.title || '',
    });
    const path = forceRefresh
      ? `/api/discovery/mikan/${item.bangumi_id}/refresh?${params.toString()}`
      : `/api/discovery/mikan/${item.bangumi_id}?${params.toString()}`;
    const detail = await api(path, forceRefresh ? { method: 'POST' } : {});
    document.getElementById('mikanDetailTitle').textContent = detail.title;
    renderMikanDetail(detail);
    return detail;
  } catch (error) {
    const body = document.getElementById('mikanDetailBody');
    body.replaceChildren(text('p', error.message, 'error-text'));
    throw error;
  }
}

function mikanWeekdayKey(data, row) {
  return `${data.year}|${data.season}|${row.weekday}`;
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
  if (editing) card.classList.add('is-filter-editing');
  if (hiddenDraft) card.classList.add('is-filter-hidden');
  if (!editing) card.addEventListener('click', () => openMikanDetail(item));

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
  info.append(text('strong', item.title));
  if (item.update_at) info.append(text('span', item.update_at, 'muted'));
  info.append(text(
    'span',
    editing ? (hiddenDraft ? '保存后隐藏' : '当前显示') : '点击查看字幕组 RSS',
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

async function saveMikanWeekdayFilter(data, row, hiddenIds) {
  const result = await api('/api/discovery/mikan/catalog/filters', {
    method: 'PUT',
    body: JSON.stringify({
      year: data.year,
      season: data.season,
      weekday: row.weekday,
      hidden_bangumi_ids: [...hiddenIds].sort((a, b) => a - b),
    }),
  });
  const saved = new Set(result.hidden_bangumi_ids || []);
  row.items.forEach((item) => { item.hidden = saved.has(Number(item.bangumi_id)); });
  row.hidden_count = row.items.filter((item) => item.hidden).length;
  data.hidden_count = data.rows.reduce(
    (sum, currentRow) => sum + currentRow.items.filter((item) => item.hidden).length,
    0,
  );
  return saved;
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
  state.textContent = `${data.year} ${data.season} · ${data.rows.length} 个播出日 · 显示 ${visibleCount}/${totalCount} 部${hiddenSummary} · ${cacheStatusText(data)}`;
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
          await saveMikanWeekdayFilter(data, row, new Set());
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
          await saveMikanWeekdayFilter(data, row, draft);
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
          new Set(row.items.filter((item) => item.hidden).map((item) => Number(item.bangumi_id))),
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
        const bangumiId = Number(item.bangumi_id);
        grid.append(createMikanCard(item, {
          editing,
          hiddenDraft: draft.has(bangumiId),
          onToggle: (hidden) => {
            if (hidden) draft.add(bangumiId);
            else draft.delete(bangumiId);
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
  state.textContent = forceRefresh
    ? `正在从 Mikan 更新 ${year} ${season}番剧目录…`
    : `正在读取 FeedDock 中的 ${year} ${season}缓存…`;
  state.className = 'hint';
  try {
    const params = new URLSearchParams({ year, season });
    if (query) params.set('q', query);
    const path = forceRefresh
      ? `/api/discovery/mikan/catalog/refresh?${params.toString()}`
      : `/api/discovery/mikan/catalog?${params.toString()}`;
    const data = await api(path, forceRefresh ? { method: 'POST' } : {});
    renderMikanCatalog(data);
    if (forceRefresh) showNotice('Mikan 番剧目录缓存已更新');
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
    'name', 'reference_title', 'tmdb_title', 'manual_title', 'naming_mode', 'media_type',
    'bgm_url', 'air_date', 'metadata_year', 'metadata_source', 'metadata_overview', 'poster_url', 'backdrop_url', 'metadata_confirmed', 'metadata_review_skipped', 'tmdb_id', 'bangumi_id', 'anilist_id', 'auto_metadata', 'season', 'season_mode',
    'primary_rss_name', 'rss_url', 'backup_rss_name', 'backup_rss_url',
    'include_keywords', 'exclude_keywords', 'episode_regex', 'episode_group',
    'episode_offset', 'total_episodes', 'total_episodes_locked', 'total_episodes_source',
    'rename_enabled', 'file_name_template', 'save_path_template',
    'custom_download_path', 'missing_detection', 'only_latest', 'enabled',
  ];
  fields.forEach((field) => setFormValue(subscriptionForm, field, sub[field]));
  setFormValue(subscriptionForm, 'subscription_id', sub.id);
  setFormValue(subscriptionForm, 'sample_title', sub.reference_title || sub.name);
  document.getElementById('subscriptionFormTitle').textContent = `编辑订阅：${sub.name}`;
  document.getElementById('saveSubscription').textContent = '保存修改';
  document.getElementById('cancelSubscriptionEdit').classList.remove('hidden');
  subscriptionPreviewBox.textContent = '请点击“预览规则和路径”确认修改后的结果。';
  subscriptionPreviewBox.className = 'preview-box muted';
  document.getElementById('subscriptionEditor').scrollIntoView({ behavior: 'smooth', block: 'start' });
}

async function loadSubscriptions() {
  const container = document.getElementById('subscriptions');
  const data = await api('/api/subscriptions');
  subscriptionsById = new Map(data.map((sub) => [String(sub.id), sub]));
  container.replaceChildren();
  if (!data.length) { container.append(text('p', '还没有订阅。', 'empty')); return; }
  for (const sub of data) {
    const card = document.createElement('article'); card.className = 'subscription-card metadata-subscription-card';
    if (sub.poster_url) {
      const img = document.createElement('img');
      img.className = 'subscription-poster'; img.src = sub.poster_url; img.loading = 'lazy'; img.decoding = 'async';
      img.alt = `${sub.canonical_title || sub.name} 海报`; card.append(img);
    }
    const content = document.createElement('div'); content.className = 'subscription-card-content';
    const titleRow = document.createElement('div'); titleRow.className = 'subscription-title';
    titleRow.append(text('h3', sub.canonical_title || sub.name));
    titleRow.append(text('span', sub.enabled ? '启用' : '停用', `badge ${sub.enabled ? 'queued' : 'skipped'}`)); content.append(titleRow);
    if (sub.metadata_overview) content.append(text('p', sub.metadata_overview, 'subscription-overview'));
    const meta = document.createElement('div'); meta.className = 'subscription-meta';
    meta.append(text('span', `原订阅名：${sub.name}`));
    meta.append(text('span', `媒体目录：${sub.media_folder || '—'}`));
    meta.append(text('span', `来源：${sub.metadata_source || (sub.metadata_review_skipped ? '已跳过' : '未确认')} · TMDB ${sub.tmdb_id || '—'} · Bangumi ${sub.bangumi_id || '—'} · AniList ${sub.anilist_id || '—'}`));
    meta.append(text('span', `季 ${sub.season}（${sub.season_mode || 'manual'}） · 总集数 ${sub.total_episodes || '未知'}（${sub.total_episodes_source || '未同步'}${sub.total_episodes_locked ? '，已锁定' : ''}）`));
    meta.append(text('span', `下载根目录：${sub.custom_download_path || currentDownloadRoot} · 模板：${sub.save_path_template}`));
    meta.append(text('span', `命名：${sub.rename_enabled ? sub.file_name_template : '关闭'}`));
    meta.append(text('span', `主 RSS：${sub.primary_rss_name || '未命名'} · ${sub.rss_url}`));
    content.append(meta);
    content.append(text('p', `上次元数据同步：${fmtDate(sub.metadata_last_synced_at)} ｜ 上次检查：${fmtDate(sub.last_checked_at)}${sub.last_error ? ` ｜ ${sub.last_error}` : ''}`, sub.last_error ? 'error-text' : 'muted'));
    const controls = document.createElement('div'); controls.className = 'card-actions';
    const edit = text('button', '编辑', 'secondary'); edit.addEventListener('click', () => populateSubscriptionForm(sub));
    const sync = text('button', '同步元数据', 'secondary'); sync.addEventListener('click', async () => { try { await api(`/api/subscriptions/${sub.id}/metadata/sync`, { method: 'POST', body: JSON.stringify({ provider: 'auto' }) }); showNotice('元数据和总集数已同步'); await reloadAll(); } catch (error) { showNotice(error.message, false); } });
    const toggle = text('button', sub.enabled ? '停用' : '启用', 'secondary'); toggle.addEventListener('click', async () => { await api(`/api/subscriptions/${sub.id}`, { method: 'PATCH', body: JSON.stringify({ enabled: !sub.enabled }) }); showNotice('订阅状态已更新'); await reloadAll(); });
    const remove = text('button', '删除', 'danger'); remove.addEventListener('click', async () => { if (!window.confirm(`确定删除“${sub.name}”及其历史记录吗？`)) return; await api(`/api/subscriptions/${sub.id}`, { method: 'DELETE' }); if (subscriptionForm.elements.subscription_id.value === String(sub.id)) resetSubscriptionForm(); showNotice('订阅已删除'); await reloadAll(); });
    controls.append(edit, sync, toggle, remove); content.append(controls); card.append(content); container.append(card);
  }
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
    const rename = [item.rename_status || (item.desired_name ? '等待处理' : '未启用'), item.desired_name || '', item.rename_message || ''].filter(Boolean).join('\n');
    row.append(text('td', rename, item.rename_status === 'error' ? 'error-text' : '')); row.append(text('td', item.reason || '—'));
    const actionCell = document.createElement('td');
    if (item.status === 'error' || item.rename_status === 'error') { const retry = text('button', '重试', 'small secondary'); retry.addEventListener('click', async () => { const result = await api(`/api/items/${item.id}/retry`, { method: 'POST' }); showNotice(result.message, result.ok); await reloadAll(); }); actionCell.append(retry); }
    row.append(actionCell); tbody.append(row);
  }
}

async function loadLoggingSettings() {
  const data = await api('/api/logging/settings');
  document.getElementById('logLevelSetting').value = data.level || 'INFO';
  document.getElementById('logConfigState').textContent = `${data.level || 'INFO'} 模式 · 文件 ${data.file || '/data/logs/feeddock.log'}`;
}

async function loadLogs() {
  const limit = document.getElementById('logLimit')?.value || '100';
  const level = document.getElementById('logLevelFilter')?.value || '';
  const requestId = document.getElementById('logRequestIdFilter')?.value.trim() || '';
  const params = new URLSearchParams({ limit });
  if (level) params.set('level', level);
  if (requestId) params.set('request_id', requestId);
  const data = await api(`/api/logs?${params}`);
  const container = document.getElementById('logs');
  container.replaceChildren();
  if (!data.length) { container.append(text('p', '暂无日志。开启 DEBUG 后重试操作，可看到每个 API 请求和完整异常。', 'empty')); return; }
  for (const log of data) {
    const row = document.createElement('article'); row.className = `log-row log-${String(log.level || '').toLowerCase()}`;
    const summary = document.createElement('div'); summary.className = 'log-summary';
    summary.append(text('time', fmtDate(log.created_at)));
    summary.append(text('span', log.level, `badge ${log.level === 'ERROR' ? 'error' : (log.level === 'WARNING' ? 'skipped' : 'queued')}`));
    summary.append(text('span', log.source || 'app', 'log-source'));
    if (log.request_id) summary.append(text('code', log.request_id, 'log-request-id'));
    summary.append(text('strong', log.message)); row.append(summary);
    if (log.details) {
      const details = document.createElement('details');
      const title = document.createElement('summary'); title.textContent = '详细内容 / traceback'; details.append(title);
      const pre = document.createElement('pre'); pre.textContent = log.details; details.append(pre); row.append(details);
    }
    container.append(row);
  }
}

async function reloadAll() {
  try {
    await loadAuth();
    await Promise.all([
      loadDashboard(), loadConfig(), loadDownloaderSettings(), loadMetadataSettings(), loadGlobalRules(),
      loadSubscriptions(), loadItems(), loadLoggingSettings(), loadLogs(), loadAutomationSettings(), loadProxySettings(),
    ]);
  } catch (error) {
    showNotice(error.message, false);
  }
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
  const data = await api('/api/automation/settings');
  const form = document.getElementById('automationSettingsForm');
  form.elements.download_enabled.checked = Boolean(data.download_enabled);
  form.elements.daily_time.value = data.daily_time || '02:00';
  form.elements.timezone.value = data.timezone || 'Asia/Shanghai';
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


document.getElementById('downloaderForm').elements.download_path.addEventListener('input', (event) => {
  const value = event.currentTarget.value.trim();
  if (!value) return;
  currentDownloadRoot = value;
  if (!subscriptionForm.elements.subscription_id.value) subscriptionForm.elements.custom_download_path.value = value;
});

document.getElementById('downloaderForm').addEventListener('submit', async (event) => {
  event.preventDefault();
  try {
    await saveDownloaderSettings();
    showNotice('qBittorrent 配置已保存');
  } catch (error) { showNotice(error.message, false); }
});

document.getElementById('saveAndTestDownloader').addEventListener('click', async () => {
  try {
    await saveDownloaderSettings();
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
  state.textContent = '已清空。点击“读取缓存”加载所选季度；只有“强制更新”会访问 Mikan。';
  state.className = 'hint';
});

document.getElementById('closeMikanModal').addEventListener('click', closeMikanModal);
document.querySelector('[data-close-mikan-modal]').addEventListener('click', closeMikanModal);
document.addEventListener('keydown', (event) => {
  if (event.key === 'Escape') closeMikanModal();
});

document.getElementById('metadataSettingsForm').addEventListener('submit', async (event) => {
  event.preventDefault();
  try { await api('/api/metadata/settings', { method: 'PUT', body: JSON.stringify(metadataSettingsPayload()) }); await loadMetadataSettings(); showNotice('元数据匹配配置已保存'); } catch (error) { showNotice(error.message, false); }
});

document.getElementById('restoreMetadataSettings').addEventListener('click', async () => {
  if (!window.confirm('确认删除网页保存的元数据配置并恢复 Compose 默认值？')) return;
  try { await api('/api/metadata/settings', { method: 'DELETE' }); await loadMetadataSettings(); showNotice('已恢复 Compose 默认元数据配置'); } catch (error) { showNotice(error.message, false); }
});

document.getElementById('searchMetadata').addEventListener('click', async () => {
  const provider = document.getElementById('metadataSearchProvider').value;
  const query = document.getElementById('metadataSearchQuery').value.trim() || subscriptionForm.elements.name.value.trim() || subscriptionForm.elements.reference_title.value.trim();
  if (!query) { showNotice('请先输入订阅名称或元数据搜索词', false); return; }
  const mediaType = subscriptionForm.elements.media_type.value || 'tv';
  const year = Number.parseInt(subscriptionForm.elements.metadata_year.value || '0', 10) || 0;
  const container = document.getElementById('metadataSearchResults'); container.textContent = '正在搜索…'; container.className = 'metadata-results muted';
  try { const params = new URLSearchParams({ provider, q: query, media_type: mediaType, year: String(year), limit: '10' }); renderMetadataResults(await api(`/api/metadata/search?${params}`)); } catch (error) { container.textContent = error.message; container.className = 'metadata-results error-text'; }
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
    await api(path, { method, body: JSON.stringify(subscriptionPayload({ formData })) });
    formElement.reset();
    resetSubscriptionForm();
    showNotice(id ? '订阅已更新' : '订阅已保存');
    await reloadAll();
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
  } catch (error) {
    subscriptionPreviewBox.textContent = error.message;
    subscriptionPreviewBox.className = 'preview-box bad';
  }
});

document.getElementById('cancelSubscriptionEdit').addEventListener('click', resetSubscriptionForm);

document.getElementById('refreshNow').addEventListener('click', async () => {
  try {
    const result = await api('/api/actions/refresh', { method: 'POST' });
    showNotice(result.message);
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


document.getElementById('automationSettingsForm').addEventListener('submit', async (event) => {
  event.preventDefault(); const f=event.currentTarget;
  try { await api('/api/automation/settings',{method:'PUT',body:JSON.stringify({download_enabled:f.elements.download_enabled.checked,daily_time:f.elements.daily_time.value,timezone:f.elements.timezone.value.trim()})}); await loadAutomationSettings(); showNotice('统一执行时间已保存'); } catch(error){showNotice(error.message,false);}
});
document.getElementById('runAutomationNow').addEventListener('click', async()=>{try{const r=await api('/api/automation/run',{method:'POST'});showNotice(r.message||'统一任务已执行');await reloadAll();}catch(e){showNotice(e.message,false);}});
document.getElementById('restoreAutomation').addEventListener('click', async()=>{await api('/api/automation/settings',{method:'DELETE'});await loadAutomationSettings();showNotice('已恢复即时下载');});
document.getElementById('proxySettingsForm').addEventListener('submit', async(event)=>{event.preventDefault();const f=event.currentTarget;try{await api('/api/proxy/settings',{method:'PUT',body:JSON.stringify({enabled:f.elements.enabled.checked,proxy_url:f.elements.proxy_url.value.trim()||null,clear_proxy_url:f.elements.clear_proxy_url.checked,no_proxy:f.elements.no_proxy.value.trim()})});await loadProxySettings();showNotice('代理设置已保存');}catch(e){showNotice(e.message,false);}});
document.getElementById('testProxy').addEventListener('click',async()=>{try{const r=await api('/api/proxy/test',{method:'POST'});showNotice(r.message,r.ok);}catch(e){showNotice(e.message,false);}});
document.getElementById('restoreProxy').addEventListener('click',async()=>{await api('/api/proxy/settings',{method:'DELETE'});await loadProxySettings();showNotice('已恢复 Compose 代理设置');});

document.getElementById('logLevelSetting').addEventListener('change', async (event) => {
  try { await api('/api/logging/settings', { method: 'PUT', body: JSON.stringify({ level: event.currentTarget.value }) }); await Promise.all([loadLoggingSettings(), loadLogs()]); showNotice(`日志级别已切换为 ${event.currentTarget.value}`); } catch (error) { showNotice(error.message, false); }
});
document.getElementById('logLevelFilter').addEventListener('change', loadLogs);
document.getElementById('logRequestIdFilter').addEventListener('input', debounce(loadLogs, 350));
document.getElementById('logLimit').addEventListener('change', loadLogs);
document.getElementById('refreshSystemLogs').addEventListener('click', loadLogs);
document.getElementById('exportSystemLogs').addEventListener('click', () => { window.location.href = '/api/logs/export?limit=10000'; });

document.getElementById('statusFilter').addEventListener('change', loadItems);
initializeCollapsiblePanels();
initializePasswordToggles();
initializeCatalogSelectors();
resetSubscriptionForm();
reloadAll();
