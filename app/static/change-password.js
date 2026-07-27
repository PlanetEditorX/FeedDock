let returnToLoginSettings = false;
fetch('/api/auth/status').then((response) => response.json()).then((status) => {
  if (!status.authenticated) { window.location.replace('/login'); return; }
  if (!status.must_change_password) {
    returnToLoginSettings = true;
    document.getElementById('passwordPageBadge').textContent = '登录设置';
    document.getElementById('passwordPageBadge').className = 'badge queued';
    document.getElementById('passwordPageTitle').textContent = '修改登录密码';
    document.getElementById('passwordPageDescription').textContent = `当前账号：${status.username}。修改后其它旧会话将失效。`;
    document.getElementById('passwordSubmit').textContent = '保存新密码';
    document.getElementById('passwordPageBack').classList.remove('hidden');
  }
}).catch(() => {});

const form = document.getElementById('passwordForm');
const errorBox = document.getElementById('authError');
function showError(message) { errorBox.textContent = message; errorBox.classList.remove('hidden'); }
document.querySelectorAll('.password-toggle').forEach((button) => button.addEventListener('click', () => {
  const input = button.parentElement.querySelector('input'); input.type = input.type === 'password' ? 'text' : 'password';
}));
form.addEventListener('submit', async (event) => {
  event.preventDefault(); errorBox.classList.add('hidden');
  const values = Object.fromEntries(new FormData(form).entries());
  if (values.new_password !== values.confirm_password) { showError('两次输入的新密码不一致'); return; }
  const button = form.querySelector('button[type="submit"]'); button.disabled = true;
  try {
    const response = await fetch('/api/auth/change-password', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ current_password: values.current_password, new_password: values.new_password }) });
    const data = await response.json().catch(() => ({}));
    if (response.status === 401) { window.location.replace('/login'); return; }
    if (!response.ok) throw new Error(data.detail || `HTTP ${response.status}`);
    window.location.replace(returnToLoginSettings ? '/#settings-login' : '/');
  } catch (error) { showError(error.message); } finally { button.disabled = false; }
});
