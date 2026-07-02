// ─── 모달 UX (바깥 클릭 닫힘 방지 + × 닫기 버튼 자동 주입) ────────────────────
(function initModalsUX() {
  // FR-1: 바깥(.modal-overlay) 클릭으로 닫히지 않도록 — 캡처 단계에서 페이지 핸들러 차단
  document.addEventListener('click', function (e) {
    const t = e.target;
    if (t && t.classList && t.classList.contains('modal-overlay')) {
      e.stopImmediatePropagation();
    }
  }, true);

  // FR-2: 모든 .modal-box 우측 상단에 × 닫기 버튼 주입
  function injectCloseButtons() {
    document.querySelectorAll('.modal-box').forEach(function (box) {
      if (box.querySelector('.modal-close-x')) return;
      const btn = document.createElement('button');
      btn.type = 'button';
      btn.className = 'modal-close-x';
      btn.title = '닫기';
      btn.setAttribute('aria-label', '닫기');
      btn.textContent = '✕';
      btn.addEventListener('click', function () {
        const ov = box.closest('.modal-overlay');
        if (ov) ov.classList.remove('open');
      });
      if (getComputedStyle(box).position === 'static') box.style.position = 'relative';
      box.insertBefore(btn, box.firstChild);
    });
  }
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', injectCloseButtons);
  else injectCloseButtons();
})();

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

// ─── 리스트 기간 조회 헬퍼 (기본 최근 1개월) ───────────────────────────────
function _ymd(d) { return d.toISOString().slice(0, 10); }
function fillDefaultRange(fromId, toId, opts) {
  opts = opts || {};
  const to = new Date();
  const from = new Date();
  if (opts.weeks) from.setDate(from.getDate() - 7 * opts.weeks);
  else from.setMonth(from.getMonth() - (opts.months || 1));
  const f = document.getElementById(fromId);
  const t = document.getElementById(toId);
  if (f && !f.value) f.value = _ymd(from);
  if (t && !t.value) t.value = _ymd(to);
}

// ─── 클라이언트 페이지네이션 (페이지당 pageSize행 + 이전/다음) ──────────────
function makePager(pageSize, renderFn, pagerElId) {
  let items = [], page = 1;
  const pages = () => Math.max(1, Math.ceil(items.length / pageSize));
  function render() {
    if (page > pages()) page = pages();
    const start = (page - 1) * pageSize;
    renderFn(items.slice(start, start + pageSize));
    const el = document.getElementById(pagerElId);
    if (!el) return;
    if (items.length <= pageSize) { el.innerHTML = ''; return; }
    el.innerHTML =
      `<button class="btn btn-secondary" data-pg="prev" style="padding:3px 10px;font-size:12px;">◀ 이전</button>`
      + `<span style="font-size:12px;color:var(--text-muted);margin:0 10px;">${start + 1}–${Math.min(start + pageSize, items.length)} / ${items.length}</span>`
      + `<button class="btn btn-secondary" data-pg="next" style="padding:3px 10px;font-size:12px;">다음 ▶</button>`;
    el.querySelector('[data-pg=prev]').onclick = () => { if (page > 1) { page--; render(); } };
    el.querySelector('[data-pg=next]').onclick = () => { if (page < pages()) { page++; render(); } };
  }
  return { set(newItems) { items = newItems || []; page = 1; render(); } };
}

// ─── 사번 CSV → {사번:이름} 맵 해석 ──────────────────────────────────────────
async function resolveUsernames(csv) {
  const ids = (csv || '').split(',').map(s => s.trim()).filter(Boolean);
  if (!ids.length) return {};
  const res = await apiFetch('/api/resource/users/resolve?usernames=' + encodeURIComponent(ids.join(',')));
  const list = (res && res.ok) ? await res.json() : [];
  const map = {};
  list.forEach(u => { map[u.username] = u.name; });
  return map;
}

