/* Estadísticas — funciones de render compartidas por la página /estadisticas/
   y el panel personal del dashboard. Requiere ApexCharts y los IDs es-*. */
var _charts = {};
var _chartHeights = {};  // última altura por gráfico (para recrear si cambia)

// Paleta categórica fija — 11 colores distintos legibles en tema oscuro.
// (un gráfico multi-serie necesita más hues distintos que los del tema).
var CAT_COLOR = {
  riesgos:'#ef4444', reuniones:'#38bdf8', cronogramas:'#f59e0b',
  actas:'#2dd4bf', pliegos:'#a78bfa', diseno:'#6366f1',
  supervision:'#34d399', informes:'#fb7185', seguimiento:'#94a3b8',
  gestion_doc:'#c084fc', otros:'#64748b',
};
// Colores dinámicos provistos por la API (data.category_colors) — incluyen las
// categorías nuevas creadas desde el admin. Se priorizan sobre CAT_COLOR.
var CAT_COLOR_RT = {};
function applyCatColors(data){ if (data && data.category_colors) CAT_COLOR_RT = data.category_colors; }
function tok(name){ return getComputedStyle(document.documentElement).getPropertyValue(name).trim() || '#888'; }
function catColor(code){ return CAT_COLOR_RT[code] || CAT_COLOR[code] || '#64748b'; }
// Color del empleado seleccionado en los gráficos de comparación: naranja vivo,
// distinto del verde (Sup) y el azul (PM) de los promedios.
var EMP_COLOR = '#f97316';

function _escTag(s) {
  return String(s == null ? '' : s).replace(/[&<>"]/g, function (c) {
    return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c];
  });
}

// Lista rankeada con barra proporcional (proyectos / ubicaciones / entregables).
function renderTagList(containerId, items) {
  var el = document.getElementById(containerId);
  if (!el) return;
  if (!items || !items.length) {
    el.innerHTML = '<p class="text-xs text-base-content/40 py-4 text-center">Sin datos</p>';
    return;
  }
  var max = items[0].count || 1;
  el.innerHTML = items.map(function (t) {
    var bar;
    if (t.segments && t.segments.length) {
      // barra apilada por sede (cada segmento con su color)
      bar = '<div class="es-tagbar es-tagbar-stack">' + t.segments.map(function (s) {
        var w = Math.max(1, Math.round(100 * s.count / max));
        return '<div class="es-tagseg" title="' + _escTag(s.name) + ': ' + s.count
          + '" style="width:' + w + '%' + (s.color ? ';background:' + s.color : '') + '"></div>';
      }).join('') + '</div>';
    } else {
      var pct = Math.max(3, Math.round(100 * t.count / max));
      var fill = 'width:' + pct + '%' + (t.color ? ';background:' + t.color : '');
      bar = '<div class="es-tagbar"><div class="es-tagbar-fill" style="' + fill + '"></div></div>';
    }
    var tot = (t.total != null && t.total !== t.count)
      ? ' <span class="es-tagtot">/ ' + t.total + '</span>' : '';
    return '<div class="es-tagrow">'
      + '<div class="es-taghead">'
      +   '<span class="es-tagname" title="' + _escTag(t.name) + '">' + _escTag(t.name) + '</span>'
      +   '<span class="es-tagcount">' + t.count + tot + '</span>'
      + '</div>'
      + bar
      + '</div>';
  }).join('');
}

// Parte un nombre largo en hasta 2 líneas (corte por palabra cerca de la mitad).
// Devuelve un array → ApexCharts lo renderiza multilínea en el eje.
function _wrapTagLabel(name, maxChars) {
  maxChars = maxChars || 22;
  if (name.length <= maxChars) return [name];
  var words = name.split(' '), l1 = '', l2 = '';
  words.forEach(function (w) {
    if (!l1 || (!l2 && (l1.length + 1 + w.length) <= maxChars)) {
      l1 = l1 ? (l1 + ' ' + w) : w;
    } else {
      l2 = l2 ? (l2 + ' ' + w) : w;
    }
  });
  if (!l2) { l1 = name.slice(0, maxChars); l2 = name.slice(maxChars); }   // palabra única muy larga
  return [l1, l2];
}

