(function (root, factory) {
  const api = factory();
  if (typeof module === 'object' && module.exports) module.exports = api;
  root.FeedDockNavigation = api;
})(typeof globalThis !== 'undefined' ? globalThis : this, function () {
  const DEFAULT_VIEW = 'subscriptions';
  const VIEW_META = Object.freeze({
    subscriptions: ['订阅列表', '查看当前订阅、运行状态与最近检查结果。'],
    'add-catalog': ['番剧周历', '按星期浏览稳定订阅站点，并生成站点专用 RSS。'],
    'add-subscription': ['添加订阅', '添加或编辑站点生成的订阅，以及任意其它 RSS。'],
    downloads: ['下载', '查看最近发现、推送和完成处理的条目。'],
    'settings-page': ['页面设置', '配置主题色与订阅列表排序。'],
    'settings-scrape': ['刮削设置', '配置自动元数据同步、TMDB 与 bangumi.ini。'],
    'settings-download': ['下载设置', '配置 qBittorrent、重试、并发和做种时长。'],
    'settings-rss': ['RSS 设置', '配置轮询、超时、自动跳过和订阅自动化。'],
    'settings-trackers': ['Trackers', '配置并更新追加到下载任务的 Tracker 列表。'],
    'settings-proxy': ['代理设置', '配置外部 RSS、元数据与更新请求使用的代理。'],
    'settings-login': ['登录设置', '查看当前账号并修改登录密码。'],
    'settings-notification': ['通知设置', '配置通知事件、消息模板与发送渠道。'],
    'settings-system': ['系统管理', '检查更新、退出、重启或关闭 FeedDock。'],
    logs: ['日志', '查看运行日志并调整日志级别。'],
  });

  function normalizeView(value) {
    const view = String(value || '').replace(/^#/, '').trim();
    return Object.prototype.hasOwnProperty.call(VIEW_META, view) ? view : DEFAULT_VIEW;
  }

  function setMenuExpanded(menu, expanded) {
    const summary = menu?.querySelector(':scope > summary');
    if (summary) summary.setAttribute('aria-expanded', String(Boolean(expanded)));
  }

  function closeMenus(doc = document, except = null) {
    doc.querySelectorAll('.nav-menu').forEach((menu) => {
      if (menu !== except && menu.hasAttribute('open')) menu.removeAttribute('open');
      setMenuExpanded(menu, menu === except ? menu.open : menu.hasAttribute('open'));
    });
  }

  function handleMenuToggle(menu, doc = document) {
    if (menu.open) closeMenus(doc, menu);
    setMenuExpanded(menu, menu.open);
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
    doc.querySelectorAll('.nav-menu').forEach((menu) => {
      setMenuExpanded(menu, menu.open);
      menu.addEventListener('toggle', () => handleMenuToggle(menu, doc));
    });
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
    doc.addEventListener('keydown', (event) => {
      if (event.key === 'Escape') closeMenus(doc);
    });
    if (typeof window !== 'undefined') {
      window.addEventListener('hashchange', () => showView(window.location.hash, { document: doc, updateHash: false }));
      showView(window.location.hash, { document: doc, updateHash: false, scroll: false });
    } else {
      showView(DEFAULT_VIEW, { document: doc, updateHash: false, scroll: false });
    }
  }

  return { DEFAULT_VIEW, VIEW_META, normalizeView, setMenuExpanded, closeMenus, handleMenuToggle, showView, initialize };
});
