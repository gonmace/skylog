(() => {
  // Si ya hay token válido, ir directo al dashboard
  if (localStorage.getItem('access')) {
    window.location.href = '/dashboard/';
    return;
  }

  const btn = document.getElementById('btn-login');
  const statusBox = document.getElementById('login-status');
  const statusText = document.getElementById('status-text');
  const errorBox = document.getElementById('login-error');
  const errorText = document.getElementById('error-text');

  let pollInterval = null;
  let pollAttempts = 0;
  const MAX_ATTEMPTS = 60; // 3 min a 3s c/u
  let popup = null;

  function showStatus(msg) {
    statusBox.classList.remove('hidden');
    statusText.textContent = msg;
    errorBox.classList.add('hidden');
  }

  function showError(msg) {
    errorBox.classList.remove('hidden');
    errorText.textContent = msg;
    statusBox.classList.add('hidden');
    btn.disabled = false;
    btn.textContent = 'Reintentar';
    if (pollInterval) clearInterval(pollInterval);
    if (popup && !popup.closed) popup.close();
  }

  function getCsrfToken() {
    const match = document.cookie.match(/csrftoken=([^;]+)/);
    return match ? match[1] : '';
  }

  async function startLogin() {
    btn.disabled = true;
    showStatus('Conectando con Nextcloud...');

    // Abrir el popup AHORA, en el contexto síncrono del click, para que no sea bloqueado
    const w = 520, h = 640;
    const left = Math.round(window.screenX + (window.outerWidth - w) / 2);
    const top = Math.round(window.screenY + (window.outerHeight - h) / 2);
    popup = window.open(
      'about:blank',
      'nextcloud_login',
      `width=${w},height=${h},left=${left},top=${top},toolbar=no,menubar=no,scrollbars=yes`,
    );

    let data;
    try {
      const resp = await fetch('/api/auth/nextcloud/start/', {
        method: 'POST',
        headers: { 'X-CSRFToken': getCsrfToken(), 'Content-Type': 'application/json' },
      });
      data = await resp.json();
      if (!resp.ok) throw new Error(data.error || 'Error desconocido');
    } catch (e) {
      if (popup && !popup.closed) popup.close();
      showError(`No se pudo iniciar sesión: ${e.message}`);
      return;
    }

    sessionStorage.setItem('nc_poll_token', data.poll_token);
    sessionStorage.setItem('nc_poll_endpoint', data.poll_endpoint);

    if (!popup || popup.closed) {
      // El usuario cerró el popup antes de que llegara la URL — fallback a misma pestaña
      sessionStorage.setItem('nc_redirect_back', '1');
      window.location.href = data.login_url;
      return;
    }

    // Redirigir el popup ya abierto a la URL de Nextcloud
    popup.location.href = data.login_url;

    showStatus('Completa el inicio de sesión en la ventana emergente...');
    pollAttempts = 0;
    pollInterval = setInterval(doPoll, 3000);
  }

  async function doPoll() {
    pollAttempts++;
    if (pollAttempts > MAX_ATTEMPTS) {
      showError('Tiempo de espera agotado. Vuelve a intentarlo.');
      return;
    }

    const poll_token = sessionStorage.getItem('nc_poll_token');
    const poll_endpoint = sessionStorage.getItem('nc_poll_endpoint');
    if (!poll_token || !poll_endpoint) {
      showError('Sesión de autenticación perdida. Vuelve a intentarlo.');
      return;
    }

    let data;
    try {
      const resp = await fetch('/api/auth/nextcloud/poll/', {
        method: 'POST',
        headers: { 'X-CSRFToken': getCsrfToken(), 'Content-Type': 'application/json' },
        body: JSON.stringify({ poll_token, poll_endpoint }),
      });
      data = await resp.json();

      if (resp.status === 202) return; // pendiente

      if (!resp.ok) {
        showError(data.error || 'Error al verificar autorización.');
        return;
      }
    } catch (e) {
      return; // error de red — reintentar
    }

    // Éxito
    clearInterval(pollInterval);
    sessionStorage.removeItem('nc_poll_token');
    sessionStorage.removeItem('nc_poll_endpoint');
    if (popup && !popup.closed) popup.close();
    localStorage.setItem('access', data.access);
    localStorage.setItem('refresh', data.refresh);
    showStatus('¡Autenticado! Redirigiendo...');
    window.location.href = '/dashboard/';
  }

  // Fallback: volviendo de redirección en misma pestaña
  if (sessionStorage.getItem('nc_poll_token') && sessionStorage.getItem('nc_redirect_back')) {
    sessionStorage.removeItem('nc_redirect_back');
    btn.disabled = true;
    showStatus('Verificando autorización...');
    pollAttempts = 0;
    pollInterval = setInterval(doPoll, 3000);
  }

  btn.addEventListener('click', startLogin);
})();
