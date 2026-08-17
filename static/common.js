// common.js —— 模拟盘前端共享：登录态、API 调用、格式化
const App = (() => {
  const TOKEN_KEY = 'sim_token';
  const apiBase = '';  // 同源

  function getToken() { return localStorage.getItem(TOKEN_KEY) || ''; }
  function setToken(t) { localStorage.setItem(TOKEN_KEY, t); }
  function clearToken() { localStorage.removeItem(TOKEN_KEY); }
  function isLogin() { return !!getToken(); }

  async function api(path, opts = {}) {
    const headers = Object.assign({}, opts.headers || {});
    const token = getToken();
    if (token) headers['Authorization'] = 'Bearer ' + token;
    if (opts.body && !(opts.body instanceof FormData)) {
      headers['Content-Type'] = 'application/json';
    }
    let resp;
    try {
      resp = await fetch(apiBase + path, {
        method: opts.method || 'GET',
        headers,
        body: opts.body,
      });
    } catch (e) {
      throw new Error('网络错误：' + e.message);
    }
    if (resp.status === 401) {
      clearToken();
      throw new Error('登录已失效，请重新登录');
    }
    let data = null;
    try { data = await resp.json(); } catch (e) {}
    if (!resp.ok) {
      const detail = (data && data.detail) ? data.detail : ('请求失败(' + resp.status + ')');
      throw new Error(detail);
    }
    return data;
  }

  async function login(account, password) {
    const data = await api('/api/users/login', {
      method: 'POST',
      body: JSON.stringify({ account, password }),
    });
    if (data && data.access_token) setToken(data.access_token);
    return data;
  }

  async function register(account, password, nickname) {
    return api('/api/users/', {
      method: 'POST',
      body: JSON.stringify({ account, password, nickname: nickname || account }),
    });
  }

  function logout() { clearToken(); location.reload(); }

  // ---------- 格式化 ----------
  function fmtNum(v, d = 2) {
    if (v === null || v === undefined || isNaN(v)) return '--';
    return Number(v).toLocaleString('zh-CN', { minimumFractionDigits: d, maximumFractionDigits: d });
  }
  function fmtPct(v) {
    if (v === null || v === undefined || isNaN(v)) return '--';
    const s = v > 0 ? '+' : '';
    return s + Number(v).toFixed(2) + '%';
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

  function toast(msg) {
    let el = document.querySelector('.toast');
    if (!el) { el = document.createElement('div'); el.className = 'toast'; document.body.appendChild(el); }
    el.textContent = msg;
    el.classList.add('show');
    setTimeout(() => el.classList.remove('show'), 2200);
  }

  // 渲染已登录用户态到顶部（若页面有 #auth-slot）
  function renderAuth() {
    const slot = document.getElementById('auth-slot');
    if (!slot) return;
    if (isLogin()) {
      slot.innerHTML = '<span class="muted">已登录</span> <button class="btn-sm ghost" onclick="App.logout()">退出</button>';
    } else {
      slot.innerHTML = '<a href="/home">行情</a> <a href="/sim">模拟</a> <a href="/admin">后台</a>';
    }
  }

  return {
    api, login, register, logout, getToken, isLogin, clearToken,
    fmtNum, fmtPct, chgClass, fmtTime, toast, renderAuth,
  };
})();