// Gráfico de barras horizontales (ApexCharts) para un breakdown de tags.
//  · Si los items traen `segments` (composición por sede) → barras apiladas por sede.
//  · Si traen `total` (denominador empleado/rol) → muestra "count / total" al final.
//  · opts.showCode → nombres en 2 líneas (si no entran); el código va solo en el tooltip.
function renderTagChart(key, containerId, items, opts) {
  opts = opts || {};
  var el = document.getElementById(containerId);
  if (!el) return;
  if (!items || !items.length) {
    if (_charts[key]) { try { _charts[key].destroy(); } catch (e) {} _charts[key] = null; }
    _chartHeights[key] = null;
    el.innerHTML = '<p class="text-xs text-base-content/40 py-4 text-center">Sin datos</p>';
    return;
  }
  if (!_charts[key]) el.innerHTML = '';   // limpiar el "Sin datos" antes de crear el chart

  var cats   = items.map(function(t){ return t.name; });
  var totals = items.map(function(t){ return (t.total != null) ? t.total : null; });
  var hasSeg = items.some(function(t){ return t.segments && t.segments.length; });

  var series, colors, distributed = false;
  if (hasSeg) {
    var sedes = [], sColor = {};
    items.forEach(function(t){ (t.segments || []).forEach(function(s){
      if (sedes.indexOf(s.name) < 0) { sedes.push(s.name); sColor[s.name] = s.color || '#888'; }
    }); });
    series = sedes.map(function(sd){ return { name: sd, data: items.map(function(t){
      var seg = (t.segments || []).filter(function(x){ return x.name === sd; })[0];
      return seg ? seg.count : 0;
    }) }; });
    colors = sedes.map(function(sd){ return sColor[sd]; });
  } else {
    series = [{ name: 'Actividades', data: items.map(function(t){ return t.count; }) }];
    colors = items.map(function(t){ return t.color || '#64748b'; });
    distributed = true;
  }

  var labelFmt = function(val, o){
    var i = o && o.dataPointIndex;
    var t = (i != null) ? totals[i] : null;
    return (t != null) ? (val + ' / ' + t) : ('' + val);
  };
  var labelStyle = { fontSize: '11.5px', fontWeight: 800, colors: [_axisCat()] };
  // El label de TOTAL de barras apiladas usa `color` (singular), no `colors` (array).
  var totalStyle = { fontSize: '12px', fontWeight: 800, color: _axisCat() };
  var labelShadow = { enabled: true, top: 0, left: 0, blur: 2, color: '#000', opacity: 0.55 };
  // Nombres en hasta 2 líneas → un poco más de alto por fila. El código solo va en el tooltip.
  var codeByName = {};
  if (opts.showCode) items.forEach(function (t) { if (t.code) codeByName[t.name] = t.code; });
  var h = Math.max(150, cats.length * (opts.showCode ? 40 : 32) + 44);

  // Etiquetas del eje Y: solo en proyecto (showCode) partimos el nombre en 2 líneas y
  // recentramos con offsetY. Importante: NO setear claves en `undefined` (ApexCharts las
  // mergea sobre sus defaults y rompe, p. ej. tooltip.x.formatter).
  var yLabels = { style: { colors: _axisCat(), fontSize: '12px', fontWeight: 600 } };
  if (opts.showCode) {
    yLabels.maxWidth = 230;
    yLabels.offsetY = 6;
    yLabels.formatter = function (v) { return _wrapTagLabel(String(v), 22); };
  }
  // El código del proyecto solo se muestra al pasar el mouse, como título del tooltip.
  var tooltipOpts = { theme: 'dark', shared: hasSeg, intersect: false };
  if (opts.showCode) {
    tooltipOpts.x = { formatter: function (v) {
      return codeByName[v] ? (v + ' · ' + codeByName[v]) : v;
    } };
  }

  upsertChart(key, el, {
    chart: Object.assign({ type: 'bar', height: h, stacked: hasSeg }, baseChartOpts()),
    series: series,
    colors: colors,
    plotOptions: { bar: Object.assign(
      { horizontal: true, barHeight: '68%', borderRadius: 3, distributed: distributed },
      hasSeg ? { dataLabels: { total: { enabled: true, formatter: labelFmt, style: totalStyle } } } : {}
    ) },
    dataLabels: hasSeg ? { enabled: false, dropShadow: labelShadow }
      : { enabled: true, textAnchor: 'start', offsetX: 4, formatter: labelFmt, style: labelStyle, dropShadow: labelShadow },
    xaxis: { categories: cats, labels: { formatter: function(v){ return Math.round(v); } } },
    yaxis: { labels: yLabels },
    legend: { show: false },
    grid: { borderColor: 'rgba(255,255,255,0.07)' },
    tooltip: tooltipOpts,
  });
}

