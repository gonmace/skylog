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

      const LEAVE_LABELS = { vacacion: 'Vacación', licencia: 'Licencia', permiso: 'Permiso' };

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

      // ── Resumen semana actual (excluye días auto-cerrados) ─────
      const weekStat  = document.getElementById('cal-week-stat');
      const weekTotal = document.getElementById('cal-week-total');
      const weekDays  = document.getElementById('cal-week-days');
      const isCurrentMonth = year === todayY && month === todayM;
      if (isCurrentMonth) {
        // Lunes de la semana actual (ISO: 0=Lun)
        const monday = todayD - ((today.getDay() + 6) % 7);
        let weekHrs = 0, daysWithWork = 0;
        for (let d = monday; d <= todayD; d++) {
          if (autoClosed.has(d)) continue;
          const h = data.days[String(d)] || 0;
          weekHrs += h;
          if (h > 0) daysWithWork++;
        }
        const wh = Math.floor(weekHrs);
        const wm = Math.round((weekHrs - wh) * 60);
        weekTotal.textContent = wm > 0 ? `${wh} h ${wm} min` : `${wh} h`;
        weekDays.textContent  = `· ${daysWithWork} día${daysWithWork !== 1 ? 's' : ''} trabajado${daysWithWork !== 1 ? 's' : ''}`;
        weekStat.style.display = 'block';
      } else {
        weekStat.style.display = 'none';
      }
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

      const autoClosed = workday?.auto_closed;
      const workdayBadge = isActive
        ? `<span class="badge-active"><span class="dot-online" style="animation:pulse 2s infinite"></span>Activa</span>`
        : autoClosed
          ? `<span class="badge-inactive" style="background:color-mix(in srgb,var(--cp-red) 12%,transparent);color:var(--cp-red);border-color:color-mix(in srgb,var(--cp-red) 25%,transparent);cursor:default" title="Jornada no finalizada — cerrada automáticamente a las 17:00">
               <svg xmlns='http://www.w3.org/2000/svg' width='10' height='10' fill='none' viewBox='0 0 24 24' stroke='currentColor' stroke-width='2.5' style='display:inline;margin-right:3px;vertical-align:middle'><path stroke-linecap='round' stroke-linejoin='round' d='M12 9v4m0 4h.01M10.29 3.86L1.82 18a2 2 0 001.71 3h16.94a2 2 0 001.71-3L13.71 3.86a2 2 0 00-3.42 0z'/></svg>Sin cerrar
             </span>`
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

      const captureBtn = agentOn && emp.workday?.active
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
          <div style="display:flex;align-items:center;gap:10px;white-space:nowrap">
            <div class="avatar-circle">${initials(emp.full_name)}</div>
            <span style="font-weight:500;font-size:0.875rem">${emp.full_name}</span>
          </div>
        </td>
        <td style="white-space:nowrap;${rowStyle}">${disabled ? '<span style="color:var(--cp-text-dim)">—</span>' : workdayBadge}</td>
        <td style="color:${autoClosed ? 'var(--cp-red)' : 'var(--cp-text-mid)'};font-size:0.82rem;${rowStyle}">${disabled ? '' : (isActive || autoClosed ? formatTime(workday.start_time) : '—')}</td>
        <td style="font-size:0.82rem;${rowStyle}">
          ${disabled ? '' : `<span style="color:${autoClosed ? 'var(--cp-red)' : 'var(--cp-text-mid)'}">${(isActive || autoClosed) ? formatDuration(workday.duration_minutes) : '—'}</span>
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
        <td style="text-align:center">
          <button class="btn-emp-cal btn-capture-ios" data-id="${emp.id}" data-name="${emp.full_name}" title="Ver calendario">
            <svg xmlns="http://www.w3.org/2000/svg" width="14" height="14" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2" class="pointer-events-none">
              <path stroke-linecap="round" stroke-linejoin="round" d="M8 7V3m8 4V3m-9 8h10M5 21h14a2 2 0 002-2V7a2 2 0 00-2-2H5a2 2 0 00-2 2v12a2 2 0 002 2z"/>
            </svg>
          </button>
        </td>
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

    // ── Shared calendar helpers ──────────────────────────────────
    const EXEC_MONTH_NAMES = ['Enero','Febrero','Marzo','Abril','Mayo','Junio',
                              'Julio','Agosto','Septiembre','Octubre','Noviembre','Diciembre'];
    const EXEC_DAY_HDR = ['Lu','Ma','Mi','Ju','Vi','Sa','Do'];
    const LEAVE_LABELS = { vacacion: 'Vacación', licencia: 'Licencia', permiso: 'Permiso' };

    function toIso(year, month, day) {
      return `${year}-${String(month).padStart(2,'0')}-${String(day).padStart(2,'0')}`;
    }

    function buildCalGrid(data, year, month, interactive) {
      const today = new Date();
      const todayY = today.getFullYear(), todayM = today.getMonth()+1, todayD = today.getDate();
      const firstDay   = new Date(year, month-1, 1);
      const startOffset = (firstDay.getDay()+6) % 7;
      const daysInMonth = new Date(year, month, 0).getDate();
      const autoClosed  = new Set(data.auto_closed_days || []);
      const notes  = data.notes  || {};
      const leaves = data.leaves || {};

      let html = EXEC_DAY_HDR.map(d => `<div class="cal-day-header">${d}</div>`).join('');
      for (let i = 0; i < startOffset; i++) html += `<div class="cal-day empty"></div>`;

      for (let d = 1; d <= daysInMonth; d++) {
        const hrs     = data.days ? (data.days[String(d)] || 0) : 0;
        const isToday  = year===todayY && month===todayM && d===todayD;
        const isActive = data.active_day === d;
        const isClosed = autoClosed.has(d);
        const note     = notes[String(d)];
        const leave    = leaves[String(d)];

        let cls = 'cal-day' + (interactive ? ' cal-interactive' : '');
        if (leave)          cls += ` leave-${leave.type}`;
        else if (isClosed)  cls += ' auto-closed-day';
        else if (isActive)  cls += ' active-wd';
        else if (hrs >= 7)  cls += ' work-full';
        else if (hrs >= 4)  cls += ' work-good';
        else if (hrs > 0)   cls += ' has-work';
        if (isToday) cls += ' is-today';
        if (note)    cls += ' has-note';

        const hrsLabel = (!leave && hrs > 0)
          ? `<span class="cal-day-hrs" style="${isClosed?'color:var(--cp-red)':''}">${hrs%1===0?hrs:hrs.toFixed(1)}h</span>`
          : (leave ? `<span class="cal-day-hrs" style="font-size:0.52rem;letter-spacing:0">${LEAVE_LABELS[leave.type]}</span>` : '');

        let tip = '';
        if (leave && leave.note) tip = ` title="${LEAVE_LABELS[leave.type]}: ${leave.note}"`;
        else if (leave) tip = ` title="${LEAVE_LABELS[leave.type]}"`;
        else if (isClosed) tip = ' title="Cerrada automáticamente a las 17:00"';
        else if (note) tip = ` title="${note.text}"`;

        html += `<div class="${cls}" data-day="${d}"${tip}>
          <span class="cal-day-num">${d}</span>${hrsLabel}
        </div>`;
      }
      return html;
    }

    // ── Global executive calendar ────────────────────────────────
    let execCalYear, execCalMonth;

    const modalCalNote  = document.getElementById('modal-cal-note');
    const calNoteTitle  = document.getElementById('cal-note-title');
    const calNoteType   = document.getElementById('cal-note-type');
    const calNoteText   = document.getElementById('cal-note-text');
    const calNoteDelete = document.getElementById('cal-note-delete');
    const calNoteCancel = document.getElementById('cal-note-cancel');
    const calNoteSave   = document.getElementById('cal-note-save');
    let activeNoteDate  = null, activeNoteId = null;

    async function loadExecCalendar(year, month) {
      execCalYear = year; execCalMonth = month;
      document.getElementById('exec-cal-month-label').textContent = `${EXEC_MONTH_NAMES[month-1]} ${year}`;
      const resp = await fetch(`/api/calendar/notes/?year=${year}&month=${month}`, { headers: authHeaders() });
      const notes = resp.ok ? await resp.json() : [];
      const notesMap = {};
      notes.forEach(n => { notesMap[String(parseInt(n.date.split('-')[2]))] = {text: n.text, type: n.note_type, id: n.id}; });
      document.getElementById('exec-cal-grid').innerHTML =
        buildCalGrid({ notes: notesMap }, year, month, true);
    }

    document.getElementById('exec-cal-prev').addEventListener('click', () => {
      let y = execCalYear, m = execCalMonth-1; if (m<1){m=12;y--;} loadExecCalendarFull(y,m);
    });
    document.getElementById('exec-cal-next').addEventListener('click', () => {
      let y = execCalYear, m = execCalMonth+1; if (m>12){m=1;y++;} loadExecCalendarFull(y,m);
    });

    document.getElementById('exec-cal-grid').addEventListener('click', function(e) {
      const cell = e.target.closest('.cal-day[data-day]');
      if (!cell) return;
      const d = parseInt(cell.dataset.day);
      activeNoteDate = toIso(execCalYear, execCalMonth, d);

      // Check if note exists
      const noteEl = document.getElementById('exec-cal-grid')
        .querySelector(`.cal-day[data-day="${d}"].has-note`);

      // Find note id from loaded data (stored in title or re-fetch)
      // We re-check via cell title data approach — simpler: store id in data attr
      // Actually we need to re-fetch or store. Let's store in data-note-id.
      activeNoteId = cell.dataset.noteId || null;

      calNoteTitle.textContent = `${d} de ${EXEC_MONTH_NAMES[execCalMonth-1]} ${execCalYear}`;
      calNoteType.value = cell.dataset.noteType || 'feriado';
      calNoteText.value = cell.dataset.noteText || '';
      calNoteDelete.style.display = activeNoteId ? 'block' : 'none';
      modalCalNote.showModal();
      setTimeout(() => calNoteText.focus(), 50);
    });

    calNoteCancel.addEventListener('click', () => modalCalNote.close());
    calNoteDelete.addEventListener('click', async () => {
      if (!activeNoteId) return;
      await fetch(`/api/calendar/notes/${activeNoteId}/`, {
        method: 'DELETE', headers: { ...authHeaders(), 'X-CSRFToken': getCsrfToken() },
      });
      modalCalNote.close();
      loadExecCalendarFull(execCalYear, execCalMonth);
    });
    calNoteSave.addEventListener('click', async () => {
      const text = calNoteText.value.trim();
      if (!text) { calNoteText.focus(); return; }
      await fetch('/api/calendar/notes/', {
        method: 'POST',
        headers: { ...authHeaders(), 'Content-Type': 'application/json', 'X-CSRFToken': getCsrfToken() },
        body: JSON.stringify({ date: activeNoteDate, text, note_type: calNoteType.value }),
      });
      modalCalNote.close();
      loadExecCalendarFull(execCalYear, execCalMonth);
    });

    async function loadExecCalendarFull(year, month) {
      await loadExecCalendar(year, month);
      // Enrich cells with note metadata for click handler
      const resp2 = await fetch(`/api/calendar/notes/?year=${year}&month=${month}`, { headers: authHeaders() });
      if (!resp2.ok) return;
      const notes2 = await resp2.json();
      notes2.forEach(n => {
        const day = parseInt(n.date.split('-')[2]);
        const cell = document.querySelector(`#exec-cal-grid .cal-day[data-day="${day}"]`);
        if (cell) {
          cell.dataset.noteId   = n.id;
          cell.dataset.noteType = n.note_type;
          cell.dataset.noteText = n.text;
        }
      });
    }

    // ── Employee calendar modal ──────────────────────────────────
    const modalEmpCal = document.getElementById('modal-emp-calendar');
    let empCalId = null, empCalYear, empCalMonth, empCalData = null;

    // Leave modal
    const modalLeave  = document.getElementById('modal-leave');
    const leaveTitle  = document.getElementById('leave-modal-title');
    const leaveType   = document.getElementById('leave-type');
    const leaveStart  = document.getElementById('leave-start');
    const leaveEnd    = document.getElementById('leave-end');
    const leaveNote   = document.getElementById('leave-note');
    const leaveDelete = document.getElementById('leave-delete');
    const leaveCancel = document.getElementById('leave-cancel');
    const leaveSave   = document.getElementById('leave-save');
    let activeLeaveId = null;

    leaveCancel.addEventListener('click', () => modalLeave.close());
    leaveDelete.addEventListener('click', async () => {
      if (!activeLeaveId) return;
      await fetch(`/api/employees/${empCalId}/leaves/${activeLeaveId}/`, {
        method: 'DELETE', headers: { ...authHeaders(), 'X-CSRFToken': getCsrfToken() },
      });
      modalLeave.close();
      loadEmpCalendar(empCalId, empCalYear, empCalMonth);
    });
    leaveSave.addEventListener('click', async () => {
      const type = leaveType.value;
      const start = leaveStart.value;
      const end   = leaveEnd.value || start;
      const note  = leaveNote.value.trim();
      if (!start) { leaveStart.focus(); return; }
      await fetch(`/api/employees/${empCalId}/leaves/`, {
        method: 'POST',
        headers: { ...authHeaders(), 'Content-Type': 'application/json', 'X-CSRFToken': getCsrfToken() },
        body: JSON.stringify({ leave_type: type, start_date: start, end_date: end, note }),
      });
      modalLeave.close();
      loadEmpCalendar(empCalId, empCalYear, empCalMonth);
    });

    async function loadEmpCalendar(empId, year, month) {
      empCalYear = year; empCalMonth = month;
      document.getElementById('emp-cal-month-label').textContent =
        `${EXEC_MONTH_NAMES[month-1]} ${year}`;

      const resp = await fetch(`/api/employees/${empId}/monthly/?year=${year}&month=${month}`, { headers: authHeaders() });
      if (!resp.ok) return;
      empCalData = await resp.json();

      document.getElementById('emp-cal-grid').innerHTML =
        buildCalGrid(empCalData, year, month, true);

      // Store leave ids in cells
      const leaves = empCalData.leaves || {};
      Object.entries(leaves).forEach(([day, lv]) => {
        const cell = document.querySelector(`#emp-cal-grid .cal-day[data-day="${day}"]`);
        if (cell) cell.dataset.leaveId = lv.id;
      });

      // Week stat
      const today = new Date();
      const todayY = today.getFullYear(), todayM = today.getMonth()+1, todayD = today.getDate();
      const weekStat  = document.getElementById('emp-cal-week-stat');
      const weekTotal = document.getElementById('emp-cal-week-total');
      const weekDays  = document.getElementById('emp-cal-week-days');
      if (year===todayY && month===todayM) {
        const monday = todayD - ((today.getDay()+6)%7);
        let wh2=0, dw=0;
        for (let d=monday; d<=todayD; d++) { const h=empCalData.days[String(d)]||0; wh2+=h; if(h>0)dw++; }
        const wh=Math.floor(wh2), wm=Math.round((wh2-wh)*60);
        weekTotal.textContent = wm>0 ? `${wh} h ${wm} min` : `${wh} h`;
        weekDays.textContent  = `· ${dw} día${dw!==1?'s':''} trabajado${dw!==1?'s':''}`;
        weekStat.style.display = 'block';
      } else {
        weekStat.style.display = 'none';
      }
    }

    // Click on employee calendar cell → open leave modal
    document.getElementById('emp-cal-grid').addEventListener('click', function(e) {
      const cell = e.target.closest('.cal-day[data-day]');
      if (!cell) return;
      const d = parseInt(cell.dataset.day);
      const dateStr = toIso(empCalYear, empCalMonth, d);
      const existingLeaveId = cell.dataset.leaveId || null;
      const leave = empCalData && empCalData.leaves ? empCalData.leaves[String(d)] : null;

      leaveTitle.textContent = `${d} de ${EXEC_MONTH_NAMES[empCalMonth-1]} ${empCalYear}`;
      leaveType.value  = leave ? leave.type  : 'vacacion';
      leaveStart.value = dateStr;
      leaveEnd.value   = dateStr;
      leaveNote.value  = leave ? (leave.note || '') : '';
      activeLeaveId    = existingLeaveId;
      leaveDelete.style.display = existingLeaveId ? 'block' : 'none';
      modalLeave.showModal();
    });

    document.getElementById('emp-cal-prev').addEventListener('click', function() {
      let y=empCalYear, m=empCalMonth-1; if(m<1){m=12;y--;} loadEmpCalendar(empCalId,y,m);
    });
    document.getElementById('emp-cal-next').addEventListener('click', function() {
      let y=empCalYear, m=empCalMonth+1; if(m>12){m=1;y++;} loadEmpCalendar(empCalId,y,m);
    });
    document.getElementById('emp-cal-close').addEventListener('click', function() {
      modalEmpCal.close();
    });

    document.getElementById('employee-tbody').addEventListener('click', function(e) {
      const btn = e.target.closest('.btn-emp-cal');
      if (!btn) return;
      empCalId = btn.dataset.id;
      document.getElementById('emp-cal-name').textContent = btn.dataset.name;
      const n = new Date();
      loadEmpCalendar(empCalId, n.getFullYear(), n.getMonth()+1);
      modalEmpCal.showModal();
    });

    // Init
    const _now = new Date();
    loadExecCalendarFull(_now.getFullYear(), _now.getMonth()+1);
    loadOverview();
    let poller = setInterval(loadOverview, REFRESH_INTERVAL);

    document.addEventListener('visibilitychange', () => {
      if (document.hidden) { clearInterval(poller); }
      else { loadOverview(); poller = setInterval(loadOverview, REFRESH_INTERVAL); }
    });
  }

  init();
})();
