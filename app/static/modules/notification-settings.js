(function (root, factory) {
  const api = factory();
  if (typeof module === 'object' && module.exports) module.exports = api;
  root.FeedDockNotificationSettings = api;
})(typeof globalThis !== 'undefined' ? globalThis : this, function () {
  'use strict';

  const DEFAULT_TITLE_TEMPLATE = '{title}';
  const DEFAULT_BODY_TEMPLATE = '{message}';

  function create({ api, showNotice, document: doc = document, confirm: confirmAction = window.confirm }) {
    if (typeof api !== 'function') throw new Error('notification settings require an api function');
    if (typeof showNotice !== 'function') throw new Error('notification settings require a notice function');

    const form = doc.getElementById('notificationSettingsForm');
    const previewBox = doc.getElementById('notificationTemplatePreview');
    const barkEncryptionOptions = doc.getElementById('barkEncryptionOptions');
    const barkEncryptionKeyHint = doc.getElementById('barkEncryptionKeyHint');

    const BARK_KEY_LENGTHS = Object.freeze({ AES128: 16, AES192: 24, AES256: 32 });

    function updateBarkEncryptionFields() {
      const enabled = form.elements.bark_encryption_enabled.checked;
      barkEncryptionOptions?.classList.toggle('hidden', !enabled);
      const algorithm = form.elements.bark_encryption_algorithm.value || 'AES128';
      const keyLength = BARK_KEY_LENGTHS[algorithm] || 16;
      if (barkEncryptionKeyHint) barkEncryptionKeyHint.textContent = `${algorithm} 需要 ${keyLength} 个 ASCII 字符。`;
    }

    function valueOrNull(name) {
      return form.elements[name].value.trim() || null;
    }

    function exactValueOrNull(name) {
      const value = form.elements[name].value;
      return value === '' ? null : value;
    }

    function payload() {
      return {
        enabled: form.elements.enabled.checked,
        events: [...form.querySelectorAll('input[name="events"]:checked')].map((input) => input.value),
        title_template: form.elements.title_template.value.trim() || DEFAULT_TITLE_TEMPLATE,
        body_template: form.elements.body_template.value.trim() || DEFAULT_BODY_TEMPLATE,
        telegram_enabled: form.elements.telegram_enabled.checked,
        telegram_bot_token: valueOrNull('notification_telegram_bot_token'),
        clear_telegram_bot_token: form.elements.clear_telegram_bot_token.checked,
        telegram_chat_id: form.elements.telegram_chat_id.value.trim(),
        bark_enabled: form.elements.bark_enabled.checked,
        bark_server_url: form.elements.bark_server_url.value.trim() || 'https://api.day.app',
        bark_device_key: valueOrNull('notification_bark_device_key'),
        clear_bark_device_key: form.elements.clear_bark_device_key.checked,
        bark_encryption_enabled: form.elements.bark_encryption_enabled.checked,
        bark_encryption_algorithm: form.elements.bark_encryption_algorithm.value,
        bark_encryption_mode: form.elements.bark_encryption_mode.value,
        bark_encryption_padding: form.elements.bark_encryption_padding.value,
        bark_encryption_key: exactValueOrNull('notification_bark_encryption_key'),
        clear_bark_encryption_key: form.elements.clear_bark_encryption_key.checked,
        webhook_enabled: form.elements.webhook_enabled.checked,
        webhook_url: valueOrNull('notification_webhook_url'),
        clear_webhook_url: form.elements.clear_webhook_url.checked,
        webhook_headers_json: valueOrNull('notification_webhook_headers_json'),
        clear_webhook_headers: form.elements.clear_webhook_headers.checked,
      };
    }

    async function load() {
      const data = await api('/api/notifications/settings');
      form.elements.enabled.checked = Boolean(data.enabled);
      form.elements.title_template.value = data.title_template || DEFAULT_TITLE_TEMPLATE;
      form.elements.body_template.value = data.body_template || DEFAULT_BODY_TEMPLATE;
      form.elements.telegram_enabled.checked = Boolean(data.telegram_enabled);
      form.elements.telegram_chat_id.value = data.telegram_chat_id || '';
      form.elements.bark_enabled.checked = Boolean(data.bark_enabled);
      form.elements.bark_server_url.value = data.bark_server_url || 'https://api.day.app';
      form.elements.bark_encryption_enabled.checked = Boolean(data.bark_encryption_enabled);
      form.elements.bark_encryption_algorithm.value = data.bark_encryption_algorithm || 'AES128';
      form.elements.bark_encryption_mode.value = data.bark_encryption_mode || 'CBC';
      form.elements.bark_encryption_padding.value = data.bark_encryption_padding || 'pkcs7';
      form.elements.webhook_enabled.checked = Boolean(data.webhook_enabled);

      const events = new Set(data.events || []);
      form.querySelectorAll('input[name="events"]').forEach((input) => { input.checked = events.has(input.value); });

      const secrets = [
        ['notification_telegram_bot_token', data.telegram_bot_token_configured, '已保存 Token；留空保留'],
        ['notification_bark_device_key', data.bark_device_key_configured, '已保存 Key；留空保留'],
        ['notification_bark_encryption_key', data.bark_encryption_key_configured, '已保存加密 Key；留空保留'],
        ['notification_webhook_url', data.webhook_url_configured, '已保存地址；留空保留'],
        ['notification_webhook_headers_json', data.webhook_headers_configured, '已保存请求头；留空保留'],
      ];
      secrets.forEach(([name, configured, placeholder]) => {
        form.elements[name].value = '';
        form.elements[name].type = 'password';
        if (configured) form.elements[name].placeholder = placeholder;
      });
      ['clear_telegram_bot_token', 'clear_bark_device_key', 'clear_bark_encryption_key', 'clear_webhook_url', 'clear_webhook_headers']
        .forEach((name) => { form.elements[name].checked = false; });

      updateBarkEncryptionFields();

      const channels = (data.configured_channels || []).join('、') || '无';
      doc.getElementById('notificationConfigState').textContent = `${data.enabled ? '已启用' : '未启用'} · 可用渠道：${channels}`;
      return data;
    }

    async function save() {
      const data = await api('/api/notifications/settings', {
        method: 'PUT',
        body: JSON.stringify(payload()),
      });
      await load();
      return data;
    }

    async function preview() {
      const result = await api('/api/notifications/preview', {
        method: 'POST',
        body: JSON.stringify({
          event: form.elements.preview_event.value,
          title_template: form.elements.title_template.value.trim() || DEFAULT_TITLE_TEMPLATE,
          body_template: form.elements.body_template.value.trim() || DEFAULT_BODY_TEMPLATE,
        }),
      });
      previewBox.replaceChildren();
      const title = doc.createElement('strong');
      title.textContent = result.title;
      const body = doc.createElement('p');
      body.textContent = result.body || '（正文为空）';
      previewBox.append(title, body);
      previewBox.className = 'preview-box good notification-preview';
      return result;
    }

    function bind() {
      form.elements.bark_encryption_enabled.addEventListener('change', updateBarkEncryptionFields);
      form.elements.bark_encryption_algorithm.addEventListener('change', updateBarkEncryptionFields);

      form.addEventListener('submit', async (event) => {
        event.preventDefault();
        try {
          await save();
          showNotice('通知设置已保存');
        } catch (error) {
          showNotice(error.message, false);
        }
      });

      doc.getElementById('previewNotificationTemplate').addEventListener('click', async () => {
        try {
          await preview();
          showNotice('通知模板预览已更新');
        } catch (error) {
          previewBox.textContent = error.message;
          previewBox.className = 'preview-box bad';
          showNotice(error.message, false);
        }
      });

      doc.getElementById('testNotifications').addEventListener('click', async () => {
        try {
          await save();
          const result = await api('/api/notifications/test', { method: 'POST' });
          showNotice(result.message, result.ok);
        } catch (error) {
          showNotice(error.message, false);
        }
      });

      doc.getElementById('restoreNotifications').addEventListener('click', async () => {
        if (!confirmAction('确认清空网页保存的全部通知渠道、模板和密钥？')) return;
        try {
          await api('/api/notifications/settings', { method: 'DELETE' });
          await load();
          previewBox.textContent = '选择事件并点击“预览模板”。';
          previewBox.className = 'preview-box muted';
          showNotice('通知设置已清空');
        } catch (error) {
          showNotice(error.message, false);
        }
      });
    }

    return { bind, load, payload, preview, save, updateBarkEncryptionFields };
  }

  return { create, DEFAULT_TITLE_TEMPLATE, DEFAULT_BODY_TEMPLATE };
});
