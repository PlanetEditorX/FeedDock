const form = document.getElementById('passwordForm');
const errorBox = document.getElementById('authError');

function showError(message) {
  errorBox.textContent = message;
  errorBox.classList.remove('hidden');
}

form.addEventListener('submit', async (event) => {
  event.preventDefault();
  errorBox.classList.add('hidden');
  const values = Object.fromEntries(new FormData(form).entries());
  if (values.new_password !== values.confirm_password) {
    showError('两次输入的新密码不一致');
    return;
  }
  const button = form.querySelector('button');
  button.disabled = true;
  try {
    const response = await fetch('/api/auth/change-password', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        current_password: values.current_password,
        new_password: values.new_password,
      }),
    });
    const data = await response.json().catch(() => ({}));
    if (response.status === 401) {
      window.location.replace('/login');
      return;
    }
    if (!response.ok) throw new Error(data.detail || `HTTP ${response.status}`);
    window.location.replace('/');
  } catch (error) {
    showError(error.message);
  } finally {
    button.disabled = false;
  }
});
