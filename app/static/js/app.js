// ─── Auth ─────────────────────────────────────────────────────────────────
const Auth = {
  getToken() { return localStorage.getItem('token'); },
  setToken(t) { localStorage.setItem('token', t); },
  clear() { localStorage.removeItem('token'); localStorage.removeItem('user'); },
  isLoggedIn() { return !!this.getToken(); },
  getUser() { return JSON.parse(localStorage.getItem('user') || 'null'); },
  setUser(u) { localStorage.setItem('user', JSON.stringify(u)); },
};

// ─── API fetch ────────────────────────────────────────────────────────────
async function apiFetch(path, options = {}) {
  const token = Auth.getToken();
  const headers = { 'Content-Type': 'application/json', ...options.headers };
  if (token) headers['Authorization'] = `Bearer ${token}`;
  const res = await fetch(path, { ...options, headers });
  if (res.status === 401) { logout(); return null; }
  return res;
}

function logout() {
  Auth.clear();
  window.location.href = '/login';
}

// 사용자가 명시적으로 로그아웃 클릭 시 — 감사 로그 기록 후 로그아웃
async function userLogout() {
  try {
    await apiFetch('/api/access-log', {
      method: 'POST',
      body: JSON.stringify({ path: window.location.pathname, action: 'logout' }),
    });
  } catch { /* best-effort */ }
  logout();
}

// 현재 페이지(메뉴) 접속을 감사 로그로 기록 (best-effort)
async function logAccess() {
  try {
    await apiFetch('/api/access-log', {
      method: 'POST',
      body: JSON.stringify({ path: window.location.pathname, action: 'view' }),
    });
  } catch { /* best-effort */ }
}

// ─── Sidebar toggle / 폭 ───────────────────────────────────────────────────
function clampW(w) { return Math.max(180, Math.min(360, w)); }

// 레일이면 인라인 --sidebar-width 제거(레일 규칙이 적용되도록), 확장이면 저장폭 적용
function applySidebarWidth() {
  const root = document.documentElement;
  if (document.body.classList.contains('sidebar-collapsed')) {
    root.style.removeProperty('--sidebar-width');
  } else {
    const saved = parseInt(localStorage.getItem('sidebarWidth') || '', 10);
    if (saved) root.style.setProperty('--sidebar-width', clampW(saved) + 'px');
    else root.style.removeProperty('--sidebar-width');
  }
}

function initSidebar() {
  const btn = document.getElementById('sidebarToggle');
  if (localStorage.getItem('sidebarCollapsed') === '1') {
    document.body.classList.add('sidebar-collapsed');
  }
  applySidebarWidth();
  if (btn) {
    btn.addEventListener('click', () => {
      const collapsed = document.body.classList.toggle('sidebar-collapsed');
      localStorage.setItem('sidebarCollapsed', collapsed ? '1' : '0');
      applySidebarWidth();
    });
  }
}

// 드래그로 사이드바 폭 조절(확장 모드 전용) + 영속화
function initSidebarResize() {
  const sidebar = document.getElementById('sidebar');
  const resizer = document.getElementById('sidebarResizer');
  if (!sidebar || !resizer) return;
  let startX = 0, startW = 0;
  function onMove(e) {
    document.documentElement.style.setProperty('--sidebar-width', clampW(startW + (e.clientX - startX)) + 'px');
  }
  function onUp() {
    document.body.classList.remove('resizing');
    document.removeEventListener('mousemove', onMove);
    document.removeEventListener('mouseup', onUp);
    const px = parseInt(getComputedStyle(document.documentElement).getPropertyValue('--sidebar-width'), 10);
    if (px) localStorage.setItem('sidebarWidth', px);
  }
  resizer.addEventListener('mousedown', (e) => {
    if (document.body.classList.contains('sidebar-collapsed')) return;
    startX = e.clientX; startW = sidebar.offsetWidth;
    document.body.classList.add('resizing');
    document.addEventListener('mousemove', onMove);
    document.addEventListener('mouseup', onUp);
    e.preventDefault();
  });
}

