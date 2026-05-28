(function () {
  'use strict';

  const API_BASE = '/api/graph_read';
  const MAX_BARS = 24;
  const INITIAL_FETCH_LIMIT = 5000;
  const SAMPLE_BASE_MIN = 5;
  const COVERAGE_THRESHOLD = 0.90;
  const POLL_MS = 8000;
  const MENU = [
    { label: '5 min', val: 5 },
    { label: '15 min', val: 15 },
    { label: '30 min', val: 30 },
    { label: '1 hr', val: 60 },
    { label: '2 hr', val: 120 },
    { label: '4 hr', val: 240 },
  ];
  const SERIES = [
    { key: 'pm1p0', title: 'PM1.0 µg/m³', color: '#ff0000', agg: 5 },
    { key: 'pm2p5', title: 'PM2.5 µg/m³', color: '#bfa600', agg: 5 },
    { key: 'pm4p0', title: 'PM4.0 µg/m³', color: '#00bfbf', agg: 5 },
    { key: 'pm10p0', title: 'PM10.0 µg/m³', color: '#bf00ff', agg: 5 },
    { key: 'voc', title: 'VOC (Index)', color: '#ff8000', agg: 5 },
    { key: 'nox', title: 'NOx (Index)', color: '#00aa00', agg: 5 },
    { key: 'co2', title: 'CO2 (ppm)', color: '#990000', agg: 5 },
    { key: 'temp', title: 'Temperatura (°C)', color: '#006600', agg: 5 },
    { key: 'hum', title: 'Humedad relativa (%)', color: '#0000cc', agg: 5, round: true },
  ];

  let raw = [];
  let lastRowId = 0;
  let initialized = false;

  function fmt2(n) { return String(n).padStart(2, '0'); }
  function fmtDate(ms) {
    const d = new Date(ms);
    return `${d.getFullYear()}-${fmt2(d.getMonth() + 1)}-${fmt2(d.getDate())}`;
  }
  function fmtTime(ms) {
    const d = new Date(ms);
    return `${fmt2(d.getHours())}:${fmt2(d.getMinutes())}`;
  }
  function toIsoDate(fecha) {
    if (!fecha || typeof fecha !== 'string') return new Date().toISOString().slice(0, 10);
    const parts = fecha.split(/[-/]/);
    if (parts.length !== 3) return new Date().toISOString().slice(0, 10);
    if (parts[0].length === 4) {
      const [yyyy, mm, dd] = parts;
      return `${yyyy}-${String(mm).padStart(2, '0')}-${String(dd).padStart(2, '0')}`;
    }
    const [dd, mm, yyyy] = parts;
    return `${yyyy}-${String(mm).padStart(2, '0')}-${String(dd).padStart(2, '0')}`;
  }
  function parseTs(row) {
    const rawTime = row && row.hora ? row.hora : '00:00:00';
    const time = /^\d{1,2}:\d{2}$/.test(rawTime) ? `${rawTime}:00` : rawTime;
    const ms = Date.parse(`${toIsoDate(row.fecha)}T${time}`);
    return Number.isFinite(ms) ? ms : null;
  }
  function startOfLocalDayMs(ms) {
    const d = new Date(ms);
    d.setHours(0, 0, 0, 0);
    return d.getTime();
  }
  function floorToBinLocal(ms, minutes) {
    const day0 = startOfLocalDayMs(ms);
    const widthMs = minutes * 60000;
    return day0 + Math.floor((ms - day0) / widthMs) * widthMs;
  }
  function makeBinLabel(binStartMs, minutes) {
    return `${fmtDate(binStartMs)} ${fmtTime(binStartMs)}`;
  }
  function buildTickText(labels, minutes) {
    const formatDateTime = (date, time) => {
      const [yyyy, mm, dd] = String(date || '').split('-');
      return `${dd}/${mm}/${yyyy}-${time}`;
    };
    const items = labels.map(s => {
      const str = String(s || '');
      const m = str.match(/^(\d{4}-\d{2}-\d{2})\s+(\d{1,2}:\d{2})/);
      return { date: m ? m[1] : '', time: m ? m[2] : str };
    });
    const out = items.map(it => it.time);
    let stamped = false;
    for (let i = 1; i < items.length; i++) {
      if (items[i].date && items[i - 1].date && items[i].date !== items[i - 1].date) {
        out[i - 1] = formatDateTime(items[i - 1].date, items[i - 1].time);
        stamped = true;
      }
    }
    if (!stamped && items[0] && items[0].date) out[0] = formatDateTime(items[0].date, items[0].time);
    return out;
  }
  function getLast24RawForKey(key) {
    const last = raw.slice(-MAX_BARS);
    return {
      labels: last.map(r => makeBinLabel(r.ts, SAMPLE_BASE_MIN)),
      values: last.map(r => Number(r[key])),
    };
  }
  function getAgg24ForKey(key, minutes) {
    if (!raw.length) return { labels: [], values: [] };
    const widthMs = minutes * 60000;
    let lastTs = 0;
    const groups = new Map();
    for (const r of raw) {
      const value = Number(r[key]);
      if (!Number.isFinite(value)) continue;
      if (r.ts > lastTs) lastTs = r.ts;
      const bin = floorToBinLocal(r.ts, minutes);
      const group = groups.get(bin) || { sum: 0, count: 0 };
      group.sum += value;
      group.count += 1;
      groups.set(bin, group);
    }
    const expected = minutes / SAMPLE_BASE_MIN;
    const required = Math.max(1, Math.ceil(expected * COVERAGE_THRESHOLD));
    const bins = Array.from(groups.keys())
      .filter(bin => (bin + widthMs) <= lastTs && groups.get(bin).count >= required)
      .sort((a, b) => a - b)
      .slice(-MAX_BARS);
    return {
      labels: bins.map(bin => makeBinLabel(bin, minutes)),
      values: bins.map(bin => groups.get(bin).sum / groups.get(bin).count),
    };
  }
  function dataForSeries(series) {
    const data = series.agg === 5 ? getLast24RawForKey(series.key) : getAgg24ForKey(series.key, series.agg);
    while (data.labels.length < MAX_BARS) data.labels.push('');
    while (data.values.length < MAX_BARS) data.values.push(null);
    if (series.round) data.values = data.values.map(v => Number.isFinite(v) ? Math.round(v) : v);
    return data;
  }
  function yMax(values) {
    const finite = values.filter(v => Number.isFinite(v) && v >= 0);
    const max = finite.length ? Math.max(...finite) : 0;
    return max > 0 ? max * 2 : 1;
  }
  function svgChart(series, labels, values) {
    const width = 860;
    const height = 340;
    const left = 70;
    const right = 20;
    const top = 20;
    const bottom = 100;
    const chartW = width - left - right;
    const chartH = height - top - bottom;
    const maxY = yMax(values);
    const gap = 6;
    const barW = Math.max(4, (chartW / MAX_BARS) - gap);
    const ticks = [0, maxY / 2, maxY];
    const bars = values.map((v, i) => {
      if (!Number.isFinite(v)) return '';
      const h = Math.max(0, (v / maxY) * chartH);
      const x = left + i * (chartW / MAX_BARS) + gap / 2;
      const y = top + chartH - h;
      return `<rect x="${x.toFixed(1)}" y="${y.toFixed(1)}" width="${barW.toFixed(1)}" height="${h.toFixed(1)}" fill="${series.color}"><title>${labels[i]}: ${Number(v).toFixed(2)}</title></rect>`;
    }).join('');
    const tickText = buildTickText(labels, series.agg);
    const xLabels = tickText.map((label, i) => {
      if (!label) return '';
      const x = left + i * (chartW / MAX_BARS) + (chartW / MAX_BARS) / 2;
      const lines = label.split('\n');
      return `<text x="${x.toFixed(1)}" y="${height - 56}" text-anchor="end" transform="rotate(-45 ${x.toFixed(1)} ${height - 56})" class="chart-tick"><tspan>${lines[0]}</tspan>${lines[1] ? `<tspan x="${x.toFixed(1)}" dy="14">${lines[1]}</tspan>` : ''}</text>`;
    }).join('');
    const yTicks = ticks.map(t => {
      const y = top + chartH - (t / maxY) * chartH;
      return `<line x1="${left}" x2="${width - right}" y1="${y}" y2="${y}" class="chart-grid"/><text x="${left - 10}" y="${y + 4}" text-anchor="end" class="chart-tick">${t.toFixed(t >= 10 ? 0 : 1)}</text>`;
    }).join('');
    return `<svg viewBox="0 0 ${width} ${height}" role="img" aria-label="${series.title}">${yTicks}<line x1="${left}" x2="${left}" y1="${top}" y2="${top + chartH}" class="chart-axis"/><line x1="${left}" x2="${width - right}" y1="${top + chartH}" y2="${top + chartH}" class="chart-axis"/>${bars}${xLabels}<text x="${width / 2}" y="${height - 8}" text-anchor="middle" class="chart-axis-title">Fecha y Hora de Medición</text></svg>`;
  }
  function redrawSeries(series) {
    const card = document.querySelector(`[data-chart-key="${series.key}"]`);
    if (!card) return;
    const data = dataForSeries(series);
    const body = card.querySelector('.chart-body');
    body.innerHTML = svgChart(series, data.labels, data.values);
  }
  function redrawAll() { SERIES.forEach(redrawSeries); }
  function createChartCard(series) {
    const card = document.createElement('section');
    card.className = 'eco-chart-card';
    card.dataset.chartKey = series.key;
    card.innerHTML = `<div class="agg-chart-title">${series.title}</div><div class="agg-toolbar-label">Seleccione el intervalo de lecturas</div><div class="agg-toolbar"></div><div class="chart-body"></div>`;
    const toolbar = card.querySelector('.agg-toolbar');
    MENU.forEach(option => {
      const button = document.createElement('button');
      button.className = `agg-btn${option.val === series.agg ? ' active' : ''}`;
      button.type = 'button';
      button.textContent = option.label;
      button.addEventListener('click', () => {
        series.agg = option.val;
        toolbar.querySelectorAll('.agg-btn').forEach(btn => btn.classList.remove('active'));
        button.classList.add('active');
        redrawSeries(series);
      });
      toolbar.appendChild(button);
    });
    return card;
  }
  function pushRowToRaw(row) {
    const ts = parseTs(row);
    if (!Number.isFinite(ts)) return;
    if (raw.some(item => item._row_id === row._row_id)) return;
    raw.push({
      ts,
      pm1p0: Number(row.pm1p0 ?? 0),
      pm2p5: Number(row.pm2p5 ?? 0),
      pm4p0: Number(row.pm4p0 ?? 0),
      pm10p0: Number(row.pm10p0 ?? 0),
      voc: Number(row.voc ?? 0),
      nox: Number(row.nox ?? 0),
      co2: Number(row.co2 ?? 0),
      temp: Number(row.temp ?? 0),
      hum: Number(row.hum ?? 0),
      _row_id: row._row_id,
    });
    if (row._row_id && row._row_id > lastRowId) lastRowId = row._row_id;
  }
  async function apiGet(op, params = {}) {
    const url = new URL(API_BASE, window.location.origin);
    url.searchParams.set('op', op);
    Object.entries(params).forEach(([key, value]) => url.searchParams.set(key, value));
    const response = await fetch(url.toString(), { cache: 'no-store' });
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    return response.json();
  }
  async function loadInitial() {
    const history = await apiGet('history', { limit: INITIAL_FETCH_LIMIT });
    if (history && history.ok && Array.isArray(history.rows)) {
      history.rows.forEach(pushRowToRaw);
      raw.sort((a, b) => a.ts - b.ts);
      redrawAll();
    }
  }
  async function pollLatest() {
    try {
      const latestResponse = await apiGet('latest');
      const latest = latestResponse && latestResponse.ok ? latestResponse.row : null;
      if (!latest || !latest._row_id || latest._row_id <= lastRowId) return;
      const inc = await apiGet('since', { id: lastRowId, limit: 500 });
      if (inc && inc.ok && Array.isArray(inc.rows)) {
        inc.rows.forEach(pushRowToRaw);
        raw.sort((a, b) => a.ts - b.ts);
        redrawAll();
      }
    } catch (error) {
      // Reconexión silenciosa: no mostrar nada en frontend.
    }
  }
  async function init() {
    if (initialized) return;
    const container = document.getElementById('ecosensor-charts');
    if (!container) return;
    initialized = true;
    container.innerHTML = '';
    SERIES.forEach(series => container.appendChild(createChartCard(series)));
    redrawAll();
    try { await loadInitial(); } catch (error) {}
    setInterval(pollLatest, POLL_MS);
  }

  const initTimer = setInterval(() => {
    if (document.getElementById('ecosensor-charts')) {
      clearInterval(initTimer);
      init();
    }
  }, 250);
})();
