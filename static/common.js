// common.js —— 模拟盘前端共享：主题 / 顶栏壳层 / 登录态 / API / 格式化
const App = (() => {
  const TOKEN_KEY = 'sim_token';
  const USER_KEY = 'sim_user';
  const THEME_KEY = 'sim_theme';
  const apiBase = '';

  // ---------------- 主题 ----------------
  function getTheme() { return localStorage.getItem(THEME_KEY) || 'light'; }
  function applyTheme(t) {
    document.documentElement.setAttribute('data-theme', t);
    const btn = document.getElementById('theme-toggle');
    if (btn) btn.textContent = (t === 'dark') ? '☀️' : '🌙';
  }
  function setTheme(t) { localStorage.setItem(THEME_KEY, t); applyTheme(t); }
  function toggleTheme() { setTheme(getTheme() === 'dark' ? 'light' : 'dark'); window.dispatchEvent(new Event('themechange')); }

  // ---------------- 顶栏壳层 ----------------
  function mount(active) {
    applyTheme(getTheme());
    const shell = document.createElement('header');
    shell.className = 'topbar';
    shell.innerHTML = `
      <div class="brand" onclick="location.href='/home'">
        <span class="mark">股</span><span>模拟盘</span>
      </div>
      <nav class="nav">
        <a href="/home" data-nav="home">行情中心</a>
        <a href="/sim" data-nav="sim">模拟交易</a>
        <a href="/positions" data-nav="positions">我的持仓</a>
        <a href="/trades" data-nav="trades">交易记录</a>
        <a href="/admin" data-nav="admin">后台管理</a>
      </nav>
      <div class="top-actions">
        <button class="icon-btn" id="theme-toggle" title="切换浅色/深色">🌙</button>
        <span id="auth-slot"></span>
      </div>`;
    document.body.insertBefore(shell, document.body.firstChild);
    const link = shell.querySelector('[data-nav="' + active + '"]');
    if (link) link.classList.add('active');
    shell.querySelector('#theme-toggle').addEventListener('click', toggleTheme);
    renderAuth();
  }

  // ---------------- 登录态 ----------------
  function getToken() { return localStorage.getItem(TOKEN_KEY) || ''; }
  function setToken(t) { localStorage.setItem(TOKEN_KEY, t); }
  function setUser(u) { if (u) localStorage.setItem(USER_KEY, u); }
  function getUser() { return localStorage.getItem(USER_KEY) || ''; }
  function clearToken() { localStorage.removeItem(TOKEN_KEY); localStorage.removeItem(USER_KEY); }
  function isLogin() { return !!getToken(); }

  function renderAuth() {
    const slot = document.getElementById('auth-slot');
    if (!slot) return;
    if (isLogin()) {
      slot.innerHTML = '<span class="user-chip">' + escapeHtml(getUser() || '已登录') + '</span>'
        + ' <button class="btn sm ghost" onclick="App.logout()">退出</button>';
    } else {
      slot.innerHTML = '<a class="btn sm ghost" href="/home">行情</a>'
        + ' <a class="btn sm" href="/sim">登录</a>';
    }
  }

  // ---------------- API ----------------
  async function api(path, opts = {}) {
    const headers = Object.assign({}, opts.headers || {});
    const token = getToken();
    if (token) headers['Authorization'] = 'Bearer ' + token;
    if (opts.body && !(opts.body instanceof FormData)) headers['Content-Type'] = 'application/json';
    let resp;
    try {
      resp = await fetch(apiBase + path, { method: opts.method || 'GET', headers, body: opts.body });
    } catch (e) {
      throw new Error('网络错误：' + e.message);
    }
    if (resp.status === 401) { clearToken(); throw new Error('登录已失效，请重新登录'); }
    let data = null;
    try { data = await resp.json(); } catch (e) {}
    if (!resp.ok) {
      const detail = (data && data.detail) ? data.detail : ('请求失败(' + resp.status + ')');
      let msg = detail;
      if (Array.isArray(detail)) {
        // FastAPI 422 校验错误数组 -> 可读文案
        msg = detail.map(it => {
          const loc = (it.loc || []).filter(x => x !== 'body').join('.');
          const why = (it.type || '').replace(/_/g, ' ') || (it.msg || '');
          return (loc ? loc + ': ' : '') + (it.msg || why || '参数错误');
        }).join('；');
      }
      throw new Error(typeof msg === 'string' ? msg : JSON.stringify(msg));
    }
    return data;
  }

  async function login(account, password) {
    const data = await api('/api/users/login', { method: 'POST', body: JSON.stringify({ account, password }) });
    if (data && data.access_token) { setToken(data.access_token); setUser(account); }
    return data;
  }
  async function register(account, password, nickname) {
    return api('/api/users/', { method: 'POST', body: JSON.stringify({ account, password, nickname: nickname || account }) });
  }
  function logout() { clearToken(); location.reload(); }

  // ---------------- 行情搜索 ----------------
  async function search(q) {
    try { return await api('/market/search?q=' + encodeURIComponent(q)); }
    catch (e) { return []; }
  }

  // ---------------- 格式化 ----------------
  function fmtNum(v, d = 2) {
    if (v === null || v === undefined || isNaN(v)) return '--';
    return Number(v).toLocaleString('zh-CN', { minimumFractionDigits: d, maximumFractionDigits: d });
  }
  function fmtPct(v) {
    if (v === null || v === undefined || isNaN(v)) return '--';
    return (v > 0 ? '+' : '') + Number(v).toFixed(2) + '%';
  }
  function chgClass(v) {
    if (v === null || v === undefined || isNaN(v) || v === 0) return 'flat';
    return v > 0 ? 'up' : 'down';
  }
  function fmtTime(ts) {
    if (!ts) return '';
    const d = new Date(ts);
    const p = n => (n < 10 ? '0' + n : n);
    return d.getFullYear() + '-' + p(d.getMonth() + 1) + '-' + p(d.getDate()) + ' ' + p(d.getHours()) + ':' + p(d.getMinutes()) + ':' + p(d.getSeconds());
  }
  function escapeHtml(s) {
    return String(s).replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
  }

  // ---------------- toast ----------------
  function toast(msg) {
    let el = document.querySelector('.toast');
    if (!el) { el = document.createElement('div'); el.className = 'toast'; document.body.appendChild(el); }
    el.textContent = msg;
    el.classList.add('show');
    setTimeout(() => el.classList.remove('show'), 2200);
  }

  return {
    api, login, register, logout, getToken, isLogin, getUser, renderAuth, mount,
    search, fmtNum, fmtPct, chgClass, fmtTime, escapeHtml, toast,
    getTheme, setTheme, toggleTheme,
  };
})();
