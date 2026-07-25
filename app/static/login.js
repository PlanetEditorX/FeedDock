const form = document.getElementById('loginForm');
const errorBox = document.getElementById('authError');

function showError(message) {
  errorBox.textContent = message;
  errorBox.classList.remove('hidden');
}

form.addEventListener('submit', async (event) => {
  event.preventDefault();
  errorBox.classList.add('hidden');
  const button = form.querySelector('button');
  button.disabled = true;
  try {
    const payload = Object.fromEntries(new FormData(form).entries());
    const response = await fetch('/api/auth/login', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    });
    const data = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(data.detail || `HTTP ${response.status}`);
    window.location.replace(data.must_change_password ? '/change-password' : '/');
  } catch (error) {
    showError(error.message);
  } finally {
    button.disabled = false;
  }
});
