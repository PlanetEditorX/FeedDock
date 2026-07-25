const state = {
  catalog: null,
  editingWeekday: null,
  subscriptions: [],
};

const $ = (selector, root = document) => root.querySelector(selector);
const $$ = (selector, root = document) => [...root.querySelectorAll(selector)];

function toast(message, error = false) {
  const node = $('#toast');
  node.textContent = String(message);
  node.className = `toast${error ? ' error' : ''}`;
  node.hidden = false;
  clearTimeout(toast.timer);
  toast.timer = setTimeout(() => { node.hidden = true; }, 4500);
}

async function api(url, options = {}) {
  const response = await fetch(url, {
    credentials: 'same-origin',
    headers: { 'Content-Type': 'application/json', ...(options.headers || {}) },
    ...options,
  });
  const type = response.headers.get('content-type') || '';
  const data = type.includes('application/json') ? await response.json() : await response.text();
  if (!response.ok) {
    const detail = data?.detail || data?.message || data || `HTTP ${response.status}`;
    const error = new Error(typeof detail === 'string' ? detail : JSON.stringify(detail));
    error.status = response.status;
    throw error;
  }
  return data;
}

function showView(name) {
  $('#login-view').hidden = name !== 'login';
  $('#password-view').hidden = name !== 'password';
  $('#app-view').hidden = name !== 'app';
}

async function bootstrap() {
  const now = new Date();
  $('#catalog-year').value = now.getFullYear();
  const month = now.getMonth() + 1;
  $('#catalog-season').value = month <= 3 ? 'winter' : month <= 6 ? 'spring' : month <= 9 ? 'summer' : 'fall';
  try {
    const me = await api('/api/me');
    if (me.must_change_password) {
      showView('password');
      return;
    }
    showView('app');
    $('#version').textContent = `v${me.version}`;
    await Promise.all([loadDashboard(), loadSubscriptions(), loadQbit(), loadLogs()]);
  } catch (error) {
    if (error.status === 401) showView('login');
    else toast(error.message, true);
  }
}

$('#login-form').addEventListener('submit', async (event) => {
  event.preventDefault();
  const form = event.currentTarget;
  const payload = Object.fromEntries(new FormData(form));
  try {
    const result = await api('/api/auth/login', { method: 'POST', body: JSON.stringify(payload) });
    if (result.must_change_password) {
      $('#password-form [name="current_password"]').value = payload.password;
      showView('password');
    } else {
      location.reload();
    }
  } catch (error) { toast(error.message, true); }
});

$('#password-form').addEventListener('submit', async (event) => {
  event.preventDefault();
  const form = event.currentTarget;
  const values = Object.fromEntries(new FormData(form));
  if (values.new_password !== values.confirm_password) return toast('两次输入的新密码不一致', true);
  try {
    await api('/api/auth/change-password', {
      method: 'POST',
      body: JSON.stringify({ current_password: values.current_password, new_password: values.new_password }),
    });
    toast('密码已修改，请使用新密码登录');
    form.reset();
    showView('login');
  } catch (error) { toast(error.message, true); }
});

$('#logout').addEventListener('click', async () => {
  await api('/api/auth/logout', { method: 'POST' }).catch(() => null);
  location.reload();
});

async function loadDashboard() {
  const data = await api('/api/dashboard');
  const labels = [
    ['订阅总数', data.subscriptions], ['启用订阅', data.enabled], ['已见条目', data.items], ['错误任务', data.errors],
  ];
  $('#stats').innerHTML = labels.map(([name, value]) => `<div class="stat"><span>${escapeHtml(name)}</span><strong>${value}</strong></div>`).join('');
}

$('#check-update').addEventListener('click', async (event) => {
  const button = event.currentTarget;
  button.disabled = true;
  try {
    const data = await api('/api/update/check', { method: 'POST' });
    toast(data.has_update ? `发现新版本 ${data.latest_version}\n${data.name || ''}` : `当前已是最新版本 ${data.current_version}`);
  } catch (error) { toast(error.message, true); }
  finally { button.disabled = false; }
});