function renderTags(data, opts) {
  opts = opts || {};
  // Con un empleado seleccionado, "Por sede" sería una sola sede → ocultar la
  // tarjeta. Salvo keepSede (vista propia del empleado, que sí muestra su sede).
  var perEmp = !!data.selected_employee;
  var hideSede = perEmp && !opts.keepSede;
  var sedeCard = document.getElementById('es-card-sede');
  if (sedeCard) sedeCard.style.display = hideSede ? 'none' : '';

  // Leyenda "Empleado / Todos" en proyecto y entregable cuando hay un empleado.
  var legHtml = '';
  if (perEmp) {
    var first = (data.selected_employee.name || '').trim().split(/\s+/)[0];
    // El denominador sigue al rol filtrado: "/ Todos", "/ Sup" o "/ PM".
    var denom = data.role_filter === 'supervisor' ? 'Sup'
              : data.role_filter === 'project_manager' ? 'PM'
              : 'Todos';
    legHtml = '<span style="font-weight:700;color:var(--cp-text-hi)">' + _escTag(first)
      + '</span> <span class="es-tagtot">/ ' + denom + '</span>';
  }
  ['es-leg-project', 'es-leg-deliverable'].forEach(function (id) {
    var el = document.getElementById(id);
    if (el) el.innerHTML = legHtml;
  });

  renderTagChart('tagsProject', 'es-tags-project', data.by_project, { showCode: true });
  if (!hideSede) renderTagChart('tagsLocation', 'es-tags-location', data.by_location);
  renderTagChart('tagsDeliverable', 'es-tags-deliverable', data.by_deliverable);
  // leyenda de colores de sede (para las barras apiladas de proyecto/entregable)
  var leg = document.getElementById('es-sede-legend');
  if (leg) {
    leg.innerHTML = (data.by_location || []).map(function (s) {
      return '<span class="inline-flex items-center gap-1">'
        + '<span style="width:10px;height:10px;border-radius:2px;display:inline-block;background:'
        + (s.color || '#888') + '"></span>' + _escTag(s.name) + '</span>';
    }).join('');
  }
}

function renderKpis(data) {
  applyCatColors(data);  // primer render llamado en ambas páginas → colores listos para los charts
  document.getElementById('es-kpi-items').textContent   = data.total_items;
  document.getElementById('es-kpi-reports').textContent = data.total_reports;
  document.getElementById('es-kpi-emps').textContent    = data.employees.length;
  var perday = data.total_reports ? (data.total_items / data.total_reports) : 0;
  document.getElementById('es-kpi-perday').textContent = perday.toFixed(1);
  var top = data.categories.filter(function(c){ return c.count > 0; })
                           .sort(function(a, b){ return b.count - a.count; })[0];
  document.getElementById('es-kpi-topcat').textContent = top ? top.label : '—';
}

