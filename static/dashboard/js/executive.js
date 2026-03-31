(() => {
  const access = localStorage.getItem('access');
  if (!access) { window.location.href = '/login/'; return; }

  const REFRESH_INTERVAL = 30 * 1000; // 30 segundos

  function authHeaders() {
    return {
      'Authorization': `Bearer ${localStorage.getItem('access')}`,
      'Content-Type': 'application/json',
    };
  }

  function logout() {
    localStorage.removeItem('access');
    localStorage.removeItem('refresh');
    window.location.href = '/login/';
  }

  function formatTime(iso) {
    return new Date(iso).toLocaleTimeString('es-BO', { hour: '2-digit', minute: '2-digit' });
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

  async function loadProfile() {
    const resp = await fetch('/api/auth/me/', { headers: authHeaders() });
    if (resp.status === 401) { logout(); return; }
    const data = await resp.json();
    if (!data.is_executive) { window.location.href = '/dashboard/'; return; }
  }

  function renderRow(emp) {
    const workday = emp.workday;
    const isActive = workday?.active;
    const agentOn = emp.agent_is_active;

    const workdayBadge = isActive
      ? `<span class="badge-active"><span class="dot-online" style="animation:pulse 2s infinite"></span>Activa</span>`
      : `<span class="badge-inactive">Sin jornada</span>`;

    const version = emp.agent_version
      ? ` <span style="color:rgba(255,255,255,0.30);font-family:monospace;font-size:0.72rem">— ${emp.agent_version}</span>`
      : '';
    const agentDot = agentOn
      ? `<span class="agent-online"><span class="dot-online"></span>Online${version}</span>`
      : `<span class="agent-offline"><span class="dot-offline"></span>Offline${version}</span>`;

    const interval = emp.capture_interval_minutes != null
      ? `<span style="color:rgba(255,255,255,0.50);font-size:0.82rem">${emp.capture_interval_minutes} min</span>`
      : `<span style="color:rgba(255,255,255,0.18)">—</span>`;

    const captureBtn = agentOn
      ? `<button class="btn-capture btn-capture-ios" data-id="${emp.id}" title="Capturar pantalla ahora">
           <svg xmlns="http://www.w3.org/2000/svg" width="15" height="15" fill="none" viewBox="0 0 24 24" stroke="currentColor" class="pointer-events-none">
             <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M3 9a2 2 0 012-2h.93a2 2 0 001.664-.89l.812-1.22A2 2 0 0110.07 4h3.86a2 2 0 011.664.89l.812 1.22A2 2 0 0018.07 7H19a2 2 0 012 2v9a2 2 0 01-2 2H5a2 2 0 01-2-2V9z"/>
             <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M15 13a3 3 0 11-6 0 3 3 0 016 0z"/>
           </svg>
         </button>`
      : '';

    const checked = emp.screenshots_enabled ? 'checked' : '';
    const skylogChecked = emp.skylog_access ? 'checked' : '';
    const disabled = !emp.skylog_access;
    const rowStyle = disabled ? 'opacity:0.35;pointer-events:none' : '';
    const ssDisabled = disabled ? 'disabled' : '';

    return `<tr style="${disabled ? 'background:rgba(0,0,0,0.15)' : ''}">
      <td style="${rowStyle}">
        <div style="display:flex;align-items:center;gap:10px">
          <div class="avatar-circle">${initials(emp.full_name)}</div>
          <span style="font-weight:500;font-size:0.875rem">${emp.full_name}</span>
        </div>
      </td>
      <td style="${rowStyle}">${disabled ? '<span style="color:rgba(255,255,255,0.15)">—</span>' : workdayBadge}</td>
      <td style="color:rgba(255,255,255,0.45);font-size:0.82rem;${rowStyle}">${disabled ? '' : (isActive ? formatTime(workday.start_time) : '—')}</td>
      <td style="font-size:0.82rem;${rowStyle}">
        ${disabled ? '' : `<span style="color:rgba(255,255,255,0.45)">${isActive ? formatDuration(workday.duration_minutes) : '—'}</span>
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
    </tr>`;
  }

  async function loadOverview() {
    try {
      const resp = await fetch('/api/employees/overview/', { headers: authHeaders() });
      if (resp.status === 401) { logout(); return; }
      if (resp.status === 403) { window.location.href = '/dashboard/'; return; }
      const data = await resp.json();

      // Summary
      document.getElementById('stat-active').textContent = data.summary.active_now;
      document.getElementById('stat-completed').textContent = data.summary.completed_today;
      document.getElementById('stat-agents').textContent = data.summary.agents_online;
      document.getElementById('stat-total').textContent = data.summary.total_employees;

      // Table
      document.getElementById('table-loading').classList.add('hidden');
      if (data.employees.length === 0) {
        document.getElementById('table-empty').classList.remove('hidden');
      } else {
        const tbody = document.getElementById('employee-tbody');
        tbody.innerHTML = data.employees.map(renderRow).join('');
        document.getElementById('table-container').classList.remove('hidden');
        document.getElementById('table-empty').classList.add('hidden');
      }

      // Timestamp
      const ts = new Date().toLocaleTimeString('es-BO', { hour: '2-digit', minute: '2-digit', second: '2-digit' });
      document.getElementById('last-updated').textContent = `Actualizado a las ${ts}`;
    } catch (e) {
      // Error de red — silencioso, se reintenta en el próximo ciclo
    }
  }

  document.getElementById('btn-logout').addEventListener('click', logout);

  // Captura inmediata — delegación en tbody
  document.getElementById('employee-tbody').addEventListener('click', async (e) => {
    const btn = e.target.closest('.btn-capture');
    if (!btn) return;
    const employeeId = btn.dataset.id;
    btn.disabled = true;
    try {
      await fetch(`/api/employees/${employeeId}/capture/`, {
        method: 'POST',
        headers: authHeaders(),
      });
    } finally {
      setTimeout(() => { btn.disabled = false; }, 3000);
    }
  });

  // Toggle Skylog — delegación en tbody
  const modalSkylogOff = document.getElementById('modal-skylog-off');
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
    } catch (_) {
      toggle.checked = !on;
    } finally {
      toggle.disabled = false;
    }
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

  btnSkylogCancel.addEventListener('click', () => {
    pendingSkylogToggle = null;
    modalSkylogOff.close();
  });

  btnSkylogConfirm.addEventListener('click', async () => {
    modalSkylogOff.close();
    if (!pendingSkylogToggle) return;
    const t = pendingSkylogToggle;
    pendingSkylogToggle = null;
    t.checked = false;
    await applySkylogToggle(t, false);
  });

  // Toggle capturas — delegación en tbody
  const modalSsOff = document.getElementById('modal-ss-off');
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
    } catch (_) {
      toggle.checked = !on;
    } finally {
      toggle.disabled = false;
    }
  }

  document.getElementById('employee-tbody').addEventListener('change', (e) => {
    const toggle = e.target.closest('.ss-toggle');
    if (!toggle) return;
    if (!toggle.checked) {
      // Apagando — pedir confirmación
      toggle.checked = true; // revertir visualmente hasta confirmar
      pendingToggle = toggle;
      modalSsOff.showModal();
    } else {
      const intervalCell = toggle.closest('tr')?.querySelector('.interval-cell');
      if (intervalCell && intervalCell.dataset.prev) intervalCell.innerHTML = intervalCell.dataset.prev;
      applyScreenshotsToggle(toggle, true);
    }
  });

  btnSsCancel.addEventListener('click', () => {
    pendingToggle = null;
    modalSsOff.close();
  });

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

  // Init
  loadProfile();
  loadOverview();

  let poller = setInterval(loadOverview, REFRESH_INTERVAL);

  // Pausar polling cuando la pestaña no está visible
  document.addEventListener('visibilitychange', () => {
    if (document.hidden) {
      clearInterval(poller);
    } else {
      loadOverview(); // actualizar al volver
      poller = setInterval(loadOverview, REFRESH_INTERVAL);
    }
  });
})();