// 레일 모드 아이콘 hover 시 메뉴명 풍선 툴팁(JS — overflow 회피)
function initRailTooltips() {
  const sidebar = document.getElementById('sidebar');
  if (!sidebar) return;
  let tip = document.querySelector('.rail-tooltip');
  if (!tip) { tip = document.createElement('div'); tip.className = 'rail-tooltip'; document.body.appendChild(tip); }
  sidebar.addEventListener('mouseover', (e) => {
    if (!document.body.classList.contains('sidebar-collapsed')) return;
    const el = e.target.closest('.sidebar-item, .sidebar-subitem, .sidebar-group-btn');
    if (!el) { tip.classList.remove('show'); return; }
    const label = el.querySelector('.s-label');
    if (!label) return;
    const r = el.getBoundingClientRect();
    tip.textContent = label.textContent.trim();
    tip.style.left = (r.right + 8) + 'px';
    tip.style.top = (r.top + r.height / 2) + 'px';
    tip.style.transform = 'translateY(-50%)';
    tip.classList.add('show');
  });
  sidebar.addEventListener('mouseleave', () => tip.classList.remove('show'));
}

// 헤더 사용자명 주입
function renderHeaderUser(user) {
  const el = document.getElementById('hu-name');
  if (el && user) el.textContent = user.name || user.username;
}

// ─── Accordion toggle ─────────────────────────────────────────────────────
function toggleGroup(id) {
  const grp = document.getElementById(id);
  if (!grp) return;
  const isOpen = grp.classList.toggle('open');
  localStorage.setItem('menu_' + id, isOpen ? '1' : '0');
}

function restoreAccordionStates() {
  const groups = ['grp-project', 'grp-data', 'grp-analysis', 'grp-resource', 'grp-mgmt'];
  groups.forEach(id => {
    const grp = document.getElementById(id);
    if (!grp) return;
    const saved = localStorage.getItem('menu_' + id);
    if (saved !== null) {
      const isOpen = saved === '1';
      grp.classList.toggle('open', isOpen);
    }
  });
}

// ─── Admin 메뉴 표시 ─────────────────────────────────────────────────────
function initAdminMenu() {
  const user = Auth.getUser();
  if (user && user.role === 'admin') {
    ['nav-notice', 'grp-resource', 'grp-mgmt'].forEach(id => {
      const el = document.getElementById(id);
      if (el) el.style.display = '';
    });
  }
}

// ─── Feature Permissions ─────────────────────────────────────────────────
window._myPermissions = null;

async function loadMyPermissions() {
  if (window._myPermissions !== null) return window._myPermissions;
  try {
    const res = await apiFetch('/api/auth/me/permissions');
    window._myPermissions = (res && res.ok) ? await res.json() : [];
  } catch {
    window._myPermissions = [];
  }
  return window._myPermissions;
}

function hasPermission(feature) {
  return (window._myPermissions || []).includes(feature);
}

// ─── 비밀번호 변경 (본인, 자율) ─────────────────────────────────────────────
function openChangePwModal() {
  const modal = document.getElementById('changePwModal');
  if (!modal) return;
  ['cp-current', 'cp-new', 'cp-confirm'].forEach(id => {
    const e = document.getElementById(id); if (e) e.value = '';
  });
  modal.classList.add('open');
}

function closeChangePwModal() {
  const modal = document.getElementById('changePwModal');
  if (modal) modal.classList.remove('open');
}

async function submitChangePassword() {
  const cur = document.getElementById('cp-current').value;
  const nw  = document.getElementById('cp-new').value;
  const cf  = document.getElementById('cp-confirm').value;
  if (!cur || !nw) { alert('현재 비밀번호와 새 비밀번호를 입력하세요.'); return; }
  if (nw !== cf) { alert('새 비밀번호 확인이 일치하지 않습니다.'); return; }

  const res = await apiFetch('/api/auth/change-password', {
    method: 'POST',
    body: JSON.stringify({ current_password: cur, new_password: nw }),
  });
  if (!res) return;
  if (res.ok) {
    closeChangePwModal();
    alert('비밀번호가 변경되었습니다.');
  } else {
    const err = await res.json().catch(() => ({}));
    alert(err.detail || '비밀번호 변경에 실패했습니다.');
  }
}

// ─── DOMContentLoaded ─────────────────────────────────────────────────────
document.addEventListener('DOMContentLoaded', () => {
  if (window.location.pathname === '/login') return;

  if (!Auth.isLoggedIn()) {
    window.location.href = '/login';
    return;
  }

  const user = Auth.getUser();
  renderHeaderUser(user);

  initSidebar();
  initSidebarResize();
  initRailTooltips();
  restoreAccordionStates();
  initAdminMenu();
  logAccess();
});