function renderTopCat(data) {
  var sel = data.selected_employee;
  // Dos instancias separadas (single/cmp) en dos divs: solo se muestra/actualiza la
  // que corresponde. Así ninguna instancia cambia de forma ni se destruye → evita el
  // bug de no-render al alternar Todos ↔ empleado.
  var elSingle = document.getElementById('es-topcat-single');
  var elCmp    = document.getElementById('es-topcat-cmp');
  elSingle.style.display = sel ? 'none' : '';
  elCmp.style.display    = sel ? '' : 'none';

  if (sel) {
    // Total (todos) vs empleado — % de composición (qué % del trabajo de cada uno va a
    // cada categoría). En % las dos barras quedan en la misma escala y son comparables,
    // aunque el volumen del empleado sea mucho menor que el del total.
    var totalByCode = {};
    data.categories.forEach(function(c){ totalByCode[c.code] = 0; });
    data.by_role.forEach(function(r){
      Object.keys(r.categories).forEach(function(code){ totalByCode[code] = (totalByCode[code] || 0) + (r.categories[code] || 0); });
    });
    var sumTotal = 0;
    Object.keys(totalByCode).forEach(function(k){ sumTotal += totalByCode[k]; });
    var totalPct = function(code){ return sumTotal ? Math.round(1000 * (totalByCode[code] || 0) / sumTotal) / 10 : 0; };
    // Empleado: aporte respecto al TOTAL general (Ec/T), no a su propio trabajo → su
    // barra queda como la porción real dentro de la barra del total de la categoría.
    var empPct   = function(code){ return sumTotal ? Math.round(1000 * (sel.categories[code] || 0) / sumTotal) / 10 : 0; };
    // Con empleado seleccionado: ordenar por el valor DEL EMPLEADO (mayor a menor).
    var rcats = data.categories.filter(function(c){
      return (totalByCode[c.code] || 0) > 0 || (sel.categories[c.code] || 0) > 0;
    }).sort(function(a, b){ return empPct(b.code) - empPct(a.code) || totalPct(b.code) - totalPct(a.code); });
    upsertChart('topcatCmp', elCmp, {
      chart: Object.assign({ type: 'bar', height: Math.max(200, rcats.length * 46 + 50) }, baseChartOpts()),
      // Total: color por categoría (igual que la vista sin filtro); empleado: naranja.
      series: [
        { name: 'Total (todos)', data: rcats.map(function(c){ return { x: c.label, y: totalPct(c.code), fillColor: catColor(c.code) }; }) },
        { name: sel.name,        data: rcats.map(function(c){ return { x: c.label, y: empPct(c.code),   fillColor: EMP_COLOR }; }) },
      ],
      colors: ['#94a3b8', EMP_COLOR],
      fill: { opacity: [0.32, 1] },
      xaxis: { labels: { formatter: function(v){ return Math.round(v) + '%'; } } },
      yaxis: { labels: { style: { colors: _axisCat(), fontSize: '12px', fontWeight: 600 } } },
      legend: { show: true, position: 'bottom', labels: { colors: _textHi() } },
      dataLabels: { enabled: true, formatter: function(v){ return v ? v + '%' : ''; },
                    style: { fontSize: '10px', fontWeight: 700, colors: [_textHi()] } },
      grid: { borderColor: _gridColor },
      plotOptions: { bar: { horizontal: true, distributed: false, barHeight: '78%', dataLabels: { position: 'top' } } },
      tooltip: { theme: 'dark', y: { formatter: function(v){ return v + '%'; } } },
    });
  } else {
    // Vista normal: una barra por categoría (color por categoría).
    var cats = data.categories.filter(function(c){ return c.count > 0; })
                              .sort(function(a, b){ return b.count - a.count; });
    upsertChart('topcatSingle', elSingle, {
      chart: Object.assign({ type: 'bar', height: Math.max(160, cats.length * 38 + 24) }, baseChartOpts()),
      series: [{ name: 'Actividades', data: cats.map(function(c){ return c.count; }) }],
      colors: cats.map(function(c){ return catColor(c.code); }),
      xaxis: { categories: cats.map(function(c){ return c.label; }),
               labels: { formatter: function(v){ return Math.round(v); } } },
      yaxis: { labels: { style: { colors: _axisCat(), fontSize: '12px', fontWeight: 600 } } },
      legend: { show: false },
      grid: { borderColor: _gridColor },
      plotOptions: { bar: { horizontal: true, distributed: true, barHeight: '62%', borderRadius: 3,
                            dataLabels: { position: 'top' } } },
      dataLabels: { enabled: true, textAnchor: 'start', offsetX: 6,
                    formatter: function(v, opts){ return v + ' · ' + cats[opts.dataPointIndex].pct + '%'; },
                    style: { fontSize: '11px', fontWeight: 600, colors: [_foreColor()] } },
      tooltip: { theme: 'dark', y: { formatter: function(v){ return v + ' actividades'; } } },
    });
  }
}