function catalogParams(extra = {}) {
  const params = new URLSearchParams({
    year: $('#catalog-year').value,
    season: $('#catalog-season').value,
    ...extra,
  });
  return params.toString();
}

async function loadCatalog({ force = false, editingWeekday = null } = {}) {
  const button = force ? $('#force-catalog') : $('#load-catalog');
  button.disabled = true;
  $('#catalog-meta').textContent = force ? '正在强制更新 Mikan 数据…' : '正在读取缓存…';
  try {
    const includeHidden = editingWeekday !== null;
    const url = force
      ? `/api/discovery/mikan/catalog/refresh?${catalogParams({ include_hidden: includeHidden })}`
      : `/api/discovery/mikan/catalog?${catalogParams({ include_hidden: includeHidden })}`;
    state.catalog = await api(url, { method: force ? 'POST' : 'GET' });
    state.editingWeekday = editingWeekday;
    renderCatalog();
  } catch (error) {
    $('#catalog-meta').textContent = '';
    toast(error.message, true);
  } finally { button.disabled = false; }
}

$('#load-catalog').addEventListener('click', () => loadCatalog());
$('#force-catalog').addEventListener('click', () => loadCatalog({ force: true }));
$('#catalog-search').addEventListener('input', renderCatalog);

function renderCatalog() {
  const data = state.catalog;
  if (!data) {
    $('#catalog').innerHTML = '<div class="empty">选择年份和季度后读取目录</div>';
    return;
  }
  const time = new Date(data.fetched_at).toLocaleString();
  $('#catalog-meta').textContent = `缓存时间：${time} ｜ 数据来源：${data.data_source === 'remote' ? '刚从 Mikan 获取' : '本地缓存'} ｜ 共 ${data.total_count} 部，隐藏 ${data.hidden_count} 部${data.stale ? ' ｜ 缓存已超过更新周期，后台将尝试更新' : ''}`;
  const query = $('#catalog-search').value.trim().toLocaleLowerCase();
  const sections = [];
  for (const group of data.groups) {
    const editing = state.editingWeekday === group.weekday;
    let items = group.items.filter(item => !item.hidden || editing);
    if (query) items = items.filter(item => item.title.toLocaleLowerCase().includes(query));
    if (!items.length && query) continue;
    const hiddenInWeek = Number(group.hidden_count || group.items.filter(item => item.hidden).length);
    sections.push(`
      <section class="week-section" data-weekday="${group.weekday}">
        <div class="week-head">
          <div class="week-title"><h3>${escapeHtml(group.name)}</h3><span class="badge">${items.length} 部${hiddenInWeek ? ` · 隐藏 ${hiddenInWeek}` : ''}</span></div>
          <div class="week-actions">
            ${editing ? `
              <button class="show-all-week" data-weekday="${group.weekday}">本周全部显示</button>
              <button class="cancel-filter" data-weekday="${group.weekday}">取消</button>
              <button class="save-filter primary" data-weekday="${group.weekday}">保存过滤</button>
            ` : `<button class="edit-filter ghost" data-weekday="${group.weekday}">编辑过滤</button>`}
          </div>
        </div>
        <div class="card-grid">
          ${items.length ? items.map(item => animeCard(item, editing)).join('') : '<div class="empty">本星期没有可显示的番剧</div>'}
        </div>
      </section>
    `);
  }
  $('#catalog').innerHTML = sections.join('') || '<div class="empty">没有符合筛选条件的番剧</div>';
  bindCatalogEvents();
}

