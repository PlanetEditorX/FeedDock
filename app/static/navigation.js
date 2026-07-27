(function (root, factory) {
  const api = factory();
  if (typeof module === 'object' && module.exports) module.exports = api;
  root.FeedDockNavigation = api;
})(typeof globalThis !== 'undefined' ? globalThis : this, function () {
  const DEFAULT_VIEW = 'subscriptions';
  const VIEW_META = Object.freeze({
    subscriptions: ['订阅', '查看当前订阅、运行状态与最近检查结果。'],
    'add-mikan': ['Mikan 番剧目录', '从季度目录选择番剧和字幕组。'],
    'add-subscription': ['添加订阅', '添加或编辑 Mikan、ANI.BT、Anime Garden 及其它 RSS。'],
    downloads: ['下载', '查看最近发现、推送和完成处理的条目。'],
    'settings-download': ['下载设置', '配置 qBittorrent、保存目录和连接测试。'],
    'settings-basic': ['基本设置', '配置元数据、轮询时间和全局过滤规则。'],
    'settings-proxy': ['代理设置', '配置外部 RSS、元数据与更新请求使用的代理。'],
    'settings-login': ['登录设置', '查看当前账号并修改登录密码。'],
    'settings-notification': ['通知', '配置通知事件与消息渠道。'],
    'settings-system': ['系统管理', '检查更新、退出、重启或关闭 FeedDock。'],
    logs: ['日志', '查看运行日志并调整日志级别。'],
  });

  function normalizeView(value) {
    const view = String(value || '').replace(/^#/, '').trim();
    return Object.prototype.hasOwnProperty.call(VIEW_META, view) ? view : DEFAULT_VIEW;
  }

  function closeMenus(doc = document) {
    doc.querySelectorAll('.nav-menu[open]').forEach((menu) => menu.removeAttribute('open'));
  }

  function showView(value, options = {}) {
    const doc = options.document || document;
    const view = normalizeView(value);
    doc.querySelectorAll('[data-app-view]').forEach((element) => {
      const visible = element.dataset.appView === view || element.dataset.appView === 'all';
      element.classList.toggle('hidden', !visible);
    });
    const [title, description] = VIEW_META[view];
    const titleElement = doc.getElementById('viewTitle');
    const descriptionElement = doc.getElementById('viewDescription');
    if (titleElement) titleElement.textContent = title;
    if (descriptionElement) descriptionElement.textContent = description;
    doc.body.dataset.currentView = view;
    doc.querySelectorAll('[data-view-target]').forEach((element) => {
      element.classList.toggle('is-active', element.dataset.viewTarget === view);
    });
    closeMenus(doc);
    if (options.updateHash !== false && typeof history !== 'undefined') {
      history.replaceState(null, '', `#${view}`);
    }
    if (typeof CustomEvent !== 'undefined') {
      doc.dispatchEvent(new CustomEvent('feeddock:viewchange', {
        detail: { view, management: Boolean(options.management) },
      }));
    }
    if (options.scroll !== false && typeof window !== 'undefined') window.scrollTo({ top: 0, behavior: 'smooth' });
    return view;
  }

  function initialize(doc = document) {
    doc.querySelectorAll('[data-view-target]').forEach((element) => {
      element.addEventListener('click', (event) => {
        event.preventDefault();
        showView(element.dataset.viewTarget, {
          document: doc,
          management: element.dataset.managementMode === 'true',
        });
      });
    });
    doc.addEventListener('click', (event) => {
      if (!event.target.closest('.nav-menu')) closeMenus(doc);
    });
    if (typeof window !== 'undefined') {
      window.addEventListener('hashchange', () => showView(window.location.hash, { document: doc, updateHash: false }));
      showView(window.location.hash, { document: doc, updateHash: false, scroll: false });
    } else {
      showView(DEFAULT_VIEW, { document: doc, updateHash: false, scroll: false });
    }
  }

  return { DEFAULT_VIEW, VIEW_META, normalizeView, closeMenus, showView, initialize };
});