function destroyCharts() {
  Object.keys(_charts).forEach(function(k){ if (_charts[k]) { try { _charts[k].destroy(); } catch (e) {} } });
  _charts = {};
  _chartHeights = {};
}

// Crea el gráfico si no existe, o actualiza la instancia en su lugar.
// Si la ALTURA cambió, recrea: ApexCharts no actualiza chart.height de forma
// fiable vía updateOptions (el SVG cambia pero el contenedor mantiene la altura
// vieja → el contenido se desborda hacia abajo).
function upsertChart(key, el, opts) {
  var h = opts.chart && opts.chart.height;
  if (_charts[key] && _chartHeights[key] !== h) {
    try { _charts[key].destroy(); } catch (e) {}
    _charts[key] = null;
    el.innerHTML = '';
  }
  _chartHeights[key] = h;
  if (_charts[key]) {
    _charts[key].updateOptions(opts, true, true);
  } else {
    _charts[key] = new ApexCharts(el, opts);
    _charts[key].render();
  }
}

// En impresión, el texto de los gráficos (ticks/leyenda) es gris claro y casi
// no se ve sobre fondo blanco: lo re-coloreamos a oscuro antes de imprimir.
function recolorCharts(color, gridColor, dataLabelColor, yaxisColor) {
  Object.keys(_charts).forEach(function(k){
    var ch = _charts[k];
    if (!ch) return;
    try {
      ch.updateOptions({
        chart: { foreColor: color },
        grid: { borderColor: gridColor },
        xaxis: { labels: { style: { colors: color } } },
        yaxis: { labels: { style: { colors: yaxisColor || color } } },
        // Los % sobre las barras son SVG (fill): el CSS de impresión no los alcanza,
        // hay que recolorearlos a oscuro para que salgan en el PDF.
        dataLabels: { style: { colors: [dataLabelColor] } },
        // El label de TOTAL de barras apiladas usa `color` (singular) aparte.
        plotOptions: { bar: { dataLabels: { total: { style: { color: dataLabelColor } } } } },
      }, false, false);
    } catch (e) {}
  });
}
function chartsToPrint() { recolorCharts('#1a1a1a', 'rgba(0,0,0,0.12)', '#1a1a1a', '#1a1a1a'); }
function chartsToScreen() { recolorCharts(tok('--cp-text-lo') || '#888', 'rgba(255,255,255,0.07)', _axisCat(), _axisCat()); }
window.addEventListener('beforeprint', chartsToPrint);
window.addEventListener('afterprint',  chartsToScreen);
if (window.matchMedia) {
  var _mqPrint = window.matchMedia('print');
  (_mqPrint.addEventListener ? _mqPrint.addEventListener.bind(_mqPrint, 'change') : _mqPrint.addListener.bind(_mqPrint))(
    function(mq){ if (mq.matches) chartsToPrint(); else chartsToScreen(); }
  );
}

// Leyenda HTML (imprimible). items = [{text, color}]
function renderLegend(containerId, items) {
  var el = document.getElementById(containerId);
  if (!el) return;
  el.innerHTML = items.map(function(it){
    return '<span class="es-leg-item"><span class="es-leg-dot" style="background:' + it.color + '"></span>' + it.text + '</span>';
  }).join('');
}

// Color base de texto/ejes según el tema (recoloreado a oscuro en impresión).
var _gridColor = 'rgba(255,255,255,0.07)';
function _foreColor() { return tok('--cp-text-lo') || '#888'; }
function _textHi()   { return 'rgba(255,255,255,0.7)'; }  // contraste subido, sin llegar a blanco (leyendas / % sobre barras)
// Etiquetas de categoría en los ejes (nombres a la izquierda): contraste alto para legibilidad.
function _axisCat()  { return tok('--cp-text-hi') || 'rgba(255,255,255,0.95)'; }
function baseChartOpts() {
  return { fontFamily: 'Nunito, sans-serif', foreColor: _foreColor(), toolbar: { show: false }, animations: { enabled: true } };
}

