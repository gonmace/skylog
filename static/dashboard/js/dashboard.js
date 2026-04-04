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

  const ALL_VIEWS = ['view-loading', 'view-noaccess', 'view-employee', 'view-executive'];

  function showView(id) {
    ALL_VIEWS.forEach(v => {
      document.getElementById(v).classList.toggle('hidden', v !== id);
    });
  }

  async function init() {
    // Si no hay token (p.ej. en iframe tras login OAuth),
    // intentar reclamarlo desde la sesión Django antes de redirigir al login.
    if (!getToken('access')) {
      try {
        const r = await fetch('/api/auth/claim-token/');
        if (r.ok) {
          const t = await r.json();
          if (t.access) {
            setToken('access', t.access, 7200);
            if (t.refresh) setToken('refresh', t.refresh, 604800);
          }
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

      if (profile.skylog_access === false) {
        showView('view-noaccess');
        initNoAccess();
        return;
      }

      if (profile.is_executive) {
        showView('view-executive');
        initExecutive(profile);
        return;
      }

      showView('view-employee');
      initEmployee(profile);
    } catch (e) {
      // network error — leave loading screen visible
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
  function initEmployee(initialProfileData) {
    let profileData = initialProfileData;
    // Populate profile card
    const profileFullname = document.getElementById('profile-fullname');
    const profileEmail    = document.getElementById('profile-email');
    if (profileFullname) profileFullname.textContent = profileData.full_name || profileData.nextcloud_username;
    if (profileEmail)    profileEmail.textContent    = profileData.email || '';

    const parts    = (profileData.full_name || profileData.nextcloud_username || '?').trim().split(/\s+/);
    const initials = parts.length >= 2 ? parts[0][0] + parts[parts.length - 1][0] : parts[0].slice(0, 2);
    const profileAvatar = document.getElementById('profile-avatar');
    if (profileAvatar) profileAvatar.textContent = initials;

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

    async function endWorkday() {
      const done    = activitiesDone.value.trim();
      const planned = activitiesPlanned.value.trim();
      if (!done || !planned) {
        modalError.classList.remove('hidden');
        modalErrorText.textContent = 'Completa ambos campos antes de finalizar.';
        return;
      }
      modalError.classList.add('hidden');
      btnModalSubmit.disabled = true;
      btnModalSubmit.textContent = 'Finalizando...';
      try {
        const resp = await fetch('/api/workday/end/', {
          method: 'POST',
          headers: { ...authHeaders(), 'X-CSRFToken': getCsrfToken() },
          body: JSON.stringify({ workday_id: activeWorkdayId, activities_done: done, activities_planned: planned }),
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
        container.innerHTML = messages.map(m => `
          <div class="message-banner cupertino-card" id="msg-${m.id}">
            <div style="flex:1">
              <p class="text-xs font-semibold mb-1" style="color:var(--cp-orange)">${m.sender_name}</p>
              <p class="text-sm" style="color:var(--cp-text-hi);white-space:pre-wrap">${m.body}</p>
              <p class="text-xs mt-2" style="color:var(--cp-text-dim)">${new Date(m.sent_at).toLocaleString('es-BO')}</p>
            </div>
            <button class="btn-msg-done btn-acknowledge" data-msg-id="${m.id}">Listo</button>
          </div>`).join('');
        container.classList.remove('hidden');
      } catch(e) {}
    }

    document.getElementById('messages-container').addEventListener('click', async (e) => {
      const btn = e.target.closest('.btn-acknowledge');
      if (!btn) return;
      const msgId = btn.dataset.msgId;
      btn.disabled = true;
      try {
        const resp = await fetch(`/api/messages/${msgId}/acknowledge/`, {
          method: 'POST',
          headers: { ...authHeaders(), 'X-CSRFToken': getCsrfToken() },
        });
        if (resp.ok) {
          document.getElementById(`msg-${msgId}`)?.remove();
          const container = document.getElementById('messages-container');
          if (!container.querySelector('.message-banner')) container.classList.add('hidden');
        } else { btn.disabled = false; }
      } catch(e) { btn.disabled = false; }
    });

    // Init
    checkAgentAlive().then(updateAgentStatus);
    loadWorkdayStatus();
    loadLastReport();
    loadPendingMessages();
    setInterval(loadPendingMessages, 60000);
  }

  // ─────────────────────────────────────────────────────────────
  //  Executive
  // ─────────────────────────────────────────────────────────────
  function initExecutive() {
    const REFRESH_INTERVAL = 180 * 1000;

    function formatTime(iso) {
      return new Date(iso).toLocaleTimeString('es-BO', { hour: '2-digit', minute: '2-digit', hour12: false });
    }

    function formatDuration(minutes) {
      if (!minutes && minutes !== 0) return '—';
      const h = Math.floor(minutes / 60);
      const m = minutes % 60;
      return h > 0 ? `${h}h ${m}m` : `${m}m`;
    }

    function initials(name) {
      const parts = (name || '?').trim().split(/\s+/);
      return parts.length >= 2 ? parts[0][0] + parts[parts.length - 1][0] : parts[0].slice(0, 2);
    }

    function renderRow(emp) {
      const workday  = emp.workday;
      const isActive = workday?.active;
      const agentOn  = emp.agent_is_active;

      const workdayBadge = isActive
        ? `<span class="badge-active"><span class="dot-online" style="animation:pulse 2s infinite"></span>Activa</span>`
        : `<span class="badge-inactive">Sin jornada</span>`;

      const version  = emp.agent_version
        ? ` <span style="color:var(--cp-text-dim);font-family:monospace;font-size:0.72rem">— ${emp.agent_version}</span>`
        : '';
      const agentDot = agentOn
        ? `<span class="agent-online"><span class="dot-online"></span>Online${version}</span>`
        : `<span class="agent-offline"><span class="dot-offline"></span>Offline${version}</span>`;

      const interval = emp.capture_interval_minutes != null
        ? `<span style="color:var(--cp-text-mid);font-size:0.82rem">${emp.capture_interval_minutes} min</span>`
        : `<span style="color:var(--cp-text-dim)">—</span>`;

      const captureBtn = agentOn
        ? `<button class="btn-capture btn-capture-ios" data-id="${emp.id}" title="Capturar pantalla ahora">
             <svg xmlns="http://www.w3.org/2000/svg" width="15" height="15" fill="none" viewBox="0 0 24 24" stroke="currentColor" class="pointer-events-none">
               <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M3 9a2 2 0 012-2h.93a2 2 0 001.664-.89l.812-1.22A2 2 0 0110.07 4h3.86a2 2 0 011.664.89l.812 1.22A2 2 0 0018.07 7H19a2 2 0 012 2v9a2 2 0 01-2 2H5a2 2 0 01-2-2V9z"/>
               <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M15 13a3 3 0 11-6 0 3 3 0 016 0z"/>
             </svg>
           </button>`
        : '';

      const checked      = emp.screenshots_enabled ? 'checked' : '';
      const skylogChecked = emp.skylog_access ? 'checked' : '';
      const disabled     = !emp.skylog_access;
      const rowStyle     = disabled ? 'opacity:0.35;pointer-events:none' : '';
      const ssDisabled   = disabled ? 'disabled' : '';

      const msgBtn = `<button class="btn-send-msg" data-id="${emp.id}" data-name="${emp.full_name || emp.id}" title="Enviar mensaje">
        <svg xmlns="http://www.w3.org/2000/svg" width="14" height="14" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2">
          <path stroke-linecap="round" stroke-linejoin="round" d="M8 10h.01M12 10h.01M16 10h.01M9 16H5a2 2 0 01-2-2V6a2 2 0 012-2h14a2 2 0 012 2v8a2 2 0 01-2 2h-5l-3 3v-3z"/>
        </svg>
      </button>`;

      return `<tr style="${disabled ? 'background:var(--cp-row-disabled)' : ''}">
        <td style="${rowStyle}">
          <div style="display:flex;align-items:center;gap:10px">
            <div class="avatar-circle">${initials(emp.full_name)}</div>
            <span style="font-weight:500;font-size:0.875rem">${emp.full_name}</span>
          </div>
        </td>
        <td style="${rowStyle}">${disabled ? '<span style="color:var(--cp-text-dim)">—</span>' : workdayBadge}</td>
        <td style="color:var(--cp-text-mid);font-size:0.82rem;${rowStyle}">${disabled ? '' : (isActive ? formatTime(workday.start_time) : '—')}</td>
        <td style="font-size:0.82rem;${rowStyle}">
          ${disabled ? '' : `<span style="color:var(--cp-text-mid)">${isActive ? formatDuration(workday.duration_minutes) : '—'}</span>
          ${isActive && workday.inactive_minutes > 0
            ? `<br><span style="color:rgba(255,99,99,0.75);font-size:0.72rem">▾ ~${formatDuration(workday.inactive_minutes)} inactivo est.</span>`
            : ''}`}
        </td>
        <td class="interval-cell" style="${rowStyle}">${disabled || !emp.screenshots_enabled ? '' : interval}</td>
        <td style="${rowStyle}">${disabled ? '' : agentDot}</td>
        <td style="text-align:center;${rowStyle}">
          <div style="display:inline-flex;align-items:center;gap:10px">
            ${disabled ? '' : captureBtn}
            <label class="ios-toggle" style="${disabled ? 'pointer-events:none' : ''}">
              <input type="checkbox" data-emp-id="${emp.id}" class="ss-toggle" ${checked} ${ssDisabled}>
              <span class="ios-toggle-track"></span>
            </label>
          </div>
        </td>
        <td style="text-align:center">
          <label class="ios-toggle skylog-toggle">
            <input type="checkbox" data-emp-id="${emp.id}" class="skylog-toggle-input" ${skylogChecked}>
            <span class="ios-toggle-track"></span>
          </label>
        </td>
        <td style="text-align:center">${msgBtn}</td>
      </tr>`;
    }

    async function loadOverview() {
      try {
        const resp = await fetch('/api/employees/overview/', { headers: authHeaders() });
        if (resp.status === 401) { logout(); return; }
        if (resp.status === 403) { init(); return; }
        const data = await resp.json();

        document.getElementById('stat-active').textContent    = data.summary.active_now;
        document.getElementById('stat-completed').textContent = data.summary.completed_today;
        document.getElementById('stat-agents').textContent    = data.summary.agents_online;
        document.getElementById('stat-total').textContent     = data.summary.total_employees;

        document.getElementById('table-loading').classList.add('hidden');
        if (data.employees.length === 0) {
          document.getElementById('table-empty').classList.remove('hidden');
        } else {
          const tbody = document.getElementById('employee-tbody');
          tbody.innerHTML = data.employees.map(renderRow).join('');
          document.getElementById('table-container').classList.remove('hidden');
          document.getElementById('table-empty').classList.add('hidden');
        }

        const ts = new Date().toLocaleTimeString('es-BO', { hour: '2-digit', minute: '2-digit', second: '2-digit', hour12: false });
        document.getElementById('exec-last-updated').textContent = `Actualizado a las ${ts}`;
      } catch (e) {}
    }

    document.getElementById('exec-btn-logout').addEventListener('click', logout);

    // Capture button — event delegation
    document.getElementById('employee-tbody').addEventListener('click', async (e) => {
      const btn = e.target.closest('.btn-capture');
      if (!btn) return;
      const employeeId = btn.dataset.id;
      const origHTML = btn.innerHTML;
      btn.disabled = true;
      btn.innerHTML = '<span class="loading loading-spinner loading-xs"></span>';
      try {
        const resp = await fetch(`/api/employees/${employeeId}/capture/`, {
          method: 'POST',
          headers: { ...authHeaders(), 'X-CSRFToken': getCsrfToken() },
        });
        if (resp.ok) {
          btn.innerHTML = '<svg xmlns="http://www.w3.org/2000/svg" width="15" height="15" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M5 13l4 4L19 7"/></svg>';
          setTimeout(() => { btn.innerHTML = origHTML; btn.disabled = false; }, 2000);
        } else {
          btn.innerHTML = origHTML;
          btn.disabled = false;
        }
      } catch (e) {
        btn.innerHTML = origHTML;
        btn.disabled = false;
      }
    });

    // Skylog toggle
    const modalSkylogOff  = document.getElementById('modal-skylog-off');
    const btnSkylogCancel = document.getElementById('btn-skylog-cancel');
    const btnSkylogConfirm = document.getElementById('btn-skylog-confirm');
    let pendingSkylogToggle = null;

    async function applySkylogToggle(toggle, on) {
      toggle.disabled = true;
      try {
        await fetch(`/api/employees/${toggle.dataset.empId}/skylog/`, {
          method: 'PATCH',
          headers: authHeaders(),
          body: JSON.stringify({ skylog_access: on }),
        });
        await loadOverview();
      } catch (_) { toggle.checked = !on; }
      finally { toggle.disabled = false; }
    }

    document.getElementById('employee-tbody').addEventListener('change', (e) => {
      const skylogToggle = e.target.closest('.skylog-toggle-input');
      if (skylogToggle) {
        if (!skylogToggle.checked) {
          skylogToggle.checked = true;
          pendingSkylogToggle = skylogToggle;
          modalSkylogOff.showModal();
        } else {
          applySkylogToggle(skylogToggle, true);
        }
      }
    });

    btnSkylogCancel.addEventListener('click', () => { pendingSkylogToggle = null; modalSkylogOff.close(); });
    btnSkylogConfirm.addEventListener('click', async () => {
      modalSkylogOff.close();
      if (!pendingSkylogToggle) return;
      const t = pendingSkylogToggle;
      pendingSkylogToggle = null;
      t.checked = false;
      await applySkylogToggle(t, false);
    });

    // Screenshots toggle
    const modalSsOff  = document.getElementById('modal-ss-off');
    const btnSsCancel = document.getElementById('btn-ss-cancel');
    const btnSsConfirm = document.getElementById('btn-ss-confirm');
    let pendingToggle = null;

    async function applyScreenshotsToggle(toggle, on) {
      toggle.disabled = true;
      try {
        await fetch(`/api/employees/${toggle.dataset.empId}/screenshots/`, {
          method: 'PATCH',
          headers: authHeaders(),
          body: JSON.stringify({ screenshots_enabled: on }),
        });
        await loadOverview();
      } catch (_) { toggle.checked = !on; }
      finally { toggle.disabled = false; }
    }

    document.getElementById('employee-tbody').addEventListener('change', (e) => {
      const toggle = e.target.closest('.ss-toggle');
      if (!toggle) return;
      if (!toggle.checked) {
        toggle.checked = true;
        pendingToggle = toggle;
        modalSsOff.showModal();
      } else {
        const intervalCell = toggle.closest('tr')?.querySelector('.interval-cell');
        if (intervalCell && intervalCell.dataset.prev) intervalCell.innerHTML = intervalCell.dataset.prev;
        applyScreenshotsToggle(toggle, true);
      }
    });

    btnSsCancel.addEventListener('click', () => { pendingToggle = null; modalSsOff.close(); });
    btnSsConfirm.addEventListener('click', async () => {
      modalSsOff.close();
      if (!pendingToggle) return;
      const t = pendingToggle;
      pendingToggle = null;
      t.checked = false;
      const intervalCell = t.closest('tr')?.querySelector('.interval-cell');
      if (intervalCell) { intervalCell.dataset.prev = intervalCell.innerHTML; intervalCell.innerHTML = ''; }
      await applyScreenshotsToggle(t, false);
    });

    // Send message modal
    const modalSendMsg  = document.getElementById('modal-send-message');
    const btnMsgCancel  = document.getElementById('btn-msg-cancel');
    const btnMsgSend    = document.getElementById('btn-msg-send');
    const modalMsgBody  = document.getElementById('modal-msg-body');
    const modalMsgRecip = document.getElementById('modal-msg-recipient');
    const modalMsgErrEl = document.getElementById('modal-msg-error');
    const modalMsgErrTxt= document.getElementById('modal-msg-error-text');
    let pendingMsgEmpId = null;

    document.getElementById('employee-tbody').addEventListener('click', (e) => {
      const btn = e.target.closest('.btn-send-msg');
      if (!btn) return;
      pendingMsgEmpId = btn.dataset.id;
      modalMsgRecip.textContent = `Para: ${btn.dataset.name}`;
      modalMsgBody.value = '';
      modalMsgErrEl.classList.add('hidden');
      btnMsgSend.disabled = false;
      btnMsgSend.textContent = 'Enviar';
      modalSendMsg.showModal();
    });

    btnMsgCancel.addEventListener('click', () => { modalSendMsg.close(); pendingMsgEmpId = null; });

    btnMsgSend.addEventListener('click', async () => {
      const body = modalMsgBody.value.trim();
      if (!body) { modalMsgErrEl.classList.remove('hidden'); modalMsgErrTxt.textContent = 'El mensaje no puede estar vacío.'; return; }
      modalMsgErrEl.classList.add('hidden');
      btnMsgSend.disabled = true;
      btnMsgSend.textContent = 'Enviando...';
      try {
        const resp = await fetch(`/api/employees/${pendingMsgEmpId}/message/`, {
          method: 'POST',
          headers: { ...authHeaders(), 'Content-Type': 'application/json', 'X-CSRFToken': getCsrfToken() },
          body: JSON.stringify({ body }),
        });
        if (resp.ok) { modalSendMsg.close(); pendingMsgEmpId = null; }
        else {
          const d = await resp.json().catch(() => ({}));
          modalMsgErrEl.classList.remove('hidden');
          modalMsgErrTxt.textContent = d.error || 'Error al enviar';
          btnMsgSend.disabled = false;
          btnMsgSend.textContent = 'Enviar';
        }
      } catch(e) {
        modalMsgErrEl.classList.remove('hidden');
        modalMsgErrTxt.textContent = 'Error de conexión';
        btnMsgSend.disabled = false;
        btnMsgSend.textContent = 'Enviar';
      }
    });

    // Init
    loadOverview();
    let poller = setInterval(loadOverview, REFRESH_INTERVAL);

    document.addEventListener('visibilitychange', () => {
      if (document.hidden) { clearInterval(poller); }
      else { loadOverview(); poller = setInterval(loadOverview, REFRESH_INTERVAL); }
    });
  }

  init();
})();
