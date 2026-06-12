(() => {
  // Chrome bloquea peticiones a 127.0.0.1 desde iframes cross-origin (Private Network Access policy)
  const isEmbedded = window.self !== window.top;

  function getToken(name) {
    // Cookie primero (persiste en iframe cross-origin); localStorage como fallback
    const match = document.cookie.match(new RegExp('(?:^|; )' + name + '=([^;]*)'));
    if (match) return match[1];
    return localStorage.getItem(name);
  }

  function setToken(name, value, maxAge) {
    const secure = location.protocol === 'https:' ? '; Secure' : '';
    document.cookie = `${name}=${value}; path=/; SameSite=None; max-age=${maxAge}${secure}`;
    localStorage.setItem(name, value);
  }

  function clearTokens() {
    const secure = location.protocol === 'https:' ? '; Secure' : '';
    document.cookie = `access=; path=/; SameSite=None; max-age=0${secure}`;
    document.cookie = `refresh=; path=/; SameSite=None; max-age=0${secure}`;
    localStorage.removeItem('access');
    localStorage.removeItem('refresh');
    localStorage.removeItem('pin_unlocked_at');
  }

  function authHeaders() {
    return {
      'Authorization': `Bearer ${getToken('access')}`,
      'Content-Type': 'application/json',
    };
  }

  function getCsrfToken() {
    const match = document.cookie.match(/csrftoken=([^;]+)/);
    return match ? match[1] : '';
  }

  // Refrescar el access token proactivamente cada 90 min para que la sesión no caduque nunca
  setInterval(async () => { await refreshAccessToken(); }, 90 * 60 * 1000);

  async function refreshAccessToken() {
    const refresh = getToken('refresh');
    if (!refresh) return false;
    try {
      const r = await fetch('/api/auth/token/refresh/', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ refresh }),
      });
      if (r.ok) {
        const data = await r.json();
        setToken('access', data.access, 7200);
        if (data.refresh) setToken('refresh', data.refresh, 604800);
        return true;
      }
    } catch {}
    return false;
  }

  function logout() {
    clearTokens();
    window.location.href = '/login/';
  }

  async function init() {
    if (!getToken('access')) {
      try {
        const r = await fetch('/api/auth/claim-token/');
        if (r.ok) {
          const t = await r.json();
          if (t.access) { setToken('access', t.access, 7200); if (t.refresh) setToken('refresh', t.refresh, 604800); }
        }
      } catch {}
    }
    if (!getToken('access')) { window.location.href = '/login/'; return; }
    try {
      let resp = await fetch('/api/auth/me/', { headers: authHeaders() });
      if (resp.status === 401) {
        const refreshed = await refreshAccessToken();
        if (!refreshed) { logout(); return; }
        resp = await fetch('/api/auth/me/', { headers: authHeaders() });
        if (resp.status === 401) { logout(); return; }
      }
      const profile = await resp.json();
      if (profile.is_executive) {
        window.location.href = '/dashboard/executive/';
      } else {
        window.location.href = '/dashboard/employee/';
      }
    } catch (e) {}
  }

  init();
})();