function renderCharts(data) {
  var cats = data.categories.filter(function(c){ return c.count > 0; });
  var catLegend = cats.map(function(c){ return { text: c.label, color: catColor(c.code) }; });
  var colors = cats.map(function(c){ return catColor(c.code); });
  var baseChart = baseChartOpts();

  // ── 1. Distribución (donut) — leyenda HTML ──
  upsertChart('dist', document.getElementById('es-chart-dist'), {
    chart: Object.assign({ type: 'donut', height: '100%' }, baseChart),
    series: cats.map(function(c){ return c.count; }),
    labels: cats.map(function(c){ return c.label; }),
    colors: colors,
    legend: { show: false },
    dataLabels: { enabled: false },
    stroke: { width: 2, colors: [tok('--color-base-100')] },
    plotOptions: { pie: { donut: { size: '58%' } } },
    tooltip: { theme: 'dark' },
  });
  renderLegend('es-leg-dist', catLegend);

  // ── 2. Supervisores vs PMs — x = roles, una barra por categoría (leyenda HTML) ──
  // Barras horizontales agrupadas: % del trabajo por categoría.
  //  · Sin filtro de empleado → una barra por rol (Supervisores / PMs).
  //  · Con un empleado seleccionado → empleado + promedio Sup + promedio PM (referencia).
  var roleColor = function(role){ return role === 'supervisor' ? tok('--color-success') : tok('--color-info'); };
  var roleShort = function(role){ return role === 'supervisor' ? 'prom. Sup' : 'prom. PM'; };
  var sel = data.selected_employee;
  // Con empleado seleccionado: todas las barras = % del TOTAL general (aporte real del
  // empleado y de cada rol). Sin empleado (vista ejecutiva agregada): % de composición
  // de cada rol, como antes.
  var roleTotalAll = 0; data.by_role.forEach(function(r){ roleTotalAll += r.total; });
  var pctOf = function(o, code){
    var denom = sel ? roleTotalAll : o.total;
    return denom ? Math.round(1000 * (o.categories[code] || 0) / denom) / 10 : 0;
  };
  // Categorías a mostrar: con datos en el empleado o en cualquier rol.
  // Orden: por producción total (suma de ambos roles), mayor arriba.
  var roleVol = function(code){
    var s = 0; data.by_role.forEach(function(r){ s += (r.categories[code] || 0); }); return s;
  };
  // Con empleado seleccionado: ordenar por el valor DEL EMPLEADO (mayor a menor);
  // sin empleado: por producción total de los roles.
  var rcats = data.categories.filter(function(c){
    // Con empleado seleccionado: solo categorías donde el empleado participó (>0).
    if (sel) return (sel.categories[c.code] || 0) > 0;
    return c.count > 0 || data.by_role.some(function(r){ return (r.categories[c.code] || 0) > 0; });
  }).sort(function(a, b){
    return sel ? (pctOf(sel, b.code) - pctOf(sel, a.code)) : (roleVol(b.code) - roleVol(a.code));
  });
  var roleSeries = data.by_role.map(function(r){
    return { name: sel ? roleShort(r.role) : r.label, data: rcats.map(function(c){ return pctOf(r, c.code); }) };
  });
  var rSeries, rColors, rLeg;
  if (sel) {
    rSeries = [{ name: sel.name, data: rcats.map(function(c){ return pctOf(sel, c.code); }) }].concat(roleSeries);
    rColors = [EMP_COLOR].concat(data.by_role.map(function(r){ return roleColor(r.role); }));
    rLeg = [{ text: sel.name, color: EMP_COLOR }].concat(
             data.by_role.map(function(r){ return { text: roleShort(r.role), color: roleColor(r.role) }; }));
  } else {
    rSeries = roleSeries;
    rColors = data.by_role.map(function(r){ return roleColor(r.role); });
    rLeg = data.by_role.map(function(r){ return { text: r.label, color: roleColor(r.role) }; });
  }
  // Altura dinámica: cada categoría necesita espacio para sus 2-3 barras (rol/empleado).
  // Con altura fija las barras y etiquetas se enciman cuando hay muchas categorías.
  var roleH = Math.max(300, rcats.length * (sel ? 38 : 30) + 40);
  upsertChart('role', document.getElementById('es-chart-role'), {
    chart: Object.assign({ type: 'bar', height: roleH }, baseChart),
    series: rSeries,
    colors: rColors,
    // Empleado resaltado (opacidad plena); promedios de referencia atenuados.
    fill: { opacity: sel ? [1].concat(data.by_role.map(function(){ return 0.45; })) : rSeries.map(function(){ return 1; }) },
    xaxis: { categories: rcats.map(function(c){ return c.label; }),
             labels: { formatter: function(v){ return Math.round(v) + '%'; } } },
    yaxis: { labels: { style: { colors: _axisCat(), fontSize: '12px', fontWeight: 600 } } },
    legend: { show: false },
    dataLabels: { enabled: !sel, formatter: function(v){ return v ? v + '%' : ''; },
                  style: { fontSize: '11px', fontWeight: 800, colors: [_axisCat()] },
                  dropShadow: { enabled: true, top: 0, left: 0, blur: 2, color: '#000', opacity: 0.55 } },
    grid: { borderColor: _gridColor },
    plotOptions: { bar: { horizontal: true, barHeight: '70%', dataLabels: { position: 'top' } } },
    tooltip: { theme: 'dark', y: { formatter: function(v){ return v + '%'; } } },
  });
  renderLegend('es-leg-role', rLeg);

  // ── 3. Evolución (línea por categoría) — leyenda HTML ──
  var months = data.monthly;
  upsertChart('month', document.getElementById('es-chart-month'), {
    chart: Object.assign({ type: 'line', height: '100%' }, baseChart),
    series: cats.map(function(c){
      return { name: c.label, data: months.map(function(m){ return m.categories[c.code] || 0; }) };
    }),
    colors: colors,
    xaxis: { categories: months.map(function(m){ return m.label; }) },
    yaxis: { min: 0, labels: { formatter: function(v){ return Math.round(v); } } },
    stroke: { width: 2, curve: 'smooth' },
    markers: { size: 3 },
    legend: { show: false },
    dataLabels: { enabled: false },
    grid: { borderColor: _gridColor },
    tooltip: { theme: 'dark' },
  });
  renderLegend('es-leg-month', catLegend);
}

