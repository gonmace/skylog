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

  const ALL_VIEWS = ['view-loading', 'view-pin', 'view-noaccess', 'view-executive'];

  function showView(id) {
    ALL_VIEWS.forEach(v => {
      document.getElementById(v).classList.toggle('hidden', v !== id);
    });
  }

  // ─────────────────────────────────────────────────────────────
  //  PIN lock
  // ─────────────────────────────────────────────────────────────
  const PIN_CODES = ['2231', '1458', '1209'];
  let _pinBuffer = '';
  let _pinCallback = null;

  const PIN_TTL = 60 * 60 * 1000; // 1 hora

  function initPin(onSuccess) {
    const last = parseInt(localStorage.getItem('pin_unlocked_at') || '0', 10);
    if (last && (Date.now() - last) < PIN_TTL) { onSuccess(); return; }

    _pinCallback = onSuccess;
    _pinBuffer = '';
    _updateDots();
    document.getElementById('pin-error').textContent = '';
    showView('view-pin');

    document.querySelectorAll('.pin-key[data-digit]').forEach(btn => {
      btn.addEventListener('click', () => _pinPress(btn.dataset.digit));
    });
    document.getElementById('pin-del').addEventListener('click', _pinBackspace);
    document.addEventListener('keydown', _pinKeydown);
  }

  function _pinKeydown(e) {
    if (e.key >= '0' && e.key <= '9') _pinPress(e.key);
    else if (e.key === 'Backspace') _pinBackspace();
  }

  function _pinPress(digit) {
    if (_pinBuffer.length >= 4) return;
    _pinBuffer += digit;
    _updateDots();
    if (_pinBuffer.length === 4) _checkPin();
  }

  function _pinBackspace() {
    _pinBuffer = _pinBuffer.slice(0, -1);
    _updateDots();
    document.getElementById('pin-error').textContent = '';
    document.querySelectorAll('.pin-dot').forEach(d => d.classList.remove('error'));
  }

  function _updateDots() {
    for (let i = 0; i < 4; i++) {
      const dot = document.getElementById('pd' + i);
      dot.classList.toggle('filled', i < _pinBuffer.length);
    }
  }

  function _checkPin() {
    if (PIN_CODES.includes(_pinBuffer)) {
      localStorage.setItem('pin_unlocked_at', Date.now().toString());
      document.removeEventListener('keydown', _pinKeydown);
      _pinCallback();
    } else {
      document.querySelectorAll('.pin-dot').forEach(d => { d.classList.remove('filled'); d.classList.add('error'); });
      document.getElementById('pin-error').textContent = 'Clave incorrecta, intenta de nuevo';
      setTimeout(() => {
        document.querySelectorAll('.pin-dot').forEach(d => d.classList.remove('error'));
        document.getElementById('pin-error').textContent = '';
        _pinBuffer = '';
        _updateDots();
      }, 900);
    }
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
      if (!profile.is_executive) { window.location.href = '/dashboard/employee/'; return; }
      if (profile.skylog_access === false) { showView('view-noaccess'); initNoAccess(); return; }
      initPin(() => { showView('view-executive'); initExecutive(profile); });
    } catch (e) {}
  }

  // ─────────────────────────────────────────────────────────────
  //  No Access
  // ─────────────────────────────────────────────────────────────
  function initNoAccess() {
    document.getElementById('noaccess-btn-logout').addEventListener('click', logout);
  }

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

  // ─────────────────────────────────────────────────────────────
  //  Mensaje a Sup/PM (botón habilitado por can_message_leads)
  // ─────────────────────────────────────────────────────────────
  function initLeadsModal() {
    const openBtn  = document.getElementById('exec-btn-leads');
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

  // ─────────────────────────────────────────────────────────────
  //  Executive
  // ─────────────────────────────────────────────────────────────
  function initExecutive(profile) {
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
      return parts.length >= 2 ? parts[0][0] + parts[1][0] : parts[0].slice(0, 2);
    }

    function avatarColorIdx(name) {
      let h = 0;
      for (let i = 0; i < (name || '?').length; i++) h = (h * 31 + (name || '?').charCodeAt(i)) & 0xffff;
      return h % 10;
    }

    function renderRow(emp) {
      const workday     = emp.workday;
      const isActive    = workday?.active;
      const autoClosed  = workday?.auto_closed;
      // Auto-cerrada (sin finalizar) NO cuenta como "completada": se muestra en rojo.
      const isCompleted = !isActive && workday?.completed && !autoClosed;
      const agentOn     = emp.agent_is_active;
      const workdayBadge = isActive
        ? `<span class="badge-active"><span class="dot-online" style="animation:pulse 2s infinite;background:var(--cp-orange);box-shadow:0 0 6px color-mix(in srgb,var(--cp-orange) 70%,transparent)"></span>Activa</span>`
        : isCompleted
          ? `<span class="badge-inactive" style="background:color-mix(in srgb,var(--cp-green,#34c759) 12%,transparent);color:var(--cp-green,#34c759);border-color:color-mix(in srgb,var(--cp-green,#34c759) 30%,transparent);cursor:default">
               <svg xmlns='http://www.w3.org/2000/svg' width='10' height='10' fill='none' viewBox='0 0 24 24' stroke='currentColor' stroke-width='2.5' style='display:inline;margin-right:3px;vertical-align:middle'><path stroke-linecap='round' stroke-linejoin='round' d='M5 13l4 4L19 7'/></svg>Completada
             </span>`
          : autoClosed
            ? `<span class="badge-inactive" style="background:color-mix(in srgb,var(--cp-red) 12%,transparent);color:var(--cp-red);border-color:color-mix(in srgb,var(--cp-red) 25%,transparent);cursor:default" title="Jornada no finalizada — cerrada automáticamente a las 17:00">
                 <svg xmlns='http://www.w3.org/2000/svg' width='10' height='10' fill='none' viewBox='0 0 24 24' stroke='currentColor' stroke-width='2.5' style='display:inline;margin-right:3px;vertical-align:middle'><path stroke-linecap='round' stroke-linejoin='round' d='M12 9v4m0 4h.01M10.29 3.86L1.82 18a2 2 0 001.71 3h16.94a2 2 0 001.71-3L13.71 3.86a2 2 0 00-3.42 0z'/></svg>Sin cerrar
               </span>`
            : `<span class="badge-inactive" style="background:color-mix(in srgb,var(--cp-red) 10%,transparent);color:color-mix(in srgb,var(--cp-red) 55%,var(--cp-text-dim));border-color:color-mix(in srgb,var(--cp-red) 18%,transparent)">Sin jornada</span>`;

      const version  = emp.agent_version
        ? `<span style="color:var(--cp-text-dim);font-family:monospace;font-size:0.7rem;display:block;margin-top:2px">${emp.agent_version}</span>`
        : '';
      const agentDot = agentOn
        ? `<span class="agent-online" style="white-space:nowrap"><span class="dot-online"></span>Online</span>${version}`
        : `<span class="agent-offline" style="white-space:nowrap"><span class="dot-offline"></span>Offline</span>${version}`;

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
            <div class="avatar-circle avatar-c-${avatarColorIdx(emp.full_name)}">${initials(emp.full_name)}</div>
            <span style="font-weight:500;font-size:0.875rem;line-height:1.3">${(emp.full_name || '').replace(/^(\S+)\s+(.+)$/, '$1<br>$2')}</span>
          </div>
        </td>
        <td style="white-space:nowrap;${rowStyle}">${disabled ? '<span style="color:var(--cp-text-dim)">—</span>' : workdayBadge}</td>
        <td style="color:${autoClosed ? 'var(--cp-red)' : 'var(--cp-text-mid)'};font-size:0.82rem;${rowStyle}">${disabled ? '' : (isActive || autoClosed || isCompleted ? formatTime(workday.start_time) : '—')}</td>
        <td style="color:${autoClosed ? 'var(--cp-red)' : isCompleted ? 'var(--cp-green,#34c759)' : 'var(--cp-text-mid)'};font-size:0.82rem;${rowStyle}">${disabled ? '' : ((isCompleted || autoClosed) ? formatTime(workday.end_time) : '—')}</td>
        <td style="font-size:0.82rem;${rowStyle}">
          ${disabled ? '' : `<span style="color:${autoClosed ? 'var(--cp-red)' : isCompleted ? 'var(--cp-green,#34c759)' : 'var(--cp-text-mid)'}">${(isActive || autoClosed || isCompleted) ? formatDuration(workday.duration_minutes) : '—'}</span>
          ${isActive && workday.inactive_minutes > 0
            ? `<br><span style="color:rgba(255,99,99,0.75);font-size:0.72rem">▾ ~${formatDuration(workday.inactive_minutes)} inactivo est.</span>`
            : ''}`}
        </td>
        <td class="interval-cell" style="${rowStyle}">${disabled || !emp.screenshots_enabled ? '' : interval}</td>
        <td style="${rowStyle}"><div style="line-height:1.2">${disabled ? '' : agentDot}</div></td>
        <td style="text-align:center;${rowStyle}">
          <label class="ios-toggle" style="${disabled ? 'pointer-events:none' : ''}">
            <input type="checkbox" data-emp-id="${emp.id}" class="ss-toggle" ${checked} ${ssDisabled}>
            <span class="ios-toggle-track"></span>
          </label>
        </td>
        <td style="text-align:center">
          <label class="ios-toggle skylog-toggle">
            <input type="checkbox" data-emp-id="${emp.id}" class="skylog-toggle-input" ${skylogChecked}>
            <span class="ios-toggle-track"></span>
          </label>
        </td>
        <td style="white-space:nowrap">
          <div style="display:inline-flex;align-items:center;gap:6px">
            <button class="btn-emp-view btn-capture-ios" data-id="${emp.id}" data-name="${emp.full_name}" title="Ver dashboard del empleado">
              <svg xmlns="http://www.w3.org/2000/svg" width="14" height="14" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2" class="pointer-events-none">
                <path stroke-linecap="round" stroke-linejoin="round" d="M15 12a3 3 0 11-6 0 3 3 0 016 0z"/>
                <path stroke-linecap="round" stroke-linejoin="round" d="M2.458 12C3.732 7.943 7.523 5 12 5c4.478 0 8.268 2.943 9.542 7-1.274 4.057-5.064 7-9.542 7-4.477 0-8.268-2.943-9.542-7z"/>
              </svg>
            </button>
            ${msgBtn}
            <button class="btn-emp-cal btn-emp-cal-icon" data-id="${emp.id}" data-name="${emp.full_name}" title="Ver calendario">
              <svg xmlns="http://www.w3.org/2000/svg" width="14" height="14" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2" class="pointer-events-none">
                <path stroke-linecap="round" stroke-linejoin="round" d="M8 7V3m8 4V3m-9 8h10M5 21h14a2 2 0 002-2V7a2 2 0 00-2-2H5a2 2 0 00-2 2v12a2 2 0 002 2z"/>
              </svg>
            </button>
            ${emp.solo_movil
              ? emp.mobile_device_bound
                ? `<button class="btn-reset-device btn-device-red" data-id="${emp.id}" data-name="${emp.full_name}" title="Desvincular dispositivo móvil">
                     <svg xmlns="http://www.w3.org/2000/svg" width="14" height="14" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2" class="pointer-events-none">
                       <path stroke-linecap="round" stroke-linejoin="round" d="M12 18h.01M8 21h8a2 2 0 002-2V5a2 2 0 00-2-2H8a2 2 0 00-2 2v14a2 2 0 002 2z"/>
                     </svg>
                   </button>`
                : `<div style="width:30px;height:30px;display:inline-flex;align-items:center;justify-content:center;border-radius:8px;border:1px solid color-mix(in srgb,var(--cp-text-dim) 20%,transparent)" title="Sin dispositivo vinculado">
                     <svg xmlns="http://www.w3.org/2000/svg" width="14" height="14" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2" style="opacity:0.25"><path stroke-linecap="round" stroke-linejoin="round" d="M12 18h.01M8 21h8a2 2 0 002-2V5a2 2 0 00-2-2H8a2 2 0 00-2 2v14a2 2 0 002 2z"/></svg>
                   </div>`
              : ''}
            ${captureBtn}
          </div>
        </td>
        <td class="report-cell" style="font-size:0.78rem;color:var(--cp-text-mid)">${isCompleted && workday.activities_done ? workday.activities_done : '<span style="color:var(--cp-text-dim)">—</span>'}</td>
        <td class="report-cell" style="font-size:0.78rem;color:var(--cp-text-mid)">${isCompleted && workday.activities_planned ? workday.activities_planned : '<span style="color:var(--cp-text-dim)">—</span>'}</td>
        <td class="report-cell" style="font-size:0.78rem;white-space:normal">${
          emp.messages && emp.messages.length
            ? emp.messages.map(m =>
                `<span style="color:${m.acknowledged ? 'var(--cp-text-dim)' : 'var(--cp-accent,#f59e0b)'}">${m.body}</span>`
              ).join('<br>')
            : '<span style="color:var(--cp-text-dim)">—</span>'
        }</td>
      </tr>`;
    }

    // Date picker setup
    const datePicker = document.getElementById('exec-date-picker');
    const btnToday   = document.getElementById('exec-btn-today');
    const btnPrev    = document.getElementById('exec-btn-prev');
    const btnNext    = document.getElementById('exec-btn-next');
    const dayLabel   = document.getElementById('exec-day-label');
    const todayStr   = new Date().toLocaleDateString('sv'); // YYYY-MM-DD
    datePicker.value = todayStr;
    datePicker.max   = todayStr;

    const DAYS = ['Domingo','Lunes','Martes','Miércoles','Jueves','Viernes','Sábado'];
    function updateDayLabel() {
      const d = new Date(datePicker.value + 'T00:00:00');
      const isToday = datePicker.value === todayStr;
      dayLabel.textContent = isToday ? 'Hoy — ' + DAYS[d.getDay()] : DAYS[d.getDay()];
    }

    function getSelectedDate() { return datePicker.value || todayStr; }

    function updateNavState() {
      const isToday = datePicker.value === todayStr;
      btnToday.style.display = isToday ? 'none' : '';
      btnNext.style.opacity  = isToday ? '0.3' : '1';
      btnNext.style.pointerEvents = isToday ? 'none' : '';
      updateDayLabel();
    }

    function shiftDate(days) {
      const d = new Date(datePicker.value + 'T00:00:00');
      d.setDate(d.getDate() + days);
      const shifted = d.toLocaleDateString('sv');
      if (shifted > todayStr) return;
      datePicker.value = shifted;
      updateNavState();
      loadOverview();
    }

    datePicker.addEventListener('change', () => { updateNavState(); loadOverview(); });
    btnToday.addEventListener('click', () => { datePicker.value = todayStr; updateNavState(); loadOverview(); });
    btnPrev.addEventListener('click',  () => shiftDate(-1));
    btnNext.addEventListener('click',  () => shiftDate(+1));
    updateNavState();

    let lastOverviewData = null;

    async function loadOverview() {
      const date = getSelectedDate();
      const isToday = date === todayStr;
      try {
        const resp = await fetch(`/api/employees/overview/?date=${date}`, { headers: authHeaders() });
        if (resp.status === 401) { logout(); return; }
        if (resp.status === 403) { init(); return; }
        const data = await resp.json();
        lastOverviewData = data;

        document.getElementById('stat-active').textContent    = isToday ? data.summary.active_now : '—';
        document.getElementById('stat-completed').textContent = data.summary.completed_today;
        document.getElementById('stat-agents').textContent    = isToday ? data.summary.agents_online : '—';
        document.getElementById('stat-total').textContent     = data.summary.total_employees;
        document.getElementById('stat-activities').textContent = data.summary.activities;

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

    // Botones superiores según permisos del usuario (superuser conserva su acceso;
    // los flags granulares habilitan a usuarios puntuales).
    const _showIf = (id, cond) => { const el = document.getElementById(id); if (el && cond) el.style.display = ''; };
    _showIf('exec-link-stats',    profile && (profile.is_superuser || profile.can_view_stats));
    _showIf('exec-link-tags',     profile && (profile.is_superuser || profile.can_edit_tags));
    _showIf('exec-btn-leads',     profile && (profile.is_executive || profile.can_message_leads));
    _showIf('exec-link-visits',   profile && (profile.is_superuser || profile.can_manage_visits));
    _showIf('exec-link-permisos', profile && profile.is_superuser);

    if (profile && profile.is_superuser) {
      const statsCard = document.getElementById('exec-card-stats');
      if (statsCard) {
        statsCard.classList.add('cursor-pointer', 'group', 'transition', 'hover:shadow-lg', 'hover:-translate-y-0.5');
        statsCard.addEventListener('click', () => { window.location.href = '/estadisticas/'; });
      }
    }

    if (profile && (profile.is_executive || profile.can_message_leads)) initLeadsModal();

    // Iniciales del usuario logueado
    if (profile && profile.full_name) {
      const userAvatar = document.getElementById('exec-user-avatar');
      userAvatar.textContent = initials(profile.full_name);
      userAvatar.classList.add(`avatar-c-${avatarColorIdx(profile.full_name)}`);
      userAvatar.title = profile.full_name;
      userAvatar.style.display = '';
    }

    // Report cell tooltip
    const tooltip = document.getElementById('report-tooltip');
    let tooltipTimeout;
    document.getElementById('employee-tbody').addEventListener('mouseover', (e) => {
      const cell = e.target.closest('.report-cell');
      if (!cell || cell.textContent.trim() === '—') return;
      clearTimeout(tooltipTimeout);
      tooltip.textContent = cell.textContent;
      tooltip.classList.add('visible');
    });
    document.getElementById('employee-tbody').addEventListener('mousemove', (e) => {
      const cell = e.target.closest('.report-cell');
      if (!cell) return;
      const x = e.clientX + 14;
      const y = e.clientY + 14;
      tooltip.style.left = (x + tooltip.offsetWidth > window.innerWidth ? e.clientX - tooltip.offsetWidth - 10 : x) + 'px';
      tooltip.style.top  = (y + tooltip.offsetHeight > window.innerHeight ? e.clientY - tooltip.offsetHeight - 10 : y) + 'px';
    });
    document.getElementById('employee-tbody').addEventListener('mouseout', (e) => {
      const cell = e.target.closest('.report-cell');
      if (!cell) return;
      tooltipTimeout = setTimeout(() => tooltip.classList.remove('visible'), 100);
    });

    // Capture button — event delegation
    document.getElementById('employee-tbody').addEventListener('click', async (e) => {
      const resetBtn = e.target.closest('.btn-reset-device');
      if (resetBtn) {
        const name = resetBtn.dataset.name;
        if (!confirm(`¿Desvincular el dispositivo de ${name}? El próximo login desde cualquier dispositivo quedará vinculado.`)) return;
        const origHTML = resetBtn.innerHTML;
        resetBtn.disabled = true;
        try {
          const resp = await fetch(`/api/employees/${resetBtn.dataset.id}/reset-device/`, {
            method: 'POST',
            headers: { ...authHeaders(), 'X-CSRFToken': getCsrfToken() },
          });
          if (resp.ok) await loadOverview();
        } finally {
          resetBtn.innerHTML = origHTML;
          resetBtn.disabled = false;
        }
        return;
      }
    });

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
    const LEAVE_LABELS = { vacacion: 'Vacación', licencia: 'Licencia', permiso: 'Permiso', otro: 'Otro' };

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
      const times  = data.times  || {};

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

        const tm = times[String(d)];
        const tmLabel = tm ? `Ingreso ${tm.start}${tm.end ? ` · Salida ${tm.end}` : ''}` : '';
        const timeLabel = (!leave && tm && tm.start)
          ? `<span class="cal-day-time">${tm.start}${tm.end ? `–${tm.end}` : ''}</span>`
          : '';
        let tip = '';
        if (leave && leave.note) tip = ` title="${LEAVE_LABELS[leave.type]}: ${leave.note}"`;
        else if (leave) tip = ` title="${LEAVE_LABELS[leave.type]}"`;
        else if (isClosed) tip = ` title="${tmLabel ? tmLabel + ' — ' : ''}Cerrada automáticamente a las 17:00"`;
        else if (note) tip = ` title="${note.text}"`;
        else if (tmLabel) tip = ` title="${tmLabel}"`;

        html += `<div class="${cls}" data-day="${d}"${tip}>
          <span class="cal-day-num">${d}</span>${hrsLabel}${timeLabel}
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
    const wdFields    = document.getElementById('wd-fields');
    const wdEmpty     = document.getElementById('wd-empty');
    const wdStart     = document.getElementById('wd-start');
    const wdEnd       = document.getElementById('wd-end');
    const wdSave      = document.getElementById('wd-save');
    let activeLeaveId = null;
    let activeCalDate = null;

    // La nota es obligatoria cuando el tipo es "Otro"
    leaveType.addEventListener('change', () => {
      leaveNote.placeholder = leaveType.value === 'otro' ? 'Nota (obligatoria)' : 'Nota opcional';
    });

    // Solo el superuser puede editar el horario de la jornada
    wdSave.addEventListener('click', async () => {
      if (!activeCalDate) return;
      const start = wdStart.value, end = wdEnd.value;
      if (!start || !end) return;
      const resp = await fetch(`/api/employees/${empCalId}/workday-times/`, {
        method: 'POST',
        headers: { ...authHeaders(), 'Content-Type': 'application/json', 'X-CSRFToken': getCsrfToken() },
        body: JSON.stringify({ date: activeCalDate, start, end }),
      });
      if (!resp.ok) {
        const err = await resp.json().catch(() => ({}));
        alert(err.error || 'No se pudo guardar el horario');
        return;
      }
      modalLeave.close();
      loadEmpCalendar(empCalId, empCalYear, empCalMonth);
    });

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
      if (type === 'otro' && !note) { leaveNote.focus(); return; }
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
      leaveNote.placeholder = leaveType.value === 'otro' ? 'Nota (obligatoria)' : 'Nota opcional';
      activeLeaveId    = existingLeaveId;
      leaveDelete.style.display = existingLeaveId ? 'block' : 'none';

      // Sección Horario: muestra ingreso/salida; editable solo para superuser
      activeCalDate = dateStr;
      const tm = empCalData && empCalData.times ? empCalData.times[String(d)] : null;
      const isSuper = !!(profile && profile.is_superuser);
      if (tm) {
        wdStart.value = tm.start || '';
        wdEnd.value   = tm.end || '';
        wdFields.style.display = 'flex';
        wdEmpty.style.display  = 'none';
        wdStart.disabled = wdEnd.disabled = !isSuper;
        wdSave.style.display = isSuper ? 'inline-flex' : 'none';
      } else {
        wdFields.style.display = 'none';
        wdEmpty.style.display  = 'block';
      }

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

    // Modal vista de empleado (iframe)
    const modalEmpView = document.getElementById('modal-emp-view');

    document.getElementById('employee-tbody').addEventListener('click', function(e) {
      const btn = e.target.closest('.btn-emp-view');
      if (!btn) return;
      const empId   = btn.dataset.id;
      const empName = btn.dataset.name;

      const empviewAvatar = document.getElementById('empview-avatar');
      empviewAvatar.textContent = initials(empName);
      for (let i = 0; i < 10; i++) empviewAvatar.classList.remove(`avatar-c-${i}`);
      empviewAvatar.classList.add(`avatar-c-${avatarColorIdx(empName)}`);
      document.getElementById('empview-name').textContent   = empName;
      document.getElementById('empview-iframe').src = `/dashboard/employee/?view_as=${empId}`;
      modalEmpView.showModal();
    });

    // Init
    const _now = new Date();
    loadExecCalendarFull(_now.getFullYear(), _now.getMonth()+1);
    loadOverview();
    let poller = setInterval(() => { if (getSelectedDate() === todayStr) loadOverview(); }, REFRESH_INTERVAL);

    document.addEventListener('visibilitychange', () => {
      if (document.hidden) { clearInterval(poller); }
      else { loadOverview(); poller = setInterval(() => { if (getSelectedDate() === todayStr) loadOverview(); }, REFRESH_INTERVAL); }
    });
  }

  init();
})();
