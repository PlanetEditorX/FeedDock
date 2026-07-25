const notice = document.getElementById('notice');
const subscriptionForm = document.getElementById('subscriptionForm');
const subscriptionPreviewBox = document.getElementById('subscriptionPreview');
let subscriptionsById = new Map();

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

function setFormValue(form, name, value) {
  const element = form.elements[name];
  if (!element) return;
  if (element.type === 'checkbox') element.checked = Boolean(value);
  else element.value = value ?? '';
}

function resetSubscriptionForm() {
  subscriptionForm.reset();
  setFormValue(subscriptionForm, 'subscription_id', '');
  setFormValue(subscriptionForm, 'season', 1);
  setFormValue(subscriptionForm, 'episode_group', 0);
  setFormValue(subscriptionForm, 'episode_offset', 0);
  setFormValue(subscriptionForm, 'total_episodes', 0);
  setFormValue(subscriptionForm, 'save_path_template', '{base}/{subscription}/Season {season}');
  setFormValue(subscriptionForm, 'enabled', true);
  document.getElementById('subscriptionFormTitle').textContent = '添加订阅';
  document.getElementById('saveSubscription').textContent = '保存订阅';
  document.getElementById('cancelSubscriptionEdit').classList.add('hidden');
  subscriptionPreviewBox.textContent = '尚未预览。最终下载位置以预览结果为准。';
  subscriptionPreviewBox.className = 'preview-box muted';
}

