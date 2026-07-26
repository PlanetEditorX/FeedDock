const form = document.getElementById('loginForm');
const errorBox = document.getElementById('authError');

function showError(message) { errorBox.textContent = message; errorBox.classList.remove('hidden'); }
function setupPasswordToggles() {
  document.querySelectorAll('.password-toggle').forEach((button) => button.addEventListener('click', () => {
    const input = button.parentElement.querySelector('input');
    input.type = input.type === 'password' ? 'text' : 'password';
    button.setAttribute('aria-label', input.type === 'password' ? '显示密码' : '隐藏密码');
  }));
}
async function loadInitialNote() {
  try {
    const response = await fetch('/api/auth/bootstrap');
    const data = await response.json();
    document.getElementById('initialPasswordNote').classList.toggle('hidden', !data.initial_password_change_required);
  } catch (_) {}
}
form.addEventListener('submit', async (event) => {
  event.preventDefault(); errorBox.classList.add('hidden');
  const button = form.querySelector('button[type="submit"]'); button.disabled = true;
  try {
    const payload = Object.fromEntries(new FormData(form).entries());
    const response = await fetch('/api/auth/login', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload) });
    const data = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(data.detail || `HTTP ${response.status}`);
    window.location.replace(data.must_change_password ? '/change-password' : '/');
  } catch (error) { showError(error.message); } finally { button.disabled = false; }
});
setupPasswordToggles(); loadInitialNote();
