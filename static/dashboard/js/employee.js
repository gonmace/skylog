(() => {
  // Chrome bloquea peticiones a 127.0.0.1 desde iframes cross-origin (Private Network Access policy)
  const isEmbedded = window.self !== window.top;
  const viewAsId   = new URLSearchParams(window.location.search).get('view_as');

  function avatarColorIdx(name) {
    let h = 0;
    for (let i = 0; i < name.length; i++) h = (h * 31 + name.charCodeAt(i)) & 0xffff;
    return h % 10;
  }
  function setAvatar(el, name) {
    if (!el) return;
    const parts = (name || '?').trim().split(/\s+/);
    el.textContent = (parts[0][0] + (parts[1]?.[0] || '')).toUpperCase();
    for (let i = 0; i < 10; i++) el.classList.remove(`avatar-c-${i}`);
    el.classList.add(`avatar-c-${avatarColorIdx(name || '?')}`);
  }

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

  const ALL_VIEWS = ['view-loading', 'view-noaccess', 'view-employee'];

  function showView(id) {
    ALL_VIEWS.forEach(v => {
      document.getElementById(v).classList.toggle('hidden', v !== id);
    });
  }

  async function init() {
    if (!getToken('access')) {
      try {
        const r = await fetch('/api/auth/claim-token/');
        if (r.ok) { const t = await r.json(); if (t.access) { setToken('access', t.access, 7200); if (t.refresh) setToken('refresh', t.refresh, 604800); } }
      } catch {}
    }
    if (!getToken('access')) { window.location.href = '/login/'; return; }
    try {
      let resp = await fetch('/api/auth/me/', { headers: authHeaders() });
      if (resp.status === 401) { const refreshed = await refreshAccessToken(); if (!refreshed) { logout(); return; } resp = await fetch('/api/auth/me/', { headers: authHeaders() }); if (resp.status === 401) { logout(); return; } }
      const profile = await resp.json();
      if (viewAsId) {
        if (!profile.is_executive) {
          document.body.innerHTML = '<div style="padding:40px;color:#ff6b6b;font-family:sans-serif">Acceso no autorizado</div>';
          return;
        }
        showView('view-employee');
        await initViewAs(parseInt(viewAsId));
        return;
      }
      if (profile.is_executive) { window.location.href = '/dashboard/executive/'; return; }
      if (profile.skylog_access === false) { showView('view-noaccess'); initNoAccess(); return; }
      showView('view-employee');
      initEmployee(profile);
    } catch (e) {
      if (viewAsId) {
        document.body.innerHTML = `<div style="padding:40px;color:#ff6b6b;font-family:sans-serif;background:#1a1a2e;min-height:100vh">Error al cargar: ${e.message}</div>`;
      }
    }
  }

  // ─────────────────────────────────────────────────────────────
  //  No Access
  // ─────────────────────────────────────────────────────────────
  function initNoAccess() {
    document.getElementById('noaccess-btn-logout').addEventListener('click', logout);
  }

  // ─────────────────────────────────────────────────────────────
  //  Employee
  // ─────────────────────────────────────────────────────────────
  // Toast efímero (elemento creado por JS, auto-removido a los ~3s).
  function showToast(msg, kind) {
    const accent = kind === 'error' ? 'var(--color-error)' : 'var(--color-success)';
    const t = document.createElement('div');
    t.textContent = msg;
    t.style.cssText = 'position:fixed;left:50%;bottom:28px;transform:translateX(-50%) translateY(10px);'
      + 'background:var(--color-base-100);color:var(--color-base-content);'
      + 'border:1px solid color-mix(in srgb, var(--color-base-content) 12%, transparent);'
      + 'border-left:4px solid ' + accent + ';padding:12px 18px;border-radius:12px;font-size:0.875rem;'
      + 'box-shadow:0 8px 30px rgba(0,0,0,.25);z-index:9999;opacity:0;transition:opacity .25s,transform .25s;max-width:90vw;';
    document.body.appendChild(t);
    requestAnimationFrame(() => { t.style.opacity = '1'; t.style.transform = 'translateX(-50%) translateY(0)'; });
    setTimeout(() => {
      t.style.opacity = '0'; t.style.transform = 'translateX(-50%) translateY(10px)';
      setTimeout(() => t.remove(), 300);
    }, 3000);
  }

  function initLeadsModal() {
    const openBtn  = document.getElementById('emp-btn-leads');
    const modal    = document.getElementById('modal-leads');
    if (!openBtn || !modal) return;
    buildLeadsModal(openBtn, modal);
  }

  // Lógica común del modal "Mensaje a Sup/PM" (modos: por grupo / personas).
  function buildLeadsModal(openBtn, modal) {
    const body      = document.getElementById('leads-body');
    const cbSup     = document.getElementById('leads-target-sup');
    const cbPm      = document.getElementById('leads-target-pm');
    const tabGroup  = document.getElementById('leads-tab-group');
    const tabPeople = document.getElementById('leads-tab-people');
    const modeGroup = document.getElementById('leads-mode-group');
    const modePeople= document.getElementById('leads-mode-people');
    const peopleList= document.getElementById('leads-people-list');
    const peopleSearch = document.getElementById('leads-people-search');
    const errEl     = document.getElementById('leads-error');
    const okEl      = document.getElementById('leads-ok');
    const btnSend   = document.getElementById('leads-send');
    const btnCancel = document.getElementById('leads-cancel');
    let mode = 'group';
    let peopleLoaded = false;
    let people = [];

    function esc(s) {
      return String(s == null ? '' : s).replace(/[&<>"']/g, c =>
        ({ '&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;' }[c]));
    }

    function setMode(m) {
      mode = m;
      modeGroup.style.display  = (m === 'group')  ? '' : 'none';
      modePeople.style.display = (m === 'people') ? '' : 'none';
      tabGroup.classList.toggle('text-info', m === 'group');
      tabGroup.classList.toggle('text-base-content/40', m !== 'group');
      tabPeople.classList.toggle('text-info', m === 'people');
      tabPeople.classList.toggle('text-base-content/40', m !== 'people');
      if (m === 'people' && !peopleLoaded) loadPeople();
    }

    function renderPeople() {
      const q = (peopleSearch.value || '').trim().toLowerCase();
      const list = people.filter(p => !q
        || p.name.toLowerCase().indexOf(q) >= 0
        || (p.role_label || '').toLowerCase().indexOf(q) >= 0);
      if (!list.length) {
        peopleList.innerHTML = '<p class="text-xs text-base-content/40 py-2 text-center">Sin resultados</p>';
        return;
      }
      peopleList.innerHTML = list.map(p => `
        <label class="flex items-center gap-2 cursor-pointer text-sm py-0.5">
          <input type="checkbox" class="checkbox checkbox-sm checkbox-info leads-person" value="${p.id}">
          <span class="flex-1 truncate">${esc(p.name)}</span>
          <span class="text-xs text-base-content/40 shrink-0">${esc(p.role_label)}</span>
        </label>`).join('');
    }

    function loadPeople() {
      peopleList.innerHTML = '<p class="text-xs text-base-content/40 py-2 text-center">Cargando…</p>';
      fetch('/api/messages/leads/', { headers: authHeaders() })
        .then(r => r.ok ? r.json() : Promise.reject())
        .then(data => { people = data || []; peopleLoaded = true; renderPeople(); })
        .catch(() => { peopleList.innerHTML = '<p class="text-xs text-error py-2 text-center">Error al cargar</p>'; });
    }

    tabGroup.addEventListener('click', () => setMode('group'));
    tabPeople.addEventListener('click', () => setMode('people'));
    peopleSearch.addEventListener('input', renderPeople);

    openBtn.addEventListener('click', () => {
      body.value = '';
      cbSup.checked = true; cbPm.checked = true;
      peopleList.querySelectorAll('.leads-person:checked').forEach(c => { c.checked = false; });
      peopleSearch.value = '';
      if (peopleLoaded) renderPeople();
      errEl.classList.add('hidden'); okEl.classList.add('hidden');
      btnSend.disabled = false; btnSend.textContent = 'Enviar';
      setMode('group');
      modal.showModal();
    });
    btnCancel.addEventListener('click', () => modal.close());

    btnSend.addEventListener('click', async () => {
      const text = body.value.trim();
      errEl.classList.add('hidden'); okEl.classList.add('hidden');
      if (!text) { errEl.textContent = 'El mensaje no puede estar vacío.'; errEl.classList.remove('hidden'); return; }
      const payload = { body: text };
      if (mode === 'people') {
        const ids = Array.from(peopleList.querySelectorAll('.leads-person:checked')).map(c => parseInt(c.value, 10));
        if (!ids.length) { errEl.textContent = 'Selecciona al menos una persona.'; errEl.classList.remove('hidden'); return; }
        payload.recipient_ids = ids;
      } else {
        const targets = [];
        if (cbSup.checked) targets.push('supervisor');
        if (cbPm.checked)  targets.push('project_manager');
        if (!targets.length) { errEl.textContent = 'Selecciona al menos un destino.'; errEl.classList.remove('hidden'); return; }
        payload.targets = targets;
      }
      btnSend.disabled = true; btnSend.textContent = 'Enviando...';
      try {
        const resp = await fetch('/api/messages/leads/', {
          method: 'POST',
          headers: { ...authHeaders(), 'Content-Type': 'application/json', 'X-CSRFToken': getCsrfToken() },
          body: JSON.stringify(payload),
        });
        const d = await resp.json().catch(() => ({}));
        if (resp.ok) {
          modal.close();
          showToast(`Mensaje enviado a ${d.sent} destinatario(s).`);
          body.value = '';
          btnSend.textContent = 'Enviar'; btnSend.disabled = false;
        } else {
          errEl.textContent = d.error || 'Error al enviar.';
          errEl.classList.remove('hidden');
          btnSend.textContent = 'Enviar'; btnSend.disabled = false;
        }
      } catch (e) {
        errEl.textContent = 'Error de conexión.'; errEl.classList.remove('hidden');
        btnSend.textContent = 'Enviar'; btnSend.disabled = false;
      }
    });
  }

  function initEmployee(initialProfileData) {
    let profileData = initialProfileData;
    // Populate profile card
    const profileFullname = document.getElementById('profile-fullname');
    const profileEmail    = document.getElementById('profile-email');
    if (profileFullname) profileFullname.textContent = profileData.full_name || profileData.nextcloud_username;
    if (profileEmail)    profileEmail.textContent    = profileData.email || '';

    setAvatar(document.getElementById('profile-avatar'), profileData.full_name || profileData.nextcloud_username);

    // Botones superiores habilitados por permisos granulares.
    const _showIf = (id, cond) => { const el = document.getElementById(id); if (el && cond) el.style.display = ''; };
    _showIf('emp-link-report',   profileData.is_superuser || profileData.can_view_report);
    _showIf('emp-link-stats',    profileData.is_superuser || profileData.can_view_stats);
    _showIf('emp-link-tags',     profileData.is_superuser || profileData.can_edit_tags);
    _showIf('emp-btn-leads',     profileData.can_message_leads);
    _showIf('emp-link-permisos', profileData.is_superuser);
    if (profileData.can_message_leads) initLeadsModal();

    // DOM refs
    const statusLoading   = document.getElementById('status-loading');
    const statusInactive  = document.getElementById('status-inactive');
    const statusActive    = document.getElementById('status-active');
    const activeSince     = document.getElementById('active-since');
    const btnStart        = document.getElementById('btn-start');
    const btnEnd          = document.getElementById('btn-end');
    const modal           = document.getElementById('modal-end-workday');
    const setupRequired   = document.getElementById('setup-required');
    const statusCard      = document.getElementById('status-card');
    const btnSetupDownload = document.getElementById('btn-setup-download');
    const btnSetupRetry   = document.getElementById('btn-setup-retry');
    const btnModalCancel  = document.getElementById('btn-modal-cancel');
    const btnModalSubmit  = document.getElementById('btn-modal-submit');
    const modalError      = document.getElementById('modal-error');
    const modalErrorText  = document.getElementById('modal-error-text');
    const activitiesDone    = document.getElementById('activities-done');
    const activitiesPlanned = document.getElementById('activities-planned');

    let activeWorkdayId = null;

    function formatTime(isoString) {
      return new Date(isoString).toLocaleTimeString('es-BO', { hour: '2-digit', minute: '2-digit', hour12: false });
    }

    function showActive(workdayId, startTime) {
      activeWorkdayId = workdayId;
      statusLoading.classList.add('hidden');
      statusInactive.classList.add('hidden');
      statusActive.classList.remove('hidden');
      activeSince.textContent = `desde las ${formatTime(startTime)}`;
      btnStart.classList.add('hidden');
      btnEnd.classList.remove('hidden');
    }

    function showInactive() {
      activeWorkdayId = null;
      statusLoading.classList.add('hidden');
      statusActive.classList.add('hidden');
      statusInactive.classList.remove('hidden');
      btnEnd.classList.add('hidden');
      btnStart.classList.remove('hidden');
    }

    async function checkAgentAlive() {
      try {
        const resp = await fetch('/api/auth/me/', { headers: authHeaders() });
        if (resp.status === 401) { logout(); return false; }
        if (resp.ok) {
          const data = await resp.json();
          profileData = { ...profileData, ...data };
          if (data.agent_is_active) return true;
        }
      } catch { /* ignorar */ }
      if (!isEmbedded) try {
        const resp = await fetch('http://127.0.0.1:7337/ping', { signal: AbortSignal.timeout(2000) });
        return resp.ok;
      } catch { return false; }
      return false;
    }

    let setupPollInterval = null;

    function startSetupPolling() {
      if (setupPollInterval) return;
      setupPollInterval = setInterval(async () => {
        const alive = await checkAgentAlive();
        if (alive) {
          clearInterval(setupPollInterval);
          setupPollInterval = null;
          updateAgentStatus(true);
        }
      }, 5000);
    }

    function stopSetupPolling() {
      if (setupPollInterval) { clearInterval(setupPollInterval); setupPollInterval = null; }
    }

    function updateAgentStatus(agentIsActive) {
      // Empleados solo_movil: no necesitan agente, todo habilitado siempre
      if (profileData?.solo_movil) {
        stopSetupPolling();
        setupRequired.classList.add('hidden');
        statusCard.classList.remove('hidden');
        document.getElementById('agent-version-card')?.classList.add('hidden');
        btnStart.disabled = false;
        btnStart.title    = '';
        btnEnd.disabled   = false;
        btnEnd.title      = '';
        return;
      }

      const neverInstalled = !profileData?.agent_version && !profileData?.agent_last_seen;
      const installed  = profileData?.agent_version || '';
      const latest     = profileData?.agent_latest_version || '';
      const outdated   = installed && latest && installed !== latest;

      if (neverInstalled && !agentIsActive) {
        setupRequired.classList.remove('hidden');
        statusCard.classList.add('hidden');
        btnStart.classList.add('hidden');
        btnEnd.classList.add('hidden');
        document.getElementById('agent-version-card')?.classList.add('hidden');
        startSetupPolling();
        return;
      }

      stopSetupPolling();
      setupRequired.classList.add('hidden');
      statusCard.classList.remove('hidden');

      // Deshabilitar botones si offline O si versión desactualizada
      const msgOffline  = 'El agente no está activo. Asegúrate de que redline_agent.exe esté corriendo.';
      const msgOutdated = `Actualiza el agente a v${latest} para poder registrar jornadas.`;
      const blocked     = !agentIsActive || outdated;
      const blockMsg    = !agentIsActive ? msgOffline : msgOutdated;
      btnStart.disabled = blocked;
      btnStart.title    = blocked ? blockMsg : '';
      btnEnd.disabled   = blocked;
      btnEnd.title      = blocked ? blockMsg : '';

      const card         = document.getElementById('agent-version-card');
      const btnDl        = document.getElementById('btn-download-agent');
      const offlineBadge = document.getElementById('agent-offline-badge');
      const versionText  = document.getElementById('agent-version-text');
      const btnUpdate    = document.getElementById('btn-update-agent');
      if (!card) return;

      // Ocultar tarjeta solo si online y versión al día
      if (agentIsActive && !outdated) {
        card.classList.add('hidden');
        if (btnDl) btnDl.classList.add('hidden');
        if (offlineBadge) offlineBadge.classList.add('hidden');
        return;
      }

      card.classList.remove('hidden');

      // Mostrar badge offline solo si está offline
      if (btnDl) btnDl.classList.toggle('hidden', agentIsActive);
      if (offlineBadge) offlineBadge.classList.toggle('hidden', agentIsActive);

      if (!installed) {
        versionText.textContent = 'No instalado';
        if (btnUpdate) btnUpdate.classList.add('hidden');
      } else if (outdated) {
        versionText.textContent = `v${installed} → v${latest} disponible`;
        if (btnUpdate) btnUpdate.classList.remove('hidden');
      } else {
        versionText.textContent = `v${installed}`;
        if (btnUpdate) btnUpdate.classList.add('hidden');
      }
    }

    async function loadWorkdayStatus() {
      try {
        const resp = await fetch('/api/workday/active/', { headers: authHeaders() });
        if (resp.status === 401) { logout(); return; }
        const data = await resp.json();
        if (data.active) { showActive(data.workday_id, data.start_time); }
        else             { showInactive(); }
      } catch (e) {
        statusLoading.classList.add('hidden');
        statusInactive.classList.remove('hidden');
      }
    }

    async function startWorkday() {
      btnStart.disabled = true;
      try {
        const resp = await fetch('/api/workday/start/', {
          method: 'POST',
          headers: { ...authHeaders(), 'X-CSRFToken': getCsrfToken() },
        });
        const data = await resp.json();
        if (!resp.ok) { alert(data.error || 'Error al iniciar jornada'); btnStart.disabled = false; return; }
        showActive(data.workday_id, data.start_time);
        if (!isEmbedded) fetch('http://127.0.0.1:7337/trigger', { method: 'POST' }).catch(() => {});
      } catch (e) { alert('Error de conexión'); btnStart.disabled = false; }
    }

    async function getLocation() {
      return new Promise((resolve) => {
        if (!navigator.geolocation) { resolve(null); return; }
        navigator.geolocation.getCurrentPosition(
          p => resolve({ latitude: p.coords.latitude, longitude: p.coords.longitude }),
          () => resolve(null),
          { timeout: 8000, maximumAge: 60000 }
        );
      });
    }

    function wordCount(text) {
      return text.trim().split(/\s+/).filter(w => w.length > 0).length;
    }

    async function endWorkday() {
      const done    = activitiesDone.value.trim();
      const planned = activitiesPlanned.value.trim();
      if (!done || !planned) {
        modalError.classList.remove('hidden');
        modalErrorText.textContent = 'Completa ambos campos antes de finalizar.';
        return;
      }
      if (wordCount(done) < 10) {
        modalError.classList.remove('hidden');
        modalErrorText.textContent = `"¿Qué hiciste hoy?" requiere al menos 10 palabras (llevas ${wordCount(done)}).`;
        activitiesDone.focus();
        return;
      }
      if (wordCount(planned) < 10) {
        modalError.classList.remove('hidden');
        modalErrorText.textContent = `"¿Qué planeas mañana?" requiere al menos 10 palabras (llevas ${wordCount(planned)}).`;
        activitiesPlanned.focus();
        return;
      }
      modalError.classList.add('hidden');
      btnModalSubmit.disabled = true;
      btnModalSubmit.textContent = 'Finalizando...';

      // Geolocalización (requerida para usuarios móviles)
      let location = null;
      if (profileData.solo_movil) {
        btnModalSubmit.textContent = 'Obteniendo ubicación...';
        location = await getLocation();
        if (!location) {
          modalError.classList.remove('hidden');
          modalErrorText.textContent = 'No se pudo obtener la ubicación. Activa el GPS e intenta de nuevo.';
          btnModalSubmit.disabled = false;
          btnModalSubmit.textContent = 'Finalizar jornada';
          return;
        }
      }

      try {
        const resp = await fetch('/api/workday/end/', {
          method: 'POST',
          headers: { ...authHeaders(), 'X-CSRFToken': getCsrfToken() },
          body: JSON.stringify({
            workday_id: activeWorkdayId,
            activities_done: done,
            activities_planned: planned,
            ...(location || {}),
          }),
        });
        const data = await resp.json();
        if (!resp.ok) {
          modalError.classList.remove('hidden');
          modalErrorText.textContent = data.error || 'Error al finalizar jornada';
          btnModalSubmit.disabled = false;
          btnModalSubmit.textContent = 'Finalizar jornada';
          return;
        }
        modal.close();
        activitiesDone.value = '';
        activitiesPlanned.value = '';
        showInactive();
      } catch (e) {
        modalError.classList.remove('hidden');
        modalErrorText.textContent = 'Error de conexión';
        btnModalSubmit.disabled = false;
        btnModalSubmit.textContent = 'Finalizar jornada';
      }
    }

    async function downloadAgent(btn, originalHTML) {
      // Abrir modal inmediatamente
      const dlModal   = document.getElementById('modal-download-agent');
      const step1Icon = document.getElementById('dl-step-1-icon');
      const step1Sub  = document.getElementById('dl-step-1-sub');
      const stepsRest = document.getElementById('dl-steps-rest');
      const dlError   = document.getElementById('dl-error');
      const dlErrTxt  = document.getElementById('dl-error-text');
      const btnClose  = document.getElementById('btn-dl-close');

      // Resetear estado del modal
      step1Icon.innerHTML = '<span class="loading loading-spinner loading-xs" style="color:var(--cp-blue)"></span>';
      step1Sub.textContent = 'Puede tardar unos segundos';
      stepsRest.classList.add('hidden');
      dlError.classList.add('hidden');
      btnClose.disabled = true;
      dlModal.showModal();

      btn.disabled = true;

      try {
        const resp = await fetch('/api/agent/download/', { headers: authHeaders() });
        if (!resp.ok) {
          const d = await resp.json().catch(() => ({}));
          dlErrTxt.textContent = d.error || 'Error al descargar el agente';
          dlError.classList.remove('hidden');
          step1Icon.innerHTML = '<svg xmlns="http://www.w3.org/2000/svg" width="20" height="20" fill="none" viewBox="0 0 24 24" stroke="var(--cp-red)" stroke-width="2"><path stroke-linecap="round" stroke-linejoin="round" d="M10 14l2-2m0 0l2-2m-2 2l-2-2m2 2l2 2m7-2a9 9 0 11-18 0 9 9 0 0118 0z"/></svg>';
          step1Sub.textContent = 'No se pudo descargar';
          return;
        }
        const blob = await resp.blob();
        const url  = URL.createObjectURL(blob);
        const a    = document.createElement('a');
        a.href = url; a.download = 'RedLineGS.zip'; a.click();
        URL.revokeObjectURL(url);

        // Marcar paso 1 como completado y mostrar pasos siguientes
        step1Icon.innerHTML = '<svg xmlns="http://www.w3.org/2000/svg" width="20" height="20" fill="none" viewBox="0 0 24 24" stroke="var(--cp-green)" stroke-width="2"><path stroke-linecap="round" stroke-linejoin="round" d="M9 12l2 2 4-4m6 2a9 9 0 11-18 0 9 9 0 0118 0z"/></svg>';
        step1Sub.textContent = 'Descarga iniciada — extrae el ZIP en una carpeta fija';
        stepsRest.classList.remove('hidden');
      } catch (e) {
        dlErrTxt.textContent = 'Error de conexión al descargar';
        dlError.classList.remove('hidden');
        step1Icon.innerHTML = '<svg xmlns="http://www.w3.org/2000/svg" width="20" height="20" fill="none" viewBox="0 0 24 24" stroke="var(--cp-red)" stroke-width="2"><path stroke-linecap="round" stroke-linejoin="round" d="M10 14l2-2m0 0l2-2m-2 2l-2-2m2 2l2 2m7-2a9 9 0 11-18 0 9 9 0 0118 0z"/></svg>';
        step1Sub.textContent = 'No se pudo descargar';
      } finally {
        btn.disabled = false;
        btn.innerHTML = originalHTML;
        btnClose.disabled = false;
      }
    }

    async function loadLastReport() {
      try {
        const resp = await fetch('/api/workday/last-report/', { headers: authHeaders() });
        if (!resp.ok) return;
        const data = await resp.json();
        if (!data.has_report) return;
        const col     = document.getElementById('last-report-col');
        const planned = document.getElementById('report-planned');
        const done    = document.getElementById('report-done');
        const dateEl  = document.getElementById('report-date');
        if (planned) planned.textContent = data.activities_planned;
        if (done)    done.textContent    = data.activities_done;
        if (dateEl) {
          const d = new Date(data.date);
          dateEl.textContent = d.toLocaleDateString('es-BO', { weekday: 'long', day: 'numeric', month: 'long' });
        }
        if (col) col.classList.remove('hidden');
      } catch (e) {}
    }

    // Event listeners
    btnStart.addEventListener('click', startWorkday);
    btnEnd.addEventListener('click', () => {
      modalError.classList.add('hidden');
      btnModalSubmit.disabled = false;
      btnModalSubmit.textContent = 'Finalizar jornada';
      modal.showModal();
    });
    btnModalCancel.addEventListener('click', () => modal.close());
    btnModalSubmit.addEventListener('click', endWorkday);
    document.getElementById('btn-logout').addEventListener('click', logout);

    const btnDlClose = document.getElementById('btn-dl-close');
    if (btnDlClose) {
      btnDlClose.addEventListener('click', () => document.getElementById('modal-download-agent').close());
    }

    const downloadBtn = document.getElementById('btn-download-agent');
    if (downloadBtn) {
      const orig = downloadBtn.innerHTML;
      downloadBtn.addEventListener('click', (e) => { e.preventDefault(); downloadAgent(e.currentTarget, orig); });
    }

    const btnUpdateAgent = document.getElementById('btn-update-agent');
    if (btnUpdateAgent) {
      btnUpdateAgent.addEventListener('click', async () => {
        const icon    = document.getElementById('btn-update-icon');
        const spinner = document.getElementById('btn-update-spinner');
        const label   = document.getElementById('btn-update-label');
        btnUpdateAgent.disabled = true;
        icon.classList.add('hidden');
        spinner.classList.remove('hidden');
        label.textContent = 'Descargando...';
        try {
          const resp = await fetch('/api/agent/installer/', { headers: authHeaders() });
          if (!resp.ok) { alert('Error al descargar el instalador'); return; }
          const blob = await resp.blob();
          const url  = URL.createObjectURL(blob);
          const a    = document.createElement('a');
          a.href = url; a.download = 'RedLineGS_update.zip'; a.click();
          URL.revokeObjectURL(url);
        } catch (e) { alert('Error de conexión'); }
        finally {
          btnUpdateAgent.disabled = false;
          icon.classList.remove('hidden');
          spinner.classList.add('hidden');
          label.textContent = 'Actualizar';
        }
      });
    }

    if (btnSetupDownload) {
      const orig = btnSetupDownload.innerHTML;
      btnSetupDownload.addEventListener('click', (e) => { e.preventDefault(); downloadAgent(e.currentTarget, orig); });
    }

    if (btnSetupRetry) {
      btnSetupRetry.addEventListener('click', async () => {
        btnSetupRetry.disabled = true;
        btnSetupRetry.textContent = 'Verificando...';
        const alive = await checkAgentAlive();
        updateAgentStatus(alive);
        btnSetupRetry.disabled = false;
        btnSetupRetry.textContent = 'Ya lo instalé — verificar conexión';
      });
    }

    async function loadPendingMessages() {
      try {
        const resp = await fetch('/api/messages/pending/', { headers: authHeaders() });
        if (!resp.ok) return;
        const messages = await resp.json();
        const container = document.getElementById('messages-container');
        if (!messages.length) { container.classList.add('hidden'); container.innerHTML = ''; return; }
        container.innerHTML = messages.map(m => {
          const own = m.is_own;
          const nameColor = own ? 'var(--cp-green)' : 'var(--cp-orange)';
          const nameLabel = own ? 'Enviado a Sup/PM' : m.sender_name;
          // Propio: indicador "Enviado" no clickeable (dura todo el día).
          // Recibido sin confirmar: botón "Listo". Recibido confirmado: ✕ para borrar.
          let action;
          if (own) {
            action = `<span class="btn-msg-done" style="border-color:var(--cp-green);color:var(--cp-green);opacity:0.9;cursor:default">Enviado</span>`;
          } else if (m.acknowledged) {
            action = `<button class="btn-msg-done btn-dismiss" data-msg-id="${m.id}" title="Borrar" aria-label="Borrar" style="border-color:var(--cp-text-lo);color:var(--cp-text-lo)">✕</button>`;
          } else {
            action = `<button class="btn-msg-done btn-acknowledge" data-msg-id="${m.id}"${m.day_closed ? ' style="border-color:var(--cp-red,#ff6b6b);color:var(--cp-red,#ff6b6b)"' : ''}>Listo</button>`;
          }
          return `
          <div class="message-banner cupertino-card" id="msg-${m.id}"${own ? ' style="border-left:3px solid var(--cp-green)"' : ''}>
            <div style="flex:1">
              <p class="text-xs font-semibold mb-1" style="color:${nameColor}">${nameLabel}</p>
              <p class="text-sm" style="color:var(--cp-text-hi);white-space:pre-wrap">${m.body}</p>
              <p class="text-xs mt-2 font-medium" style="color:var(--cp-text-mid)">${new Date(m.sent_at).toLocaleString('es-BO')}</p>
            </div>
            ${action}
          </div>`;
        }).join('');
        container.classList.remove('hidden');
      } catch(e) {}
    }

    document.getElementById('messages-container').addEventListener('click', async (e) => {
      const ackBtn = e.target.closest('.btn-acknowledge');
      const delBtn = e.target.closest('.btn-dismiss');

      // Confirmar (Listo): marca leído y re-renderiza para mostrar la ✕ de borrar.
      if (ackBtn) {
        ackBtn.disabled = true;
        try {
          const resp = await fetch(`/api/messages/${ackBtn.dataset.msgId}/acknowledge/`, {
            method: 'POST',
            headers: { ...authHeaders(), 'X-CSRFToken': getCsrfToken() },
          });
          if (resp.ok) await loadPendingMessages();
          else ackBtn.disabled = false;
        } catch(e) { ackBtn.disabled = false; }
        return;
      }

      // Borrar (✕): solo disponible tras confirmar; oculta el mensaje.
      if (delBtn) {
        delBtn.disabled = true;
        try {
          const resp = await fetch(`/api/messages/${delBtn.dataset.msgId}/dismiss/`, {
            method: 'POST',
            headers: { ...authHeaders(), 'X-CSRFToken': getCsrfToken() },
          });
          if (resp.ok) {
            const card = document.getElementById('msg-' + delBtn.dataset.msgId);
            if (card) card.remove();
            const container = document.getElementById('messages-container');
            if (container && !container.children.length) container.classList.add('hidden');
          } else { delBtn.disabled = false; }
        } catch(e) { delBtn.disabled = false; }
        return;
      }
    });

    // ── Calendar ────────────────────────────────────────────────
    const MONTH_NAMES = ['Enero','Febrero','Marzo','Abril','Mayo','Junio',
                         'Julio','Agosto','Septiembre','Octubre','Noviembre','Diciembre'];
    const DAY_HEADERS = ['Lu','Ma','Mi','Ju','Vi','Sa','Do'];
    let calYear, calMonth;

    async function loadCalendar(year, month) {
      calYear = year; calMonth = month;
      document.getElementById('cal-month-label').textContent =
        `${MONTH_NAMES[month - 1]} ${year}`;

      const resp = await fetch(`/api/workday/monthly/?year=${year}&month=${month}`, { headers: authHeaders() });
      if (!resp.ok) return;
      const data = await resp.json();

      const today = new Date();
      const todayY = today.getFullYear(), todayM = today.getMonth() + 1, todayD = today.getDate();

      // First weekday of month (0=Mon … 6=Sun, ISO week)
      const firstDay = new Date(year, month - 1, 1);
      const startOffset = (firstDay.getDay() + 6) % 7; // 0=Mon
      const daysInMonth = new Date(year, month, 0).getDate();

      const grid = document.getElementById('cal-grid');
      let html = DAY_HEADERS.map(d => `<div class="cal-day-header">${d}</div>`).join('');

      // Empty cells before first day
      for (let i = 0; i < startOffset; i++) html += `<div class="cal-day empty"></div>`;

      const autoClosed = new Set(data.auto_closed_days || []);
      const notes  = data.notes  || {};
      const leaves = data.leaves || {};

      const LEAVE_LABELS = { vacacion: 'Vacación', licencia: 'Licencia', permiso: 'Permiso', otro: 'Otro' };

      for (let d = 1; d <= daysInMonth; d++) {
        const hrs     = data.days[String(d)] || 0;
        const isToday  = year === todayY && month === todayM && d === todayD;
        const isActive = data.active_day === d;
        const isClosed = autoClosed.has(d);
        const note     = notes[String(d)];
        const leave    = leaves[String(d)];

        let cls = 'cal-day';
        if (leave)          cls += ` leave-${leave.type}`;
        else if (isClosed)  cls += ' auto-closed-day';
        else if (isActive)  cls += ' active-wd';
        else if (hrs >= 7)  cls += ' work-full';
        else if (hrs >= 4)  cls += ' work-good';
        else if (hrs > 0)   cls += ' has-work';
        if (isToday) cls += ' is-today';
        if (note)    cls += ' has-note';

        const hrsLabel = (!leave && hrs > 0)
          ? `<span class="cal-day-hrs" style="${isClosed ? 'color:var(--cp-red)' : ''}">${hrs % 1 === 0 ? hrs : hrs.toFixed(1)}h</span>`
          : (leave ? `<span class="cal-day-hrs" style="font-size:0.52rem;letter-spacing:0">${LEAVE_LABELS[leave.type]}</span>` : '');

        let extraAttrs = '';
        if (leave)         extraAttrs = ` title="${LEAVE_LABELS[leave.type]}${leave.note ? ': ' + leave.note : ''}"`;
        else if (isClosed) extraAttrs = ' title="Jornada no finalizada"';
        else if (note) {
          extraAttrs = ` data-note="${note.text}"`;
        }

        html += `<div class="${cls}"${extraAttrs}>
          <span class="cal-day-num">${d}</span>
          ${hrsLabel}
        </div>`;
      }

      grid.innerHTML = html;
      document.getElementById('calendar-card').classList.remove('hidden');
    }

    document.getElementById('cal-prev').addEventListener('click', function() {
      let y = calYear, m = calMonth - 1;
      if (m < 1) { m = 12; y--; }
      loadCalendar(y, m);
    });
    document.getElementById('cal-next').addEventListener('click', function() {
      let y = calYear, m = calMonth + 1;
      if (m > 12) { m = 1; y++; }
      loadCalendar(y, m);
    });

    // Init
    checkAgentAlive().then(updateAgentStatus);
    loadWorkdayStatus();
    loadLastReport();
    loadPendingMessages();
    setInterval(loadPendingMessages, 60000);
    const now = new Date();
    loadCalendar(now.getFullYear(), now.getMonth() + 1);

    // WebSocket para notificaciones en tiempo real (mensajes de ejecutivo)
    (function connectDashboardWS() {
      const token = localStorage.getItem('access');
      if (!token) return;
      const proto = location.protocol === 'https:' ? 'wss' : 'ws';
      const ws = new WebSocket(`${proto}://${location.host}/ws/dashboard/?token=${token}`);
      ws.onmessage = function(e) {
        try {
          const msg = JSON.parse(e.data);
          if (msg.type === 'new_message') loadPendingMessages();
        } catch (_) {}
      };
      ws.onclose = function() { setTimeout(connectDashboardWS, 5000); };
    })();
  }

  // ─────────────────────────────────────────────────────────────
  //  View-As (ejecutivo ve el dashboard de un empleado)
  // ─────────────────────────────────────────────────────────────
  async function initViewAs(empId) {
    const MONTH_NAMES = ['Enero','Febrero','Marzo','Abril','Mayo','Junio',
                         'Julio','Agosto','Septiembre','Octubre','Noviembre','Diciembre'];
    const DAY_HEADERS = ['Lu','Ma','Mi','Ju','Vi','Sa','Do'];

    // Ocultar lo que no aplica: logout (cierra sesión del ejecutivo),
    // setup-required y agent-version-card (muestran datos del agente del ejecutivo, no del empleado)
    ['btn-logout', 'setup-required', 'agent-version-card'].forEach(id => {
      document.getElementById(id)?.classList.add('hidden');
    });

    // Asegurar que el status-card sea visible (updateAgentStatus pudo haberlo ocultado)
    document.getElementById('status-card')?.classList.remove('hidden');
    // Ocultar botones hasta saber el estado del agente del empleado
    ['btn-start', 'btn-end'].forEach(id => document.getElementById(id)?.classList.add('hidden'));

    // Ocultar spinner de carga inmediatamente
    const statusLoading  = document.getElementById('status-loading');
    const statusInactive = document.getElementById('status-inactive');
    const statusActive   = document.getElementById('status-active');
    if (statusLoading) statusLoading.classList.add('hidden');
    if (statusInactive) statusInactive.classList.remove('hidden');

    try {
      const resp = await fetch(`/api/employees/${empId}/view-data/`, { headers: authHeaders() });
      if (!resp.ok) {
        if (statusInactive) {
          statusInactive.querySelector('p')?.insertAdjacentHTML('afterend',
            `<p style="font-size:0.75rem;color:var(--cp-red);margin-top:4px">Error ${resp.status} al cargar datos</p>`);
        }
        return;
      }
      const data = await resp.json();

      // Botones según estado de jornada y agente (igual que en el dashboard del empleado)
      const agentOk = data.agent_is_active || data.solo_movil;
      const hasActive = !!data.workday?.active;
      const btnS = document.getElementById('btn-start');
      const btnE = document.getElementById('btn-end');
      if (btnS) { btnS.classList.toggle('hidden', !agentOk || hasActive);  btnS.disabled = false; }
      if (btnE) { btnE.classList.toggle('hidden', !agentOk || !hasActive); btnE.disabled = false; }

      // Perfil
      setAvatar(document.getElementById('profile-avatar'), data.full_name);
      document.getElementById('profile-fullname').textContent = data.full_name;
      document.getElementById('profile-email').textContent   = data.email || '';

      // Ocultar inactive por defecto antes de decidir estado real
      if (statusInactive) statusInactive.classList.add('hidden');

      if (data.workday?.active) {
        const wd  = data.workday;
        const h   = Math.floor(wd.duration_minutes / 60);
        const m   = wd.duration_minutes % 60;
        const dur = h > 0 ? `${h}h ${m}min` : `${m} min`;
        const st  = new Date(wd.start_time);
        const fmt = st.toLocaleTimeString('es-BO', { hour: '2-digit', minute: '2-digit' });
        if (statusActive) {
          statusActive.classList.remove('hidden');
          document.getElementById('active-since').textContent = `Desde las ${fmt} · ${dur}`;
        }
        // Mostrar reporte si existe
        if (wd.activities_done || wd.activities_planned) {
          showViewAsReport(wd.activities_planned, wd.activities_done, null);
        }
      } else {
        if (statusInactive) statusInactive.classList.remove('hidden');
        // Último reporte
        if (data.last_report?.has_report) {
          const d = new Date(data.last_report.date);
          const dateStr = d.toLocaleDateString('es-BO', { weekday: 'long', day: 'numeric', month: 'long' });
          showViewAsReport(data.last_report.activities_planned, data.last_report.activities_done, dateStr);
        }
      }

      // Mensajes pendientes
      const msgResp = await fetch(`/api/employees/${empId}/messages/`, { headers: authHeaders() });
      if (msgResp.ok) {
        const messages = await msgResp.json();
        const container = document.getElementById('messages-container');
        if (messages.length && container) {
          container.innerHTML = messages.map(m => `
            <div class="message-banner cupertino-card" id="msg-${m.id}">
              <div style="flex:1">
                <p class="text-xs font-semibold mb-1" style="color:var(--cp-orange)">${m.sender_name}</p>
                <p class="text-sm" style="color:var(--cp-text-hi);white-space:pre-wrap">${m.body}</p>
                <p class="text-xs mt-2 font-medium" style="color:var(--cp-text-mid)">${new Date(m.sent_at).toLocaleString('es-BO')}</p>
              </div>
              <button class="btn-msg-done btn-acknowledge" data-msg-id="${m.id}" data-view-as="${empId}">Listo</button>
            </div>`).join('');
          container.classList.remove('hidden');

          container.addEventListener('click', async (e) => {
            const btn = e.target.closest('.btn-acknowledge');
            if (!btn) return;
            const msgId  = btn.dataset.msgId;
            const viewAs = btn.dataset.viewAs;
            const resp = await fetch(`/api/messages/${msgId}/acknowledge/?view_as=${viewAs}`, {
              method: 'POST', headers: authHeaders(),
            });
            if (resp.ok) {
              document.getElementById(`msg-${msgId}`)?.remove();
              if (!container.querySelector('.message-banner')) container.classList.add('hidden');
            }
          });
        }
      }

      // Calendario
      const now = new Date();
      let calYear = now.getFullYear(), calMonth = now.getMonth() + 1;

      async function loadViewAsCalendar(year, month) {
        calYear = year; calMonth = month;
        document.getElementById('cal-month-label').textContent = `${MONTH_NAMES[month - 1]} ${year}`;
        const r = await fetch(`/api/employees/${empId}/monthly/?year=${year}&month=${month}`, { headers: authHeaders() });
        if (!r.ok) return;
        const calData = await r.json();

        const todayY = now.getFullYear(), todayM = now.getMonth() + 1, todayD = now.getDate();
        const firstDay = new Date(year, month - 1, 1);
        const startOffset = (firstDay.getDay() + 6) % 7;
        const daysInMonth = new Date(year, month, 0).getDate();

        const grid = document.getElementById('cal-grid');
        let html = DAY_HEADERS.map(d => `<div class="cal-day-header">${d}</div>`).join('');
        for (let i = 0; i < startOffset; i++) html += `<div class="cal-day empty"></div>`;

        const autoClosed = new Set(calData.auto_closed_days || []);
        const notes  = calData.notes  || {};
        const leaves = calData.leaves || {};
        const LEAVE_LABELS = { vacacion: 'Vacación', licencia: 'Licencia', permiso: 'Permiso', otro: 'Otro' };

        for (let d = 1; d <= daysInMonth; d++) {
          const hrs = calData.days[String(d)] || 0;
          const isToday  = year === todayY && month === todayM && d === todayD;
          const isActive = calData.active_day === d;
          const isClosed = autoClosed.has(d);
          const note  = notes[String(d)];
          const leave = leaves[String(d)];

          let cls = 'cal-day';
          if (leave)         cls += ` leave-${leave.type}`;
          else if (isClosed) cls += ' auto-closed-day';
          else if (isActive) cls += ' active-wd';
          else if (hrs >= 7) cls += ' work-full';
          else if (hrs >= 4) cls += ' work-good';
          else if (hrs > 0)  cls += ' has-work';
          if (isToday) cls += ' is-today';
          if (note)    cls += ' has-note';

          const hrsLabel = (!leave && hrs > 0)
            ? `<span class="cal-day-hrs" style="${isClosed ? 'color:var(--cp-red)' : ''}">${hrs % 1 === 0 ? hrs : hrs.toFixed(1)}h</span>`
            : (leave ? `<span class="cal-day-hrs" style="font-size:0.52rem;letter-spacing:0">${LEAVE_LABELS[leave.type]}</span>` : '');

          let extraAttrs = '';
          if (leave)         extraAttrs = ` title="${LEAVE_LABELS[leave.type]}${leave.note ? ': '+leave.note : ''}"`;
          else if (isClosed) extraAttrs = ' title="Jornada no finalizada"';
          else if (note)     extraAttrs = ` data-note="${note.text}"`;

          html += `<div class="${cls}"${extraAttrs}><span class="cal-day-num">${d}</span>${hrsLabel}</div>`;
        }
        grid.innerHTML = html;
        document.getElementById('calendar-card').classList.remove('hidden');
      }

      document.getElementById('cal-prev').addEventListener('click', () => {
        let y = calYear, m = calMonth - 1; if (m < 1) { m = 12; y--; } loadViewAsCalendar(y, m);
      });
      document.getElementById('cal-next').addEventListener('click', () => {
        let y = calYear, m = calMonth + 1; if (m > 12) { m = 1; y++; } loadViewAsCalendar(y, m);
      });

      loadViewAsCalendar(calYear, calMonth);

    } catch (e) {
      if (statusInactive) {
        statusInactive.querySelector('p')?.insertAdjacentHTML('afterend',
          `<p style="font-size:0.75rem;color:var(--cp-red);margin-top:4px">Error: ${e.message}</p>`);
      }
    }
  }

  function showViewAsReport(planned, done, dateStr) {
    const col    = document.getElementById('last-report-col');
    const planEl = document.getElementById('report-planned');
    const doneEl = document.getElementById('report-done');
    const dateEl = document.getElementById('report-date');
    if (planEl) planEl.textContent = planned || '';
    if (doneEl) doneEl.textContent = done    || '';
    if (dateEl) dateEl.textContent = dateStr || '';
    if (col)    col.classList.remove('hidden');
  }

  init();
})();