// ─── 멤버(사용자) 다중 선택 피커 — 사번/성명 검색 → 칩 ──────────────────────
function makeMemberPicker(root) {
  if (!root) return { getCsv: () => '', count: () => 0, setCsv() {}, clear() {} };
  const esc = (s) => s == null ? '' : String(s).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
  root.classList.add('member-picker');
  root.innerHTML =
    '<div class="mp-chips"></div>'
    + '<input class="mp-input form-input" placeholder="사번/성명 검색하여 추가" autocomplete="new-password">'
    + '<div class="mp-dd" style="display:none;"></div>';
  const chipsEl = root.querySelector('.mp-chips');
  const input = root.querySelector('.mp-input');
  const dd = root.querySelector('.mp-dd');
  let selected = [];   // {username, name}
  let timer;

  function renderChips() {
    chipsEl.innerHTML = selected.map((m, i) => {
      const showName = m.name && m.name !== m.username;
      return `<span class="mp-chip">${esc(m.name || m.username)}${showName ? ` <small>(${esc(m.username)})</small>` : ''} <a data-i="${i}" title="제거">×</a></span>`;
    }).join('');
    chipsEl.querySelectorAll('a[data-i]').forEach(a => a.onclick = () => { selected.splice(+a.dataset.i, 1); renderChips(); });
  }
  function add(m) {
    if (m.username && !selected.some(x => x.username === m.username)) { selected.push(m); renderChips(); }
    input.value = ''; dd.style.display = 'none';
  }
  input.addEventListener('input', () => {
    clearTimeout(timer);
    const q = input.value.trim();
    if (q.length < 1) { dd.style.display = 'none'; return; }
    timer = setTimeout(async () => {
      const res = await apiFetch('/api/resource/users/lookup?q=' + encodeURIComponent(q));
      const list = (res && res.ok) ? await res.json() : [];
      if (!list.length) { dd.innerHTML = '<div class="mp-opt mp-empty">검색 결과 없음</div>'; dd.style.display = 'block'; return; }
      dd.innerHTML = list.map(u =>
        `<div class="mp-opt" data-u="${esc(u.username)}" data-n="${esc(u.name || '')}">${esc(u.name || u.username)} <small>${esc(u.username)}${u.department ? ' · ' + esc(u.department) : ''}</small></div>`).join('');
      dd.style.display = 'block';
      dd.querySelectorAll('.mp-opt[data-u]').forEach(o => o.onclick = () => add({ username: o.dataset.u, name: o.dataset.n || o.dataset.u }));
    }, 250);
  });
  document.addEventListener('click', e => { if (!root.contains(e.target)) dd.style.display = 'none'; });

  return {
    getCsv: () => selected.map(m => m.username).join(','),
    count: () => selected.length,
    setCsv: (csv) => {
      selected = (csv || '').split(',').map(s => s.trim()).filter(Boolean).map(u => ({ username: u, name: u }));
      renderChips();
      resolveUsernames(csv).then(map => { selected.forEach(m => { if (map[m.username]) m.name = map[m.username]; }); renderChips(); });
    },
    clear: () => { selected = []; renderChips(); input.value = ''; dd.style.display = 'none'; },
  };
}
function dateRangeParams(fromId, toId, params) {
  const f = document.getElementById(fromId);
  const t = document.getElementById(toId);
  if (f && f.value) params.set('date_from', f.value);
  if (t && t.value) params.set('date_to', t.value);
  return params;
}

// ─── 자원 신청/배분 공통: 산정서 한도 배너 ─────────────────────────────────
function renderCapBanner(el, cap) {
  if (!el) return;
  if (!cap) { el.innerHTML = '한도 조회 실패'; el.style.background = '#fef2f2'; el.style.borderColor = '#fecaca'; return; }
  if (!cap.has_approved_estimate) {
    el.innerHTML = '⚠️ <b>승인된 용량 산정서가 없습니다.</b> 산정서 작성·승인 후 신청할 수 있습니다.';
    el.style.background = '#fef3c7'; el.style.borderColor = '#fde68a';
    return;
  }
  el.innerHTML = `산정서 한도 <b>${cap.peak_vcpu} vCPU / ${cap.peak_mem} GB</b> · 남은 <b style="color:#0d9488;">${cap.remain_vcpu} vCPU / ${cap.remain_mem} GB</b>`;
  el.style.background = '#f0fdfa'; el.style.borderColor = '#99f6e4';
}
async function loadCapBanner(projectId, elId) {
  // 오토스케일링 전제 — '산정서 한도' 개념 제거(/capacity 폐지). 배너 숨김(하위 템플릿 호환 no-op).
  const el = document.getElementById(elId);
  if (el) el.style.display = 'none';
}

// ─── 클릭 복사(ITSM 가이드 등 <pre> 텍스트 → 클립보드 + 토스트) ──────────────
function copyPre(preId, toastId) {
  const pre = document.getElementById(preId);
  if (!pre) return;
  const text = pre.textContent || '';
  const done = () => {
    const t = document.getElementById(toastId);
    if (t) { t.style.display = 'block'; setTimeout(() => { t.style.display = 'none'; }, 1800); }
  };
  if (navigator.clipboard && navigator.clipboard.writeText) {
    navigator.clipboard.writeText(text).then(done).catch(() => { _fallbackCopy(text); done(); });
  } else { _fallbackCopy(text); done(); }
}
function _fallbackCopy(text) {
  const ta = document.createElement('textarea');
  ta.value = text; ta.style.position = 'fixed'; ta.style.opacity = '0';
  document.body.appendChild(ta); ta.select();
  try { document.execCommand('copy'); } catch { /* ignore */ }
  ta.remove();
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