function rolelabel(r) { return r === 'supervisor' ? 'Sup.' : 'PM'; }

function catChip(code, labels) {
  if (!code) return '<span class="muted">—</span>';
  return '<span style="display:inline-flex;align-items:center;gap:6px">'
    + '<span style="width:9px;height:9px;border-radius:2px;background:' + catColor(code) + '"></span>'
    + (labels[code] || code) + '</span>';
}

function renderMetrics(data) {
  document.getElementById('es-met-head').innerHTML =
      '<th>Nombre</th><th class="center">Rol</th><th class="center">Días c/reporte</th>'
    + '<th class="center">Actividades</th><th class="center">Act/día</th>'
    + '<th class="center">% del total</th><th class="center">Categ.</th>'
    + '<th>Categorías principales</th><th class="center">Último reporte</th>';
  var labels = data.category_labels || {};
  // % del total = participación sobre el total GLOBAL (suma de ambos roles), para
  // que tenga sentido también en la vista propia del empleado (donde total_items
  // es el del propio empleado → siempre 100%) y sea comparable con los promedios.
  var globalTotal = (data.by_role || []).reduce(function(s, r){ return s + (r.total || 0); }, 0)
                    || data.total_items || 0;
  var body = '';
  data.employees.forEach(function(e){
    var perday = e.reports ? (e.total / e.reports).toFixed(1) : '—';
    var pct = globalTotal ? (100 * e.total / globalTotal).toFixed(1) : '0';
    var ranked = Object.keys(e.categories).filter(function(k){ return e.categories[k] > 0; })
                       .sort(function(a, b){ return e.categories[b] - e.categories[a]; });
    var distinct = ranked.length;
    var top = ranked[0] || '';
    var second = ranked[1] || '';
    body += '<tr><td>' + e.name + '</td>'
      + '<td class="center"><span class="es-role-pill ' + e.role + '">' + rolelabel(e.role) + '</span></td>'
      + '<td class="center">' + (e.reports || 0) + '</td>'
      + '<td class="center">' + e.total + '</td>'
      + '<td class="center">' + perday + '</td>'
      + '<td class="center muted">' + pct + '%</td>'
      + '<td class="center">' + distinct + '</td>'
      + '<td><div style="display:flex;flex-direction:column;gap:2px;line-height:1.35">'
      +   catChip(top, labels)
      +   (second ? '<span class="muted" style="font-size:0.78rem">' + catChip(second, labels) + '</span>' : '')
      + '</div></td>'
      + '<td class="center muted">' + (e.last_date || '—') + '</td>'
      + '</tr>';
  });
  // Referencia: promedio por empleado de cada rol (solo al filtrar un empleado).
  if (data.selected_employee) {
    data.by_role.forEach(function(r, i){
      var ranked = Object.keys(r.avg_categories).filter(function(k){ return r.avg_categories[k] > 0; })
                         .sort(function(a, b){ return r.avg_categories[b] - r.avg_categories[a]; });
      var top = ranked[0] || '', second = ranked[1] || '';
      body += '<tr class="es-ref-row' + (i === 0 ? ' es-ref-first' : '') + '"><td>Prom. ' + r.label + '</td>'
        + '<td class="center"><span class="es-role-pill ' + r.role + '">' + rolelabel(r.role) + '</span></td>'
        + '<td class="center">' + r.avg_reports + '</td>'
        + '<td class="center">' + r.avg_total + '</td>'
        + '<td class="center">' + r.avg_perday + '</td>'
        + '<td class="center muted">' + (globalTotal ? (100 * r.avg_total / globalTotal).toFixed(1) + '%' : '—') + '</td>'
        + '<td class="center">' + ranked.length + '</td>'
        + '<td><div style="display:flex;flex-direction:column;gap:2px;line-height:1.35">'
        +   catChip(top, labels)
        +   (second ? '<span class="muted" style="font-size:0.78rem">' + catChip(second, labels) + '</span>' : '')
        + '</div></td>'
        + '<td class="center muted">—</td></tr>';
    });
  }
  document.getElementById('es-met-body').innerHTML = body;
}