function animeCard(item, editing) {
  const cover = item.cover_proxy_url || item.cover_url;
  return `
    <article class="anime-card ${editing ? 'editing' : ''} ${item.hidden ? 'hidden-item' : ''}"
      data-id="${item.bangumi_id}" data-base="${escapeAttr(item.base_url || '')}" data-title="${escapeAttr(item.title)}">
      ${editing ? `<label class="hide-toggle"><input type="checkbox" class="hide-checkbox" ${item.hidden ? 'checked' : ''}>隐藏</label>` : ''}
      <div class="cover">
        ${cover ? `<img src="${escapeAttr(cover)}" alt="${escapeAttr(item.title)}" loading="lazy" referrerpolicy="no-referrer">` : `<div class="cover-fallback">暂无封面</div>`}
      </div>
      <div class="card-body">
        <div class="card-title">${escapeHtml(item.title)}</div>
        <div class="card-update">${escapeHtml(item.update_at || '')}</div>
      </div>
    </article>`;
}

function bindCatalogEvents() {
  $$('.cover img', $('#catalog')).forEach(image => image.addEventListener('error', () => {
    const fallback = document.createElement('div');
    fallback.className = 'cover-fallback';
    fallback.textContent = '封面加载失败';
    image.replaceWith(fallback);
  }, { once: true }));

  $$('.edit-filter', $('#catalog')).forEach(button => button.addEventListener('click', async () => {
    await loadCatalog({ editingWeekday: Number(button.dataset.weekday) });
  }));
  $$('.cancel-filter', $('#catalog')).forEach(button => button.addEventListener('click', async () => {
    await loadCatalog();
  }));
  $$('.save-filter', $('#catalog')).forEach(button => button.addEventListener('click', saveWeekFilter));
  $$('.show-all-week', $('#catalog')).forEach(button => button.addEventListener('click', clearWeekFilter));
  $$('.anime-card:not(.editing)', $('#catalog')).forEach(card => card.addEventListener('click', () => openBangumi(card)));
}

async function saveWeekFilter(event) {
  const weekday = Number(event.currentTarget.dataset.weekday);
  const section = $(`.week-section[data-weekday="${weekday}"]`, $('#catalog'));
  const entries = $$('.anime-card', section)
    .filter(card => $('.hide-checkbox', card)?.checked)
    .map(card => ({ bangumi_id: Number(card.dataset.id), title: card.dataset.title }));
  const button = event.currentTarget;
  button.disabled = true;
  try {
    await api(`/api/discovery/mikan/filters/${weekday}?${catalogParams()}`, {
      method: 'PUT', body: JSON.stringify({ entries }),
    });
    toast(`已保存${section.querySelector('h3').textContent}过滤：隐藏 ${entries.length} 部番剧`);
    await loadCatalog();
  } catch (error) { toast(error.message, true); }
  finally { button.disabled = false; }
}

async function clearWeekFilter(event) {
  const weekday = Number(event.currentTarget.dataset.weekday);
  if (!confirm('确定恢复显示本星期的全部番剧吗？')) return;
  try {
    await api(`/api/discovery/mikan/filters/${weekday}?${catalogParams()}`, { method: 'DELETE' });
    toast('本星期隐藏设置已清空');
    await loadCatalog();
  } catch (error) { toast(error.message, true); }
}

