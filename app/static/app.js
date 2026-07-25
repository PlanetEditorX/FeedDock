const notice = document.getElementById('notice');

function showNotice(message, ok = true) {
  notice.textContent = message;
  notice.className = `notice ${ok ? 'ok' : 'bad'}`;
  window.clearTimeout(showNotice.timer);
  showNotice.timer = window.setTimeout(() => notice.classList.add('hidden'), 6000);
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
  if (data.qbit_url) {
    qbitState = data.configured ? data.qbit_url : `${data.qbit_url}（配置不完整）`;
  }
  document.getElementById('configSummary').textContent =
    `轮询 ${data.poll_interval_minutes} 分钟 · qBittorrent ${qbitState} · 保存根目录 ${data.download_path}`;
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
  } else {
    releaseLink.classList.add('hidden');
  }

  const apply = document.getElementById('applyUpdate');
  if (data.update_available && data.updater_configured) {
    apply.classList.remove('hidden');
  } else {
    apply.classList.add('hidden');
  }

  if (showResult) showNotice(data.message, !data.message.startsWith('检查更新失败'));
}

async function loadSubscriptions() {
  const container = document.getElementById('subscriptions');
  const data = await api('/api/subscriptions');
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
    card.append(text('p', sub.rss_url, 'url'));
    card.append(text('p', `包含：${sub.include_keywords || '不限'} ｜ 排除：${sub.exclude_keywords || '无'}`));
    card.append(text('p', `上次检查：${fmtDate(sub.last_checked_at)}${sub.last_error ? ` ｜ ${sub.last_error}` : ''}`, sub.last_error ? 'error-text' : 'muted'));

    const controls = document.createElement('div');
    controls.className = 'card-actions';
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
      showNotice('订阅已删除');
      await reloadAll();
    });
    controls.append(toggle, remove);
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
    await Promise.all([loadDashboard(), loadConfig(), loadDownloaderSettings(), loadSubscriptions(), loadItems(), loadLogs()]);
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

document.getElementById('subscriptionForm').addEventListener('submit', async (event) => {
  event.preventDefault();

  // Event.currentTarget is only guaranteed during the synchronous event
  // dispatch. Keep a stable form reference before the first await.
  const formElement = event.currentTarget;
  const formData = new FormData(formElement);
  const payload = Object.fromEntries(formData.entries());
  try {
    await api('/api/subscriptions', { method: 'POST', body: JSON.stringify(payload) });
    formElement.reset();
    formElement.elements.save_path_template.value = '{base}/{subscription}';
    showNotice('订阅已保存');
    await reloadAll();
  } catch (error) { showNotice(error.message, false); }
});

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

document.getElementById('checkUpdate').addEventListener('click', async () => {
  try { await loadUpdateStatus(true); } catch (error) { showNotice(error.message, false); }
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
reloadAll().then(() => loadUpdateStatus(false).catch(() => {}));