// Abreviatura corta y legible para encabezados de columna (ej: Cronogramas → Cronog.,
// Supervisión → Superv., Adquisiciones → Adquis.). Tooltip muestra el nombre completo.
function abbrevCat(label) {
  var w = (label || '').split(' ')[0];
  return w.length > 8 ? (w.slice(0, 6) + '.') : w;
}

function renderEmployees(data) {
  var sel = data.selected_employee;
  // Con un empleado seleccionado: unión de sus categorías y las de los roles (referencia).
  var cats = data.categories.filter(function(c){
    return c.count > 0 || (sel && data.by_role.some(function(r){ return (r.avg_categories[c.code] || 0) > 0; }));
  });
  var head = '<th>Nombre</th><th class="center">Rol</th><th class="center">Total</th>';
  cats.forEach(function(c){ head += '<th class="center" title="' + c.label + '">' + abbrevCat(c.label) + '</th>'; });
  document.getElementById('es-emp-head').innerHTML = head;

  var body = '';
  data.employees.forEach(function(e){
    body += '<tr><td>' + e.name + '</td>'
      + '<td class="center"><span class="es-role-pill ' + e.role + '">' + rolelabel(e.role) + '</span></td>'
      + '<td class="center">' + e.total + '</td>';
    cats.forEach(function(c){
      var n = e.categories[c.code] || 0;
      body += '<td class="center ' + (n ? '' : 'muted') + '">' + (n || '·') + '</td>';
    });
    body += '</tr>';
  });
  // Referencia: promedio por empleado de cada rol (solo al filtrar un empleado).
  if (sel) {
    data.by_role.forEach(function(r, i){
      body += '<tr class="es-ref-row' + (i === 0 ? ' es-ref-first' : '') + '"><td>Prom. ' + r.label + '</td>'
        + '<td class="center"><span class="es-role-pill ' + r.role + '">' + rolelabel(r.role) + '</span></td>'
        + '<td class="center">' + r.avg_total + '</td>';
      cats.forEach(function(c){
        var n = r.avg_categories[c.code] || 0;
        body += '<td class="center ' + (n ? '' : 'muted') + '">' + (n || '·') + '</td>';
      });
      body += '</tr>';
    });
  }
  document.getElementById('es-emp-body').innerHTML = body;
}
