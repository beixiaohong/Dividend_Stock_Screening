// charts.js —— 零依赖 SVG 图表：资产走势(折线) + 持仓配置(环形)
// 适用于浅色/深色主题（颜色取自 CSS 变量，由 JS 读取）
const Charts = (() => {
  function cssVar(name, fallback) {
    const v = getComputedStyle(document.documentElement).getPropertyValue(name).trim();
    return v || fallback;
  }

  function _tip() {
    let t = document.querySelector('.chart-tip');
    if (!t) { t = document.createElement('div'); t.className = 'chart-tip'; document.body.appendChild(t); }
    return t;
  }

  // ---------------- 折线 / 面积图 ----------------
  function line(el, series, opts = {}) {
    el.innerHTML = '';
    if (!series || !series.length) { el.innerHTML = '<div class="empty">暂无数据</div>'; return; }
    const height = opts.height || 230;
    const W = Math.max(el.clientWidth || 600, 280);
    const H = height;
    const padL = 12, padR = 12, padT = 16, padB = 24;
    const plotW = W - padL - padR;
    const plotH = H - padT - padB;
    const vals = series.map(s => Number(s.value) || 0);
    let min = Math.min(...vals), max = Math.max(...vals);
    if (min === max) { min -= 1; max += 1; }
    const span = (max - min) || 1;
    min -= span * 0.08; max += span * 0.08;
    const n = series.length;
    const X = i => padL + (n === 1 ? plotW / 2 : (i / (n - 1)) * plotW);
    const Y = v => padT + (1 - (v - min) / (max - min)) * plotH;

    const pts = series.map((s, i) => [X(i), Y(Number(s.value) || 0)]);
    const linePath = pts.map((p, i) => (i ? 'L' : 'M') + p[0].toFixed(1) + ',' + p[1].toFixed(1)).join(' ');
    const areaPath = 'M' + pts[0][0].toFixed(1) + ',' + (padT + plotH).toFixed(1)
      + ' ' + pts.map(p => 'L' + p[0].toFixed(1) + ',' + p[1].toFixed(1)).join(' ')
      + ' L' + pts[n - 1][0].toFixed(1) + ',' + (padT + plotH).toFixed(1) + ' Z';

    const fmt = opts.valueFmt || (v => App.fmtNum(v));
    const yLabels = [max, (max + min) / 2, min].map(v =>
      `<text x="${padL}" y="${(Y(v) + 3).toFixed(1)}">${fmt(v)}</text>`).join('');
    const xi = [0, Math.floor((n - 1) / 2), n - 1].filter((v, i, a) => a.indexOf(v) === i);
    const xLabels = xi.map(i =>
      `<text x="${X(i).toFixed(1)}" y="${H - 6}" text-anchor="${i === 0 ? 'start' : i === n - 1 ? 'end' : 'middle'}">${series[i].label}</text>`).join('');

    el.innerHTML = `
      <svg viewBox="0 0 ${W} ${H}" preserveAspectRatio="none" role="img">
        <path class="area" d="${areaPath}"></path>
        <path class="line" d="${linePath}"></path>
        ${yLabels}${xLabels}
        <line id="hl" class="grid" x1="0" y1="${padT}" x2="0" y2="${padT + plotH}" style="display:none"></line>
        <circle id="hd" class="dot" r="3.5" style="display:none"></circle>
        <rect id="ov" x="${padL}" y="${padT}" width="${plotW}" height="${plotH}" fill="transparent"></rect>
      </svg>`;

    const svg = el.querySelector('svg');
    const ov = el.querySelector('#ov');
    const hl = el.querySelector('#hl');
    const hd = el.querySelector('#hd');
    const tip = _tip();
    ov.addEventListener('mousemove', e => {
      const r = svg.getBoundingClientRect();
      const relX = (e.clientX - r.left) / r.width * W;
      let i = Math.round((relX - padL) / (plotW || 1) * (n - 1));
      i = Math.max(0, Math.min(n - 1, i));
      const px = X(i), py = Y(Number(series[i].value) || 0);
      hl.setAttribute('x1', px); hl.setAttribute('x2', px); hl.style.display = '';
      hd.setAttribute('cx', px); hd.setAttribute('cy', py); hd.style.display = '';
      tip.textContent = series[i].label + ' · ' + fmt(series[i].value);
      tip.style.left = (e.clientX + 12) + 'px';
      tip.style.top = (e.clientY - 10) + 'px';
      tip.style.opacity = '1';
    });
    ov.addEventListener('mouseleave', () => { hl.style.display = 'none'; hd.style.display = 'none'; tip.style.opacity = '0'; });

    // 响应式重绘
    _bindResize(el, () => line(el, series, opts));
  }

  // ---------------- 环形图 ----------------
  function donut(el, segments, opts = {}) {
    el.innerHTML = '';
    const total = segments.reduce((a, s) => a + (Number(s.value) || 0), 0);
    if (!total) { el.innerHTML = '<div class="empty">暂无持仓</div>'; return; }
    const size = 180, cx = 90, cy = 90, r = 66, sw = 24;
    const C = 2 * Math.PI * r;
    let acc = 0;
    const arcs = segments.map(s => {
      const len = (Number(s.value) || 0) / total * C;
      const dash = `${len.toFixed(2)} ${(C - len).toFixed(2)}`;
      const off = (-acc).toFixed(2);
      acc += len;
      return `<circle cx="${cx}" cy="${cy}" r="${r}" fill="none" stroke="${s.color}" stroke-width="${sw}"
        stroke-dasharray="${dash}" stroke-dashoffset="${off}" transform="rotate(-90 ${cx} ${cy})"></circle>`;
    }).join('');
    const center = opts.centerLabel || '总市值';
    const centerVal = opts.centerFmt ? opts.centerFmt(total) : App.fmtNum(total);
    const legend = segments.map(s => {
      const pct = (Number(s.value) || 0) / total * 100;
      return `<span class="li"><span class="dotc" style="background:${s.color}"></span>${App.escapeHtml(s.label)} ${pct.toFixed(1)}%</span>`;
    }).join('');
    el.innerHTML = `
      <div style="display:flex;gap:18px;align-items:center;flex-wrap:wrap;justify-content:center;">
        <svg width="${size}" height="${size}" viewBox="0 0 ${size} ${size}" role="img">
          <circle cx="${cx}" cy="${cy}" r="${r}" fill="none" stroke="${cssVar('--border', '#e6e8eb')}" stroke-width="${sw}"></circle>
          ${arcs}
          <text x="${cx}" y="${cy - 4}" text-anchor="middle" style="fill:var(--muted);font-size:12px">${center}</text>
          <text x="${cx}" y="${cy + 16}" text-anchor="middle" style="fill:var(--text);font-size:15px;font-weight:600">${centerVal}</text>
        </svg>
        <div class="legend" style="flex-direction:column;gap:8px;">${legend}</div>
      </div>`;
  }

  // ---------------- 响应式 ----------------
  const _rs = new WeakMap();
  function _bindResize(el, fn) {
    if (_rs.has(el)) return;
    _rs.set(el, true);
    let t;
    window.addEventListener('resize', () => { clearTimeout(t); t = setTimeout(fn, 150); });
  }

  return { line, donut };
})();
