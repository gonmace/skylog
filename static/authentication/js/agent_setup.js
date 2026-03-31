(() => {
  const params = new URLSearchParams(window.location.search);
  const deviceToken = params.get('device');

  const stepLogin = document.getElementById('step-login');
  const stepWaiting = document.getElementById('step-waiting');
  const stepSuccess = document.getElementById('step-success');
  const stepError = document.getElementById('step-error');
  const statusText = document.getElementById('status-text');
  const errorText = document.getElementById('error-text');
  const btnLogin = document.getElementById('btn-login');
  const btnRetry = document.getElementById('btn-retry');

  if (!deviceToken) {
    showError('No se encontró el device token. Abre esta página desde el agente.');
    return;
  }

  let pollInterval = null;
  let pollAttempts = 0;
  const MAX_ATTEMPTS = 60;

  function showError(msg) {
    stepLogin.classList.add('hidden');
    stepWaiting.classList.add('hidden');
    stepSuccess.classList.add('hidden');
    stepError.classList.remove('hidden');
    errorText.textContent = msg;
    if (pollInterval) clearInterval(pollInterval);
  }

  function getCsrfToken() {
    const match = document.cookie.match(/csrftoken=([^;]+)/);
    return match ? match[1] : '';
  }

  async function startLogin() {
    btnLogin.disabled = true;

    let data;
    try {
      const resp = await fetch('/api/auth/nextcloud/start/', {
        method: 'POST',
        headers: { 'X-CSRFToken': getCsrfToken(), 'Content-Type': 'application/json' },
      });
      data = await resp.json();
      if (!resp.ok) throw new Error(data.error || 'Error desconocido');
    } catch (e) {
      showError(`No se pudo conectar con Nextcloud: ${e.message}`);
      return;
    }

    sessionStorage.setItem('agent_poll_token', data.poll_token);
    sessionStorage.setItem('agent_poll_endpoint', data.poll_endpoint);
    sessionStorage.setItem('agent_device_token', deviceToken);

    // Abrir Nextcloud en ventana nueva — esta página se queda abierta haciendo polling
    window.open(data.login_url, '_blank', 'width=900,height=650,noopener');

    stepLogin.classList.add('hidden');
    stepWaiting.classList.remove('hidden');
    statusText.textContent = 'Autoriza el acceso en la ventana de Nextcloud...';

    pollAttempts = 0;
    pollInterval = setInterval(doPoll, 3000);
  }

  async function doPoll() {
    pollAttempts++;
    if (pollAttempts > MAX_ATTEMPTS) {
      showError('Tiempo de espera agotado. Vuelve a intentarlo.');
      return;
    }

    const poll_token = sessionStorage.getItem('agent_poll_token');
    const poll_endpoint = sessionStorage.getItem('agent_poll_endpoint');
    const device_token = sessionStorage.getItem('agent_device_token');

    let pollData = null;
    try {
      const resp = await fetch('/api/agent/nextcloud/poll/', {
        method: 'POST',
        headers: { 'X-CSRFToken': getCsrfToken(), 'Content-Type': 'application/json' },
        body: JSON.stringify({ poll_token, poll_endpoint, device_token }),
      });
      pollData = await resp.json();

      if (resp.status === 202) return; // pending

      if (!resp.ok) {
        showError(pollData.error || 'Error al verificar autorización.');
        return;
      }
    } catch (e) {
      return; // retry next cycle
    }

    // Éxito
    clearInterval(pollInterval);
    sessionStorage.removeItem('agent_poll_token');
    sessionStorage.removeItem('agent_poll_endpoint');
    sessionStorage.removeItem('agent_redirect_back');
    sessionStorage.removeItem('agent_device_token');

    stepWaiting.classList.add('hidden');
    stepSuccess.classList.remove('hidden');

    // Redirigir al home tras 5 segundos
    let secs = 5;
    const countdown = document.getElementById('redirect-countdown');
    const timer = setInterval(() => {
      secs--;
      countdown.textContent = secs;
      if (secs <= 0) {
        clearInterval(timer);
        window.location.href = '/';
      }
    }, 1000);
  }

  // Reanudar polling si la página se recargó con tokens activos (ej: F5)
  if (
    sessionStorage.getItem('agent_poll_token') &&
    sessionStorage.getItem('agent_device_token') === deviceToken
  ) {
    stepLogin.classList.add('hidden');
    stepWaiting.classList.remove('hidden');
    statusText.textContent = 'Autoriza el acceso en la ventana de Nextcloud...';
    pollAttempts = 0;
    pollInterval = setInterval(doPoll, 3000);
  }

  btnLogin.addEventListener('click', startLogin);
  btnRetry.addEventListener('click', () => {
    stepError.classList.add('hidden');
    stepLogin.classList.remove('hidden');
    btnLogin.disabled = false;
  });
})();
