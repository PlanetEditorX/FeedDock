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

function discoveryProviderLabel(provider) {
  return provider === 'mikan' ? 'Mikan' : provider === 'dmhy' ? '动漫花园' : provider;
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

function renderMikanGroups(result, detail, container) {
  container.replaceChildren();
  const header = document.createElement('div');
  header.className = 'discovery-group-head';
  header.append(text('strong', `${detail.title} · ${detail.groups.length} 个字幕组`));
  if (detail.detail_url) header.append(externalLink('打开番剧页', detail.detail_url));
  container.append(header);

  if (!detail.groups.length) {
    container.append(text('p', '没有解析到字幕组，可打开番剧页确认站点是否调整了页面结构。', 'empty'));
    return;
  }

  const list = document.createElement('div');
  list.className = 'discovery-groups';
  for (const group of detail.groups) {
    const item = document.createElement('div');
    item.className = 'discovery-group';
    const info = document.createElement('div');
    info.append(text('strong', group.name));
    info.append(text('span', `Subgroup ID ${group.subgroup_id}`, 'muted'));
    const actions = document.createElement('div');
    actions.className = 'card-actions';
    const choose = text('button', '选择并填入', 'small');
    choose.type = 'button';
    choose.addEventListener('click', () => applyDiscoveryPreset(group.preset));
    actions.append(choose);
    if (group.detail_url) actions.append(externalLink('字幕组页面', group.detail_url));
    item.append(info, actions);
    list.append(item);
  }
  container.append(list);
}

async function loadMikanGroups(result, container, button) {
  button.disabled = true;
  button.textContent = '正在读取字幕组…';
  try {
    const params = new URLSearchParams({
      base_url: result.base_url || '',
      title: result.title || '',
    });
    const detail = await api(`/api/discovery/mikan/${result.bangumi_id}?${params.toString()}`);
    renderMikanGroups(result, detail, container);
    button.textContent = '重新读取字幕组';
  } catch (error) {
    container.replaceChildren(text('p', error.message, 'error-text'));
    button.textContent = '重试读取字幕组';
  } finally {
    button.disabled = false;
  }
}

function renderDiscoveryResults(data) {
  const container = document.getElementById('sourceSearchResults');
  const state = document.getElementById('sourceSearchState');
  container.replaceChildren();

  const errorText = (data.errors || []).join('；');
  if (!data.results.length) {
    state.textContent = errorText || `没有找到与“${data.query}”相关的结果。`;
    state.className = errorText ? 'hint error-text' : 'hint';
    return;
  }

  state.textContent = `找到 ${data.results.length} 项结果${errorText ? `；部分来源失败：${errorText}` : ''}`;
  state.className = errorText ? 'hint error-text' : 'hint';

  for (const result of data.results) {
    const card = document.createElement('article');
    card.className = 'discovery-card';

    const titleRow = document.createElement('div');
    titleRow.className = 'discovery-title';
    titleRow.append(text('span', discoveryProviderLabel(result.provider), `provider-badge ${result.provider}`));
    titleRow.append(text('h3', result.title));
    card.append(titleRow);

    if (result.description) card.append(text('p', result.description, 'muted'));
    const meta = document.createElement('div');
    meta.className = 'discovery-meta';
    if (result.published_at) meta.append(text('span', `发布时间：${fmtDate(result.published_at)}`));
    if (result.rss_url) meta.append(text('span', `RSS：${result.rss_url}`));
    card.append(meta);

    const actions = document.createElement('div');
    actions.className = 'card-actions';
    if (result.result_type === 'bangumi' && result.bangumi_id) {
      const choose = text('button', '选择字幕组');
      choose.type = 'button';
      const groupBox = document.createElement('div');
      groupBox.className = 'discovery-group-box';
      choose.addEventListener('click', () => loadMikanGroups(result, groupBox, choose));
      actions.append(choose);
      if (result.detail_url) actions.append(externalLink('打开 Mikan', result.detail_url));
      card.append(actions, groupBox);
    } else {
      if (result.preset) {
        const choose = text(
          'button',
          result.result_type === 'feed' ? '使用此关键词 RSS' : '用此条目预填',
        );
        choose.type = 'button';
        choose.addEventListener('click', () => applyDiscoveryPreset(result.preset));
        actions.append(choose);
      }
      if (result.source_url) actions.append(externalLink('打开来源', result.source_url));
      card.append(actions);
    }
    container.append(card);
  }
}

async function searchSources(form) {
  const button = document.getElementById('sourceSearchButton');
  const state = document.getElementById('sourceSearchState');
  const query = form.elements.query.value.trim();
  const provider = form.elements.provider.value;
  if (!query) return;
  button.disabled = true;
  button.textContent = '正在搜索…';
  state.textContent = `正在请求 ${provider === 'all' ? 'Mikan 和动漫花园' : discoveryProviderLabel(provider)}…`;
  state.className = 'hint';
  try {
    const params = new URLSearchParams({ q: query, provider, limit: '20' });
    const data = await api(`/api/discovery/search?${params.toString()}`);
    renderDiscoveryResults(data);
  } catch (error) {
    document.getElementById('sourceSearchResults').replaceChildren();
    state.textContent = error.message;
    state.className = 'hint error-text';
  } finally {
    button.disabled = false;
    button.textContent = '搜索';
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

document.getElementById('sourceSearchForm').addEventListener('submit', async (event) => {
  event.preventDefault();
  await searchSources(event.currentTarget);
});

document.getElementById('clearSourceSearch').addEventListener('click', () => {
  document.getElementById('sourceSearchForm').reset();
  document.getElementById('sourceSearchResults').replaceChildren();
  const state = document.getElementById('sourceSearchState');
  state.textContent = '不会自动请求外部站点，只有点击“搜索”时才访问所选来源。';
  state.className = 'hint';
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
resetSubscriptionForm();
reloadAll();