async function openBangumi(card) {
  const dialog = $('#bangumi-dialog');
  $('#bangumi-detail').innerHTML = '<p>正在解析番剧详情和字幕组 RSS…</p>';
  dialog.showModal();
  try {
    const params = new URLSearchParams({ base_url: card.dataset.base });
    const detail = await api(`/api/discovery/mikan/bangumi/${card.dataset.id}?${params}`);
    $('#bangumi-detail').innerHTML = `
      <h2>${escapeHtml(detail.title || card.dataset.title)}</h2>
      <p class="muted">番剧 ID：${detail.bangumi_id}</p>
      <div class="subgroup-list">
        ${detail.subgroups.length ? detail.subgroups.map(group => `
          <div class="subgroup">
            <strong>${escapeHtml(group.name)}</strong>
            <div class="rss-url">${escapeHtml(group.rss_url)}</div>
            <div class="form-actions">
              <button class="copy-rss" data-url="${escapeAttr(group.rss_url)}">复制 RSS</button>
              <button class="use-rss primary" data-url="${escapeAttr(group.rss_url)}" data-name="${escapeAttr(group.name)}" data-title="${escapeAttr(detail.title || card.dataset.title)}">订阅</button>
            </div>
          </div>`).join('') : '<div class="empty">未识别到带 ID 的字幕组，无法生成专用 RSS。</div>'}
      </div>`;
    $$('.copy-rss', $('#bangumi-detail')).forEach(button => button.addEventListener('click', async () => {
      await navigator.clipboard.writeText(button.dataset.url);
      toast('RSS 已复制');
    }));
    $$('.use-rss', $('#bangumi-detail')).forEach(button => button.addEventListener('click', () => {
      const form = $('#subscription-form');
      form.elements.name.value = button.dataset.title;
      form.elements.reference_title.value = button.dataset.title;
      form.elements.primary_rss_name.value = button.dataset.name;
      form.elements.primary_rss_url.value = button.dataset.url;
      dialog.close();
      form.scrollIntoView({ behavior: 'smooth', block: 'start' });
      toast('已带入订阅表单，请确认规则和下载路径后保存');
    }));
  } catch (error) { $('#bangumi-detail').innerHTML = `<div class="empty">${escapeHtml(error.message)}</div>`; }
}

$('#close-dialog').addEventListener('click', () => $('#bangumi-dialog').close());

async function loadSubscriptions() {
  state.subscriptions = await api('/api/subscriptions');
  if (!state.subscriptions.length) {
    $('#subscriptions').innerHTML = '<div class="empty">尚未添加订阅</div>';
    return;
  }
  $('#subscriptions').innerHTML = `<table><thead><tr><th>名称</th><th>主 RSS</th><th>下载路径</th><th>状态</th><th>最后检查</th><th>操作</th></tr></thead><tbody>${state.subscriptions.map(row => `
    <tr><td>${escapeHtml(row.name)}</td><td>${escapeHtml(row.primary_rss_name || '')}<br><span class="rss-url">${escapeHtml(row.primary_rss_url)}</span></td><td>${escapeHtml(row.download_path || '使用下载器默认')}</td><td>${row.enabled ? '启用' : '停用'}</td><td>${escapeHtml(row.last_checked_at || '—')}</td><td><div class="table-actions"><button data-action="edit" data-id="${row.id}">编辑</button><button data-action="refresh" data-id="${row.id}">刷新</button><button data-action="delete" data-id="${row.id}">删除</button></div></td></tr>`).join('')}</tbody></table>`;
  $$('[data-action]', $('#subscriptions')).forEach(button => button.addEventListener('click', subscriptionAction));
}

async function subscriptionAction(event) {
  const { action, id } = event.currentTarget.dataset;
  const row = state.subscriptions.find(item => String(item.id) === id);
  if (action === 'edit' && row) {
    const form = $('#subscription-form');
    Object.entries(row).forEach(([key, value]) => {
      const field = form.elements[key];
      if (!field) return;
      if (field.type === 'checkbox') field.checked = Boolean(value);
      else field.value = value ?? '';
    });
    form.scrollIntoView({ behavior: 'smooth' });
  }
  if (action === 'refresh') {
    event.currentTarget.disabled = true;
    try {
      const result = await api(`/api/subscriptions/${id}/refresh`, { method: 'POST' });
      toast(`刷新完成：新条目 ${result.new_count}，已推送 ${result.pushed_count}`);
      await Promise.all([loadSubscriptions(), loadDashboard(), loadLogs()]);
    } catch (error) { toast(error.message, true); }
    finally { event.currentTarget.disabled = false; }
  }
  if (action === 'delete' && confirm(`确定删除订阅“${row?.name || id}”吗？`)) {
    await api(`/api/subscriptions/${id}`, { method: 'DELETE' });
    toast('订阅已删除');
    await Promise.all([loadSubscriptions(), loadDashboard()]);
  }
}

