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

  // ---------------- 蜡烛图（含成交量副图） ----------------
  function candle(el, rows, opts = {}) {
    el.innerHTML = '';
    if (!rows || !rows.length) { el.innerHTML = '<div class="empty">暂无数据</div>'; return; }
    const height = opts.height || 320;
    const W = Math.max(el.clientWidth || 600, 280);
    const H = height;
    const padL = 8, padR = 60, padT = 14, padB = 18;
    const showVol = opts.volume !== false && rows.some(r => Number(r.volume) > 0);
    const volH = showVol ? Math.round(H * 0.22) : 0;
    const gap = showVol ? 14 : 0;
    const mainTop = padT;
    const mainBot = padT + (H - padT - padB - gap - volH);
    const mainH = mainBot - mainTop;
    const plotW = W - padL - padR;
    const n = rows.length;

    const prices = [];
    rows.forEach(r => { prices.push(Number(r.high), Number(r.low)); });
    let min = Math.min(...prices), max = Math.max(...prices);
    if (min === max) { min -= 1; max += 1; }
    const span = (max - min) || 1;
    min -= span * 0.05; max += span * 0.05;

    const cw = Math.max(1.5, Math.min(18, plotW / n * 0.66));
    const X = i => padL + (n === 1 ? plotW / 2 : (i / (n - 1)) * plotW);
    const Y = v => mainTop + (1 - (v - min) / (max - min)) * mainH;

    const up = cssVar('--up', '#e54545');
    const down = cssVar('--down', '#1ba784');
    const grid = cssVar('--border', '#e6e8eb');
    const fmt = opts.valueFmt || (v => App.fmtNum(v));

    // 价格网格 + 右侧刻度
    let g = '';
    const ticks = 4;
    for (let t = 0; t <= ticks; t++) {
      const v = min + (max - min) * t / ticks;
      const y = Y(v);
      g += `<line x1="${padL}" y1="${y.toFixed(1)}" x2="${W - padR}" y2="${y.toFixed(1)}" stroke="${grid}" stroke-width="1" stroke-dasharray="2 3" opacity="0.6"></line>`;
      g += `<text x="${W - padR + 5}" y="${(y + 3).toFixed(1)}">${fmt(v)}</text>`;
    }
    // 日期刻度
    const xi = [0, Math.floor(n / 3), Math.floor(2 * n / 3), n - 1].filter((v, i, a) => a.indexOf(v) === i);
    const xLabels = xi.map(i =>
      `<text x="${X(i).toFixed(1)}" y="${H - 3}" text-anchor="${i === 0 ? 'start' : i === n - 1 ? 'end' : 'middle'}">${rows[i].date.slice(5)}</text>`).join('');

    // 蜡烛
    const candles = rows.map((r, i) => {
      const o = Number(r.open), c = Number(r.close), h = Number(r.high), l = Number(r.low);
      const isUp = c >= o;
      const col = isUp ? up : down;
      const x = X(i);
      const yo = Y(o), yc = Y(c), yh = Y(h), yl = Y(l);
      const top = Math.min(yo, yc), bh = Math.max(1, Math.abs(yc - yo));
      return `<line x1="${x.toFixed(1)}" y1="${yh.toFixed(1)}" x2="${x.toFixed(1)}" y2="${yl.toFixed(1)}" stroke="${col}" stroke-width="1"></line>`
        + `<rect x="${(x - cw / 2).toFixed(1)}" y="${top.toFixed(1)}" width="${cw.toFixed(1)}" height="${bh.toFixed(1)}" fill="${col}"></rect>`;
    }).join('');

    // 成交量
    let volSvg = '';
    if (showVol) {
      const volTop = mainBot + gap, volBot = H - padB;
      const maxV = Math.max(...rows.map(r => Number(r.volume) || 0)) || 1;
      volSvg = rows.map((r, i) => {
        const h = (Number(r.volume) || 0) / maxV * (volBot - volTop);
        const col = (Number(r.close) >= Number(r.open)) ? up : down;
        return `<rect x="${(X(i) - cw / 2).toFixed(1)}" y="${(volBot - h).toFixed(1)}" width="${cw.toFixed(1)}" height="${Math.max(0.5, h).toFixed(1)}" fill="${col}" opacity="0.45"></rect>`;
      }).join('');
      volSvg += `<line x1="${padL}" y1="${volTop}" x2="${W - padR}" y2="${volTop}" stroke="${grid}" stroke-width="1" opacity="0.5"></line>`;
    }

    el.innerHTML = `<svg viewBox="0 0 ${W} ${H}" preserveAspectRatio="none" role="img">
      ${g}${candles}${volSvg}${xLabels}
      <line id="hl" stroke="var(--muted)" stroke-width="1" stroke-dasharray="3 3" style="display:none"></line>
      <rect id="ov" x="${padL}" y="${mainTop}" width="${plotW}" height="${H - mainTop - padB}" fill="transparent"></rect>
    </svg>`;

    const svg = el.querySelector('svg');
    const ov = el.querySelector('#ov');
    const hl = el.querySelector('#hl');
    const tip = _tip();
    ov.addEventListener('mousemove', e => {
      const r = svg.getBoundingClientRect();
      const relX = (e.clientX - r.left) / r.width * W;
      let i = Math.round((relX - padL) / (plotW || 1) * (n - 1));
      i = Math.max(0, Math.min(n - 1, i));
      const x = X(i);
      hl.setAttribute('x1', x); hl.setAttribute('x2', x);
      hl.setAttribute('y1', mainTop); hl.setAttribute('y2', H - padB);
      hl.style.display = '';
      const rw = rows[i];
      const ref = i > 0 ? Number(rows[i - 1].close) : Number(rw.open);
      const chg = Number(rw.close) - ref;
      const pct = ref ? chg / ref * 100 : 0;
      const cls = chg >= 0 ? 'up' : 'down';
      tip.innerHTML = `<b>${rw.date}</b><br>开 ${App.fmtNum(rw.open)}　高 ${App.fmtNum(rw.high)}<br>低 ${App.fmtNum(rw.low)}　收 ${App.fmtNum(rw.close)}`
        + `<br><span class="${cls}">涨跌 ${App.fmtNum(chg)} (${App.fmtPct(pct)})</span>　量 ${App.fmtNum(rw.volume, 0)}`;
      tip.style.left = (e.clientX + 12) + 'px';
      tip.style.top = (e.clientY - 10) + 'px';
      tip.style.opacity = '1';
    });
    ov.addEventListener('mouseleave', () => { hl.style.display = 'none'; tip.style.opacity = '0'; });
    _bindResize(el, () => candle(el, rows, opts));
  }

  // ---------------- 响应式 ----------------
  const _rs = new WeakMap();
  function _bindResize(el, fn) {
    if (_rs.has(el)) return;
    _rs.set(el, true);
    let t;
    window.addEventListener('resize', () => { clearTimeout(t); t = setTimeout(fn, 150); });
  }

  return { line, donut, candle };
})();