function subscriptionPayload({ forPreview = false, formData = null } = {}) {
  const data = formData || new FormData(subscriptionForm);
  const get = (name) => String(data.get(name) || '').trim();
  const integer = (name, fallback = 0) => {
    const value = Number.parseInt(get(name), 10);
    return Number.isFinite(value) ? value : fallback;
  };
  const payload = {
    name: get('name'),
    reference_title: get('reference_title'),
    tmdb_title: get('tmdb_title'),
    bgm_url: get('bgm_url'),
    air_date: get('air_date') || null,
    season: integer('season', 1),
    primary_rss_name: get('primary_rss_name'),
    rss_url: get('rss_url'),
    backup_rss_name: get('backup_rss_name'),
    backup_rss_url: get('backup_rss_url') || null,
    include_keywords: get('include_keywords'),
    exclude_keywords: get('exclude_keywords'),
    episode_regex: get('episode_regex'),
    episode_group: integer('episode_group', 0),
    episode_offset: integer('episode_offset', 0),
    total_episodes: integer('total_episodes', 0),
    save_path_template: get('save_path_template') || '{base}/{subscription}/Season {season}',
    custom_download_path: get('custom_download_path'),
    missing_detection: subscriptionForm.elements.missing_detection.checked,
    only_latest: subscriptionForm.elements.only_latest.checked,
    enabled: subscriptionForm.elements.enabled.checked,
  };
  if (forPreview) {
    payload.sample_title = get('sample_title');
    if (!payload.rss_url) payload.rss_url = 'https://preview.invalid/feed.xml';
    if (!payload.name) payload.name = payload.reference_title || '未命名订阅';
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
  form.elements.download_path.value = data.download_path || '/downloads/rss';
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
    'name', 'reference_title', 'tmdb_title', 'bgm_url', 'air_date', 'season',
    'primary_rss_name', 'rss_url', 'backup_rss_name', 'backup_rss_url',
    'include_keywords', 'exclude_keywords', 'episode_regex', 'episode_group',
    'episode_offset', 'total_episodes', 'save_path_template', 'custom_download_path',
    'missing_detection', 'only_latest', 'enabled', 'sample_title',
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

function renderMikanDetail(detail) {
  const container = document.getElementById('mikanDetailBody');
  container.replaceChildren();

  const summary = document.createElement('div');
  summary.className = 'mikan-detail-summary';
  summary.append(text('strong', `${detail.groups.length} 个字幕组 RSS`));
  if (detail.detail_url) summary.append(externalLink('打开 Mikan 番剧页', detail.detail_url));
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

async function openMikanDetail(item) {
  openMikanModal(item.title);
  try {
    const params = new URLSearchParams({
      base_url: item.base_url || '',
      title: item.title || '',
    });
    const detail = await api(`/api/discovery/mikan/${item.bangumi_id}?${params.toString()}`);
    document.getElementById('mikanDetailTitle').textContent = detail.title;
    renderMikanDetail(detail);
  } catch (error) {
    const body = document.getElementById('mikanDetailBody');
    body.replaceChildren(text('p', error.message, 'error-text'));
  }
}

function createMikanCard(item) {
  const card = document.createElement('button');
  card.type = 'button';
  card.className = 'mikan-anime-card';
  card.addEventListener('click', () => openMikanDetail(item));

  const cover = document.createElement('div');
  cover.className = 'mikan-cover';
  if (item.cover_url) {
    const image = document.createElement('img');
    image.src = item.cover_url;
    image.alt = item.title;
    image.loading = 'lazy';
    image.referrerPolicy = 'no-referrer';
    image.addEventListener('error', () => {
      image.remove();
      cover.append(text('span', item.title.slice(0, 1) || '番'));
    }, { once: true });
    cover.append(image);
  } else cover.append(text('span', item.title.slice(0, 1) || '番'));

  const info = document.createElement('div');
  info.className = 'mikan-anime-info';
  info.append(text('strong', item.title));
  if (item.update_at) info.append(text('span', item.update_at, 'muted'));
  info.append(text('span', '点击查看字幕组 RSS', 'catalog-card-action'));
  card.append(cover, info);
  return card;
}

function renderMikanCatalog(data) {
  const container = document.getElementById('mikanCatalog');
  const state = document.getElementById('mikanCatalogState');
  container.replaceChildren();
  const count = data.rows.reduce((sum, row) => sum + row.items.length, 0);
  if (!count) {
    state.textContent = data.query
      ? `${data.year} ${data.season}没有匹配“${data.query}”的番剧。`
      : `${data.year} ${data.season}没有解析到番剧。`;
    state.className = 'hint';
    return;
  }

  state.textContent = `${data.year} ${data.season} · ${data.rows.length} 个播出日 · ${count} 部番剧`;
  state.className = 'hint';
  for (const row of data.rows) {
    const section = document.createElement('section');
    section.className = 'mikan-weekday-section';
    const heading = document.createElement('div');
    heading.className = 'mikan-weekday-head';
    heading.append(text('h3', row.weekday));
    heading.append(text('span', `${row.items.length} 部`, 'muted'));
    const grid = document.createElement('div');
    grid.className = 'mikan-anime-grid';
    row.items.forEach((item) => grid.append(createMikanCard(item)));
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

async function loadMikanCatalog(form) {
  const button = document.getElementById('loadMikanCatalog');
  const state = document.getElementById('mikanCatalogState');
  const year = form.elements.year.value;
  const season = form.elements.season.value;
  const query = form.elements.query.value.trim();
  button.disabled = true;
  button.textContent = '正在加载…';
  state.textContent = `正在读取 Mikan ${year} ${season}番剧目录…`;
  state.className = 'hint';
  try {
    const params = new URLSearchParams({ year, season });
    if (query) params.set('q', query);
    const data = await api(`/api/discovery/mikan/catalog?${params.toString()}`);
    renderMikanCatalog(data);
  } catch (error) {
    document.getElementById('mikanCatalog').replaceChildren();
    state.textContent = error.message;
    state.className = 'hint error-text';
  } finally {
    button.disabled = false;
    button.textContent = '加载番剧';
  }
}

function populateSubscriptionForm(sub) {
  const fields = [
    'name', 'reference_title', 'tmdb_title', 'bgm_url', 'air_date', 'season',
    'primary_rss_name', 'rss_url', 'backup_rss_name', 'backup_rss_url',
    'include_keywords', 'exclude_keywords', 'episode_regex', 'episode_group',
    'episode_offset', 'total_episodes', 'save_path_template', 'custom_download_path',
    'missing_detection', 'only_latest', 'enabled',
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
  if (!data.length) {
    container.append(text('p', '还没有订阅。请先添加一个你有权使用的 RSS 地址。', 'empty'));
    return;
  }

  for (const sub of data) {
    const card = document.createElement('article');
    card.className = 'subscription-card';

    const titleRow = document.createElement('div');
    titleRow.className = 'subscription-title';
    titleRow.append(text('h3', sub.name));
    titleRow.append(text('span', sub.enabled ? '启用' : '停用', `badge ${sub.enabled ? 'queued' : 'skipped'}`));
    card.append(titleRow);

    const meta = document.createElement('div');
    meta.className = 'subscription-meta';
    meta.append(text('span', `参考标题：${sub.reference_title || '—'}`));
    meta.append(text('span', `主 RSS：${sub.primary_rss_name || '未命名'} · ${sub.rss_url}`));
    if (sub.backup_rss_url) meta.append(text('span', `备用 RSS：${sub.backup_rss_name || '未命名'} · ${sub.backup_rss_url}`));
    meta.append(text('span', `季 ${sub.season} · 偏移 ${sub.episode_offset} · 总集数 ${sub.total_episodes || '未知'}`));
    meta.append(text('span', `路径：${sub.custom_download_path || sub.save_path_template}`));
    meta.append(text('span', `策略：${sub.only_latest ? '只下载最新集' : '下载全部匹配'} · ${sub.missing_detection ? '遗漏检测开启' : '遗漏检测关闭'}`));
    if (sub.missing_detection) {
      const missing = sub.missing_episodes.length ? sub.missing_episodes.join(', ') : '无';
      meta.append(text('span', `遗漏集数：${missing}`));
    }
    card.append(meta);

    card.append(text('p', `匹配：${sub.include_keywords || '无'} ｜ 排除：${sub.exclude_keywords || '无'}`));
    card.append(text(
      'p',
      `上次检查：${fmtDate(sub.last_checked_at)}${sub.last_error ? ` ｜ ${sub.last_error}` : ''}`,
      sub.last_error ? 'error-text' : 'muted',
    ));

    const controls = document.createElement('div');
    controls.className = 'card-actions';
    const edit = text('button', '编辑', 'secondary');
    edit.addEventListener('click', () => populateSubscriptionForm(sub));
    const toggle = text('button', sub.enabled ? '停用' : '启用', 'secondary');
    toggle.addEventListener('click', async () => {
      await api(`/api/subscriptions/${sub.id}`, { method: 'PATCH', body: JSON.stringify({ enabled: !sub.enabled }) });
      showNotice('订阅状态已更新');
      await reloadAll();
    });
    const remove = text('button', '删除', 'danger');
    remove.addEventListener('click', async () => {
      if (!window.confirm(`确定删除“${sub.name}”及其历史记录吗？`)) return;
      await api(`/api/subscriptions/${sub.id}`, { method: 'DELETE' });
      if (subscriptionForm.elements.subscription_id.value === String(sub.id)) resetSubscriptionForm();
      showNotice('订阅已删除');
      await reloadAll();
    });
    controls.append(edit, toggle, remove);
    card.append(controls);
    container.append(card);
  }
}

async function loadItems() {
  const status = document.getElementById('statusFilter').value;
  const data = await api(`/api/items?limit=100${status ? `&status=${encodeURIComponent(status)}` : ''}`);
  const tbody = document.getElementById('items');
  tbody.replaceChildren();
  if (!data.length) {
    const row = document.createElement('tr');
    const cell = text('td', '暂无记录');
    cell.colSpan = 6;
    row.append(cell);
    tbody.append(row);
    return;
  }
  for (const item of data) {
    const row = document.createElement('tr');
    row.append(text('td', fmtDate(item.created_at)));
    const titleCell = document.createElement('td');
    if (item.source_url) {
      const link = text('a', item.title);
      link.href = item.source_url;
      link.target = '_blank';
      link.rel = 'noreferrer noopener';
      titleCell.append(link);
    } else titleCell.textContent = item.title;
    row.append(titleCell);
    row.append(text('td', item.episode || '—'));
    const statusCell = document.createElement('td');
    statusCell.append(text('span', ({ queued: '已推送', skipped: '已跳过', error: '错误', discovered: '发现' })[item.status] || item.status, `badge ${item.status}`));
    row.append(statusCell);
    row.append(text('td', item.reason || '—'));
    const actionCell = document.createElement('td');
    if (item.status === 'error') {
      const retry = text('button', '重试', 'small secondary');
      retry.addEventListener('click', async () => {
        const result = await api(`/api/items/${item.id}/retry`, { method: 'POST' });
        showNotice(result.message, result.ok);
        await reloadAll();
      });
      actionCell.append(retry);
    }
    row.append(actionCell);
    tbody.append(row);
  }
}

async function loadLogs() {
  const data = await api('/api/logs?limit=50');
  const container = document.getElementById('logs');
  container.replaceChildren();
  if (!data.length) {
    container.append(text('p', '暂无日志。', 'empty'));
    return;
  }
  for (const log of data) {
    const row = document.createElement('div');
    row.className = 'log-row';
    row.append(text('time', fmtDate(log.created_at)));
    row.append(text('span', log.level, `badge ${log.level === 'ERROR' ? 'error' : 'queued'}`));
    row.append(text('strong', log.message));
    row.append(text('span', log.details, 'muted'));
    container.append(row);
  }
}

async function reloadAll() {
  try {
    await loadAuth();
    await Promise.all([
      loadDashboard(), loadConfig(), loadDownloaderSettings(), loadGlobalRules(),
      loadSubscriptions(), loadItems(), loadLogs(),
    ]);
  } catch (error) {
    showNotice(error.message, false);
  }
}

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
  await loadMikanCatalog(event.currentTarget);
});

document.getElementById('clearMikanCatalog').addEventListener('click', () => {
  const form = document.getElementById('mikanCatalogForm');
  form.elements.query.value = '';
  document.getElementById('mikanCatalog').replaceChildren();
  const state = document.getElementById('mikanCatalogState');
  state.textContent = '已清空。点击“加载番剧”重新读取所选季度。';
  state.className = 'hint';
});

document.getElementById('closeMikanModal').addEventListener('click', closeMikanModal);
document.querySelector('[data-close-mikan-modal]').addEventListener('click', closeMikanModal);
document.addEventListener('keydown', (event) => {
  if (event.key === 'Escape') closeMikanModal();
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
      `原始集数：${result.parsed_episode || '未识别'}`,
      `偏移后集数：${result.adjusted_episode || '未识别'}`,
      `最终下载位置：${result.save_path}`,
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

document.getElementById('statusFilter').addEventListener('change', loadItems);
initializeCatalogSelectors();
resetSubscriptionForm();
reloadAll();