$('#subscription-form').addEventListener('submit', async (event) => {
  event.preventDefault();
  const form = event.currentTarget; // Keep the reference before await; currentTarget becomes null afterwards in some browsers.
  const raw = Object.fromEntries(new FormData(form));
  const id = raw.id;
  const payload = {
    ...raw,
    season: Number(raw.season || 1), episode_group: Number(raw.episode_group || 0),
    episode_offset: Number(raw.episode_offset || 0), total_episodes: Number(raw.total_episodes || 0),
    missing_check: form.elements.missing_check.checked,
    latest_only: form.elements.latest_only.checked,
    enabled: form.elements.enabled.checked,
  };
  delete payload.id;
  try {
    await api(id ? `/api/subscriptions/${id}` : '/api/subscriptions', { method: id ? 'PUT' : 'POST', body: JSON.stringify(payload) });
    toast(id ? '订阅已更新' : '订阅已保存');
    resetSubscriptionForm();
    await Promise.all([loadSubscriptions(), loadDashboard()]);
  } catch (error) { toast(error.message, true); }
});

function resetSubscriptionForm() {
  const form = $('#subscription-form');
  form.reset();
  form.elements.id.value = '';
  form.elements.season.value = 1;
  form.elements.episode_group.value = 0;
  form.elements.episode_offset.value = 0;
  form.elements.total_episodes.value = 0;
  form.elements.enabled.checked = true;
}
$('#reset-subscription').addEventListener('click', resetSubscriptionForm);

async function loadQbit() {
  const data = await api('/api/settings/qbittorrent');
  const form = $('#qbit-form');
  for (const key of ['url', 'username', 'category', 'download_path']) form.elements[key].value = data[key] || '';
  form.elements.password.placeholder = data.has_password ? '已保存密码；留空保持不变' : '请输入密码';
}

$('#qbit-form').addEventListener('submit', async (event) => {
  event.preventDefault();
  const form = event.currentTarget;
  try {
    const result = await api('/api/settings/qbittorrent?test=true', { method: 'PUT', body: JSON.stringify(Object.fromEntries(new FormData(form))) });
    form.elements.password.value = '';
    toast(`保存成功，qBittorrent ${result.test.version} 连接正常`);
    await loadQbit();
  } catch (error) { toast(error.message, true); }
});
$('#test-qbit').addEventListener('click', async () => {
  try { const result = await api('/api/settings/qbittorrent/test', { method: 'POST' }); toast(`连接正常：qBittorrent ${result.version}`); }
  catch (error) { toast(error.message, true); }
});
$('#reset-qbit').addEventListener('click', async () => {
  if (!confirm('确定恢复 Compose 环境变量中的 qBittorrent 配置吗？')) return;
  await api('/api/settings/qbittorrent', { method: 'DELETE' });
  await loadQbit();
  toast('已恢复 Compose 默认配置');
});

async function loadLogs() {
  const rows = await api('/api/logs?limit=100');
  $('#logs').innerHTML = rows.length ? rows.map(row => `<div class="log-row ${escapeAttr(row.level)}"><strong>${escapeHtml(row.level.toUpperCase())}</strong> ${escapeHtml(row.message)}<br><span class="muted">${escapeHtml(row.created_at)}</span></div>`).join('') : '<div class="empty">暂无日志</div>';
}
$('#reload-logs').addEventListener('click', loadLogs);

function escapeHtml(value) {
  return String(value ?? '').replace(/[&<>'"]/g, char => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', "'": '&#39;', '"': '&quot;' }[char]));
}
function escapeAttr(value) { return escapeHtml(value); }

bootstrap();
