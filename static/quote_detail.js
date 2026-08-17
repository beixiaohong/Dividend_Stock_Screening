// quote_detail.js —— 股票 / 指数 详情共用逻辑（券商式行情详情）
const QuoteDetail = (() => {
  let type = 'stock';        // 'stock' | 'index'
  let symbol = '';
  let name = '';

  function init(opts) {
    type = opts.type || 'stock';
    const p = new URLSearchParams(location.search);
    symbol = (p.get('symbol') || opts.symbol || '').trim();
    App.mount('home');
    if (!symbol) {
      const body = document.getElementById('detail-body');
      if (body) body.innerHTML = '<div class="empty">缺少 symbol 参数</div>';
      return;
    }
    load();
  }

  async function load() {
    try {
      const q = await App.api('/market/quote?symbol=' + encodeURIComponent(symbol));
      name = q.name || symbol;
      renderHead(q);
      loadKline(60);
    } catch (e) {
      const body = document.getElementById('detail-body');
      if (body) body.innerHTML = '<div class="empty">' + App.escapeHtml(e.message) + '</div>';
    }
  }

  function renderHead(q) {
    const chg = q.change_amount || 0;
    const pct = q.change_pct || 0;
    const cls = App.chgClass(chg);
    const head = document.getElementById('detail-head');
    if (!head) return;
    const bar = head.querySelector('.chg-bar');
    if (bar) bar.style.background = cls === 'up' ? 'var(--up)' : cls === 'down' ? 'var(--down)' : 'var(--flat)';

    const nm = head.querySelector('.dh-name');
    if (nm) nm.innerHTML = App.escapeHtml(q.name || symbol)
      + ' <span class="tag">' + (type === 'index' ? '指数' : '股票') + '</span>';
    const code = head.querySelector('.dh-code');
    if (code) code.textContent = q.code + (q.source ? ' · 数据 ' + q.source : '');

    const hero = head.querySelector('.price-hero');
    if (hero) { hero.textContent = App.fmtNum(q.price); hero.className = 'price-hero ' + cls; }
    const chgEl = head.querySelector('.price-chg');
    if (chgEl) {
      chgEl.innerHTML = (chg >= 0 ? '+' : '') + App.fmtNum(chg) + '　' + App.fmtPct(pct)
        + '　<span class="muted">今开 ' + App.fmtNum(q.open) + ' · 昨收 ' + App.fmtNum(q.prev_close) + '</span>';
      chgEl.className = 'price-chg ' + cls;
    }

    const actions = head.querySelector('.dh-actions');
    if (actions) {
      if (type === 'stock') {
        actions.innerHTML = '<button class="btn" onclick="QuoteDetail.trade(\'buy\')">买入</button>'
          + '<button class="btn danger" onclick="QuoteDetail.trade(\'sell\')">卖出</button>';
      } else {
        actions.innerHTML = '<span class="pill">指数不可直接交易</span>';
      }
    }

    const kpis = [
      ['今开', App.fmtNum(q.open)],
      ['最高', App.fmtNum(q.high)],
      ['最低', App.fmtNum(q.low)],
      ['昨收', App.fmtNum(q.prev_close)],
      ['成交量', fmtVol(q.volume)],
      ['成交额', fmtAmt(q.amount)],
    ];
    if (type === 'stock') {
      kpis.push(['换手率', q.turnover_rate != null ? q.turnover_rate + '%' : '--']);
      kpis.push(['市盈率(TTM)', q.pe != null ? App.fmtNum(q.pe) : '--']);
      kpis.push(['市净率', q.pb != null ? App.fmtNum(q.pb) : '--']);
    }
    const grid = document.getElementById('kpi-grid');
    if (grid) grid.innerHTML = kpis.map(([k, v]) =>
      `<div class="kpi"><div class="k">${k}</div><div class="v">${v}</div></div>`).join('');
  }

  function fmtVol(v) {
    if (v == null || isNaN(v)) return '--';
    if (v >= 1e8) return (v / 1e8).toFixed(2) + '亿';
    if (v >= 1e4) return (v / 1e4).toFixed(2) + '万';
    return App.fmtNum(v, 0);
  }
  function fmtAmt(v) {
    if (v == null || isNaN(v)) return '--';
    if (v >= 1e8) return (v / 1e8).toFixed(2) + '亿元';
    if (v >= 1e4) return (v / 1e4).toFixed(2) + '万元';
    return App.fmtNum(v, 0) + '元';
  }

  async function loadKline(count) {
    document.querySelectorAll('[data-k]').forEach(b => {
      b.classList.toggle('active', Number(b.dataset.k) === Number(count));
    });
    const el = document.getElementById('kline-chart');
    if (!el) return;
    try {
      const kl = await App.api('/market/kline?symbol=' + encodeURIComponent(symbol) + '&count=' + count);
      if (!kl || !kl.length) { el.innerHTML = '<div class="empty">暂无K线数据</div>'; return; }
      Charts.candle(el, kl, { height: 320, valueFmt: v => App.fmtNum(v) });
    } catch (e) {
      el.innerHTML = '<div class="empty">' + App.escapeHtml(e.message) + '</div>';
    }
  }

  function trade(side) {
    const code = symbol.replace(/^(sh|sz)/i, '');
    location.href = '/sim?code=' + encodeURIComponent(code) + '&mt=on&side=' + side
      + '&name=' + encodeURIComponent(name || '');
  }

  return { init, loadKline, trade };
})();
