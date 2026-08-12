const $ = (sel) => document.querySelector(sel);
const $$ = (sel) => [...document.querySelectorAll(sel)];

const AUTH_KEY = "ampcus_helpdesk_auth";
const CHAT_SESSION_KEY = "ampcus_chat_session_id";
const CHAT_SESSION_OWNER_KEY = "ampcus_chat_session_owner";

function formatApiError(err, fallback) {
  const detail = err?.detail;
  if (!detail) return fallback;
  if (typeof detail === "string") return detail;
  if (detail.message) {
    const extra = detail.duplicate_title
      ? ` (matches “${detail.duplicate_title}”)`
      : detail.duplicate_of
        ? ` (matches ${detail.duplicate_of})`
        : "";
    return `${detail.message}${extra}`;
  }
  try {
    return JSON.stringify(detail);
  } catch {
    return fallback;
  }
}

function getAuth() {
  try {
    return JSON.parse(localStorage.getItem(AUTH_KEY) || "null");
  } catch {
    return null;
  }
}

function setAuth(payload) {
  localStorage.setItem(AUTH_KEY, JSON.stringify(payload));
}

function clearAuth() {
  localStorage.removeItem(AUTH_KEY);
}

function currentRole() {
  return getAuth()?.user?.role || "";
}

function currentName() {
  return getAuth()?.user?.name || getAuth()?.user?.email || "there";
}

function logout(message) {
  stopNotificationPolling();
  closeNotifyPanel();
  closeAccountMenu?.();
  clearAuth();
  try {
    localStorage.removeItem(CHAT_SESSION_KEY);
    localStorage.removeItem(CHAT_SESSION_OWNER_KEY);
  } catch {
    /* ignore */
  }
  clearChatUi?.();
  showLogin(message);
}

function showLogin(message) {
  const shell = $("#app-shell");
  const login = $("#login-screen");
  if (shell) shell.hidden = true;
  if (login) login.hidden = false;
  document.body.classList.add("is-login");
  const err = $("#login-error");
  if (!err) return;
  if (message) {
    err.hidden = false;
    err.textContent = message;
  } else {
    err.hidden = true;
    err.textContent = "";
  }
}

function userInitials(name, email) {
  const parts = String(name || "")
    .trim()
    .split(/\s+/)
    .filter(Boolean);
  if (parts.length >= 2) {
    return (parts[0][0] + parts[parts.length - 1][0]).toUpperCase();
  }
  if (parts.length === 1 && parts[0].length) {
    return parts[0].slice(0, 2).toUpperCase();
  }
  const local = String(email || "").split("@")[0] || "?";
  return local.slice(0, 2).toUpperCase();
}

function applyRoleGates() {
  const role = currentRole();
  $$(".nav-btn[data-roles]").forEach((btn) => {
    const allowed = (btn.dataset.roles || "").split(",").map((r) => r.trim());
    btn.hidden = !allowed.includes(role);
  });
  $$("[data-admin-only]").forEach((el) => {
    el.hidden = role !== "admin";
  });
  const user = getAuth()?.user;
  const avatar = $("#header-avatar");
  if (avatar) {
    avatar.textContent = userInitials(user?.name, user?.email);
    avatar.title = user ? `${user.name || "Account"} · ${user.email || ""}` : "Account";
  }
  const nameEl = $("#account-menu-name");
  const emailEl = $("#account-menu-email");
  const roleElMenu = $("#account-menu-role");
  if (nameEl) nameEl.textContent = user?.name || "Account";
  if (emailEl) emailEl.textContent = user?.email || "—";
  if (roleElMenu) roleElMenu.textContent = user?.role || role || "—";
  const roleEl = $("#chat-user-role");
  if (roleEl) {
    roleEl.textContent = role || "user";
  }
}

const SIDEBAR_KEY = "ampcus_sidebar_expanded";
let _sidebarToggleBound = false;
let _sidebarPeekTimer = null;

function setSidebarPeek(open) {
  const shell = $("#app-shell");
  if (!shell || shell.classList.contains("sidebar-expanded")) {
    shell?.classList.remove("sidebar-peek");
    return;
  }
  shell.classList.toggle("sidebar-peek", !!open);
}

function setSidebarExpanded(expanded) {
  const shell = $("#app-shell");
  const toggle = $("#sidebar-toggle");
  if (!shell) return;
  shell.classList.toggle("sidebar-expanded", !!expanded);
  shell.classList.remove("sidebar-peek");
  localStorage.setItem(SIDEBAR_KEY, expanded ? "1" : "0");
  if (toggle) {
    toggle.setAttribute("aria-expanded", expanded ? "true" : "false");
    toggle.title = expanded ? "Minimize sidebar" : "Expand sidebar";
  }
}

function initSidebarToggle() {
  const saved = localStorage.getItem(SIDEBAR_KEY);
  setSidebarExpanded(saved === "1");
  if (_sidebarToggleBound) return;
  _sidebarToggleBound = true;

  const toggle = $("#sidebar-toggle");
  const sidebar = $("#app-sidebar");
  const shell = $("#app-shell");

  const clearPeekTimer = () => {
    if (_sidebarPeekTimer) {
      clearTimeout(_sidebarPeekTimer);
      _sidebarPeekTimer = null;
    }
  };

  const scheduleHidePeek = () => {
    clearPeekTimer();
    _sidebarPeekTimer = setTimeout(() => setSidebarPeek(false), 160);
  };

  toggle?.addEventListener("click", () => {
    clearPeekTimer();
    setSidebarExpanded(!shell?.classList.contains("sidebar-expanded"));
  });

  toggle?.addEventListener("mouseenter", () => {
    if (shell?.classList.contains("sidebar-expanded")) return;
    clearPeekTimer();
    setSidebarPeek(true);
  });
  toggle?.addEventListener("mouseleave", () => {
    if (shell?.classList.contains("sidebar-expanded")) return;
    scheduleHidePeek();
  });

  sidebar?.addEventListener("mouseenter", () => {
    if (shell?.classList.contains("sidebar-expanded")) return;
    clearPeekTimer();
    setSidebarPeek(true);
  });
  sidebar?.addEventListener("mouseleave", () => {
    if (shell?.classList.contains("sidebar-expanded")) return;
    scheduleHidePeek();
  });

  sidebar?.addEventListener("click", (e) => {
    if (shell?.classList.contains("sidebar-expanded")) return;
    const actionable = e.target.closest(".nav-btn, .sidebar-new-chat, .chat-session-open, .chat-session-more");
    if (!actionable) return;
    clearPeekTimer();
    setSidebarPeek(false);
  });
}

let _notifyItems = [];
let _notifyPollTimer = null;
let _notifyBound = false;

function canSeeNotifications() {
  return ["agent", "admin"].includes(currentRole());
}

function formatNotifyTime(iso) {
  if (!iso) return "";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "";
  return d.toLocaleString([], {
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}

function setNotifyBadge(count) {
  const badge = $("#header-notify-badge");
  if (!badge) return;
  if (!canSeeNotifications() || count <= 0) {
    badge.hidden = true;
    badge.textContent = "0";
    return;
  }
  badge.hidden = false;
  badge.textContent = count > 99 ? "99+" : String(count);
}

function notifyItemHtml(n, { compact = false } = {}) {
  const unread = !n.read_at;
  const sev = (n.severity || "") === "high" ? "sev-high" : "";
  return `<button type="button" class="notify-item${unread ? " unread" : ""}" data-notify-id="${escapeHtml(
    n.id
  )}" data-ticket-id="${escapeHtml(n.ticket_id || "")}" data-notify-kind="${escapeHtml(n.kind || "")}" data-reservation-id="${escapeHtml(n.reservation_id || "")}">
    <div class="notify-item-title">
      <span class="${sev}">${escapeHtml(n.title || "Ticket")}</span>
      <span class="time">${escapeHtml(formatNotifyTime(n.created_at))}</span>
    </div>
    <p class="notify-item-body">${escapeHtml(n.body || "")}${
      compact ? "" : ""
    }</p>
  </button>`;
}

function renderNotifyPanelList() {
  const list = $("#header-notify-list");
  if (!list) return;
  if (!_notifyItems.length) {
    list.innerHTML = `<p class="empty notify-empty">No notifications yet.</p>`;
    return;
  }
  list.innerHTML = _notifyItems.map((n) => notifyItemHtml(n)).join("");
  list.querySelectorAll(".notify-item").forEach((btn) => {
    btn.addEventListener("click", async () => {
      const id = btn.dataset.notifyId;
      if (id) {
        try {
          await api(`/notifications/${id}/read`, { method: "POST" });
        } catch (_) {
          /* ignore */
        }
      }
      closeNotifyPanel();
      if (btn.dataset.notifyKind === "reservation_pending") {
        switchView("reservations");
      } else {
        switchView("tickets");
      }
      refreshNotifications();
    });
  });
}

function renderDashNotifyList() {
  const list = $("#dash-notify-list");
  if (!list) return;
  if (!canSeeNotifications()) {
    list.innerHTML = `<p class="empty" style="padding:20px;box-shadow:none">Sign in as admin/agent to see ticket alerts.</p>`;
    return;
  }
  const items = _notifyItems.slice(0, 8);
  if (!items.length) {
    list.innerHTML = `<p class="empty" style="padding:20px;box-shadow:none">No ticket alerts yet.</p>`;
    return;
  }
  list.innerHTML = items.map((n) => notifyItemHtml(n)).join("");
  list.querySelectorAll(".notify-item").forEach((btn) => {
    btn.addEventListener("click", async () => {
      const id = btn.dataset.notifyId;
      if (id) {
        try {
          await api(`/notifications/${id}/read`, { method: "POST" });
        } catch (_) {
          /* ignore */
        }
      }
      if (btn.dataset.notifyKind === "reservation_pending") {
        switchView("reservations");
      } else {
        switchView("tickets");
      }
      refreshNotifications();
    });
  });
}

async function refreshNotifications() {
  if (!canSeeNotifications() || !getAuth()?.access_token) {
    setNotifyBadge(0);
    _notifyItems = [];
    renderNotifyPanelList();
    renderDashNotifyList();
    return;
  }
  try {
    const [listRes, countRes] = await Promise.all([
      api("/notifications?limit=40"),
      api("/notifications/unread-count"),
    ]);
    if (!listRes.ok || !countRes.ok) return;
    _notifyItems = await listRes.json();
    const { unread } = await countRes.json();
    setNotifyBadge(unread || 0);
    renderNotifyPanelList();
    renderDashNotifyList();
  } catch (e) {
    console.warn("notifications refresh failed", e);
  }
}

function closeNotifyPanel() {
  const panel = $("#header-notify-panel");
  const btn = $("#header-notify");
  if (panel) panel.hidden = true;
  if (btn) btn.setAttribute("aria-expanded", "false");
}

function toggleNotifyPanel() {
  const panel = $("#header-notify-panel");
  const btn = $("#header-notify");
  if (!panel || !btn) return;
  const open = panel.hidden;
  panel.hidden = !open;
  btn.setAttribute("aria-expanded", open ? "true" : "false");
  if (open) refreshNotifications();
}

function stopNotificationPolling() {
  if (_notifyPollTimer) {
    clearInterval(_notifyPollTimer);
    _notifyPollTimer = null;
  }
}

function initNotifications() {
  if (!canSeeNotifications()) {
    setNotifyBadge(0);
    closeNotifyPanel();
    stopNotificationPolling();
    return;
  }
  refreshNotifications();
  stopNotificationPolling();
  _notifyPollTimer = setInterval(() => {
    if (document.hidden) return;
    refreshNotifications();
  }, 15000);

  if (_notifyBound) return;
  _notifyBound = true;

  $("#header-notify-read-all")?.addEventListener("click", async (e) => {
    e.stopPropagation();
    try {
      await api("/notifications/read-all", { method: "POST" });
      await refreshNotifications();
    } catch (err) {
      alert(err.message || String(err));
    }
  });
  $("#header-notify-open-tickets")?.addEventListener("click", (e) => {
    e.stopPropagation();
    closeNotifyPanel();
    switchView("tickets");
  });
  document.addEventListener("click", (e) => {
    const wrap = e.target.closest?.(".header-notify-wrap");
    if (!wrap) closeNotifyPanel();
  });
}

let _headerChromeBound = false;

function closeAccountMenu() {
  const menu = $("#header-account-menu");
  const btn = $("#header-avatar");
  if (menu) menu.hidden = true;
  if (btn) btn.setAttribute("aria-expanded", "false");
}

function toggleAccountMenu() {
  const menu = $("#header-account-menu");
  const btn = $("#header-avatar");
  if (!menu || !btn) return;
  const open = menu.hidden;
  menu.hidden = !open;
  btn.setAttribute("aria-expanded", open ? "true" : "false");
  if (open) closeNotifyPanel();
}

function initHeaderChrome() {
  if (_headerChromeBound) return;
  _headerChromeBound = true;

  const goHome = () => switchView("chat");
  $("#header-brand")?.addEventListener("click", goHome);
  $("#header-brand")?.addEventListener("keydown", (e) => {
    if (e.key === "Enter" || e.key === " ") {
      e.preventDefault();
      goHome();
    }
  });

  $("#header-notify")?.addEventListener("click", (e) => {
    e.stopPropagation();
    closeAccountMenu();
    const role = currentRole();
    if (!["agent", "admin"].includes(role)) {
      alert("No notifications right now. Ask a question in Chat if you need help.");
      return;
    }
    toggleNotifyPanel();
  });

  $("#header-help")?.addEventListener("click", () => {
    closeAccountMenu();
    alert(
      "Ampcus Helpdesk tips:\n• Use Chat for HR, IT, Compliance, and Legal questions.\n• Agents/admins work all tickets from the Tickets board (resolve or promote to KB).\n• New tickets appear in the bell and on the Dashboard.\n• Sign out from the account menu (top-right avatar)."
    );
  });

  $("#header-settings")?.addEventListener("click", () => {
    closeAccountMenu();
    alert("Settings are not available in this demo yet.");
  });

  $("#header-avatar")?.addEventListener("click", (e) => {
    e.stopPropagation();
    toggleAccountMenu();
  });

  $("#logout-btn")?.addEventListener("click", (e) => {
    e.stopPropagation();
    closeAccountMenu();
    logout();
  });

  document.addEventListener("click", (e) => {
    if (!e.target.closest?.("#header-account-wrap")) closeAccountMenu();
  });
}

async function enterApp() {
  const login = $("#login-screen");
  const shell = $("#app-shell");
  if (login) login.hidden = true;
  if (shell) shell.hidden = false;
  document.body.classList.remove("is-login");
  ensureSessionOwnedByCurrentUser();
  applyRoleGates();
  initSidebarToggle();
  initHeaderChrome();
  initNotifications();
  await loadSessionList();
  switchView("chat");
}

async function api(path, options = {}) {
  const auth = getAuth();
  const headers = {
    ...(options.headers || {}),
  };
  if (!(options.body instanceof FormData) && options.body && !headers["Content-Type"]) {
    headers["Content-Type"] = "application/json";
  }
  if (auth?.access_token) {
    headers.Authorization = `Bearer ${auth.access_token}`;
  }
  const res = await fetch(path, { ...options, headers });
  if (res.status === 401) {
    logout("Session expired — please sign in again.");
    throw new Error("Unauthorized");
  }
  if (res.status === 403) {
    const err = await res.json().catch(() => ({}));
    const msg = formatApiError(err, "You do not have permission for that action.");
    throw new Error(msg);
  }
  return res;
}

function switchView(name) {
  const role = currentRole();
  const btn = $(`.nav-btn[data-view="${name}"]`);
  if (btn?.hidden) {
    name = "chat";
  }
  if (name === "dashboard" && !["agent", "admin"].includes(role)) {
    name = "chat";
  }
  if ((name === "insights" || name === "attribution" || name === "nlp-logs" || name === "onboarding" || name === "reservations") && role !== "admin") {
    name = "chat";
  }
  $$(".view").forEach((v) => v.classList.remove("active"));
  $$(".nav-btn").forEach((b) => b.classList.toggle("active", b.dataset.view === name));
  const view = document.getElementById(`view-${name}`);
  if (view) view.classList.add("active");
  if (name === "dashboard") loadStats();
  if (name === "kb") loadKnowledgeBase();
  if (name === "workspace") loadWorkspace();
  if (name === "tickets") loadTickets();
  if (name === "insights") loadInsights();
  if (name === "attribution") loadUserAttribution();
  if (name === "nlp-logs") loadNlpLogs();
  if (name === "onboarding") loadOnboarding();
  if (name === "reservations") loadReservationsAdmin();
  if (name === "chat") {
    loadSessionList();
    requestAnimationFrame(() => $("#chat-input")?.focus());
  }
}

$$(".nav-btn, [data-view].btn-primary").forEach((el) => {
  el.addEventListener("click", () => {
    if (el.dataset.view) switchView(el.dataset.view);
  });
});

$("#login-form")?.addEventListener("submit", async (e) => {
  e.preventDefault();
  const email = $("#login-email").value.trim();
  const password = $("#login-password").value;
  const err = $("#login-error");
  const btn = $("#login-submit");
  err.hidden = true;
  btn.disabled = true;
  btn.textContent = "Signing in…";
  try {
    const res = await fetch("/auth/login", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ email, password }),
    });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) {
      throw new Error(formatApiError(data, "Invalid email or password"));
    }
    setAuth({
      access_token: data.access_token,
      user: data.user,
    });
    $("#login-password").value = "";
    await enterApp();
  } catch (ex) {
    err.hidden = false;
    err.textContent = ex.message || "Sign in failed";
  } finally {
    btn.disabled = false;
    btn.textContent = "Sign in";
  }
});

function barList(container, data, colors) {
  if (!container) return;
  const entries = Object.entries(data || {});
  if (!entries.length) {
    container.innerHTML = `<p class="empty" style="padding:20px;box-shadow:none">No data yet — ask a question in Chat.</p>`;
    return;
  }
  const max = Math.max(...entries.map(([, v]) => v), 1);
  container.innerHTML = entries
    .sort((a, b) => b[1] - a[1])
    .map(([label, value]) => {
      const pct = Math.round((value / max) * 100);
      const color = colors?.[label];
      return `<div class="bar-row">
        <span>${label}</span>
        <div class="bar-track"><div class="bar-fill" style="width:${pct}%;${color ? `background:${color};` : ""}"></div></div>
        <strong>${value}</strong>
      </div>`;
    })
    .join("");
}

const DEPT_COLORS = {
  hr: "#6c4dff",
  it: "#3dcfb0",
  compliance: "#f0b429",
  legal: "#e2556f",
  unknown: "#9aa0b5",
};

function formatHours(h) {
  if (h == null || Number.isNaN(Number(h))) return "—";
  const n = Number(h);
  if (n < 1) return `${Math.round(n * 60)}m`;
  if (n < 48) return `${n.toFixed(1)}h`;
  return `${(n / 24).toFixed(1)}d`;
}

function counterToBarData(items) {
  const out = {};
  (items || []).forEach((row) => {
    out[row.key] = row.count;
  });
  return out;
}

function downsampleSeries(series, maxPoints) {
  const data = series || [];
  if (data.length <= maxPoints) return data;
  const step = Math.ceil(data.length / maxPoints);
  return data.filter((_, i) => i % step === 0 || i === data.length - 1);
}

function trendText(pct, { invert = false } = {}) {
  if (pct == null || Number.isNaN(Number(pct))) return { text: "—", cls: "" };
  const n = Number(pct);
  const up = n > 0;
  const good = invert ? !up : up;
  const arrow = up ? "↑" : n < 0 ? "↓" : "→";
  return {
    text: `${arrow} ${Math.abs(n)}% WoW`,
    cls: n === 0 ? "" : good ? "up" : "down",
  };
}

function prepCanvas(canvas, cssH = 150) {
  if (!canvas) return null;
  const ctx = canvas.getContext("2d");
  const dpr = window.devicePixelRatio || 1;
  const cssW = canvas.clientWidth || 640;
  canvas.width = cssW * dpr;
  canvas.height = cssH * dpr;
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  ctx.clearRect(0, 0, cssW, cssH);
  return { ctx, cssW, cssH };
}

function drawSparkline(canvas, values, color) {
  if (!canvas) return;
  const ctx = canvas.getContext("2d");
  const dpr = window.devicePixelRatio || 1;
  const w = canvas.clientWidth || 120;
  const h = 28;
  canvas.width = w * dpr;
  canvas.height = h * dpr;
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  ctx.clearRect(0, 0, w, h);
  const data = values || [];
  if (data.length < 2) return;
  const max = Math.max(...data, 1);
  ctx.beginPath();
  ctx.strokeStyle = color;
  ctx.lineWidth = 1.6;
  data.forEach((v, i) => {
    const x = (i / (data.length - 1)) * (w - 2) + 1;
    const y = h - 3 - ((Number(v) || 0) / max) * (h - 8);
    if (i === 0) ctx.moveTo(x, y);
    else ctx.lineTo(x, y);
  });
  ctx.stroke();
}

function drawAreaLine(canvas, series, key, color, emptyMsg, cssH = 150) {
  const prep = prepCanvas(canvas, cssH);
  if (!prep) return;
  const { ctx, cssW, cssH: H } = prep;
  const pad = { t: 10, r: 8, b: 18, l: 28 };
  const w = cssW - pad.l - pad.r;
  const h = H - pad.t - pad.b;
  const data = series || [];
  if (!data.length) {
    ctx.fillStyle = "#98a2b3";
    ctx.font = "12px Manrope, sans-serif";
    ctx.fillText(emptyMsg || "No data yet.", pad.l, H / 2);
    return;
  }
  const maxVal = Math.max(...data.map((d) => Number(d[key]) || 0), 1);
  const points = data.map((d, i) => ({
    x: pad.l + (i / Math.max(data.length - 1, 1)) * w,
    y: pad.t + h - ((Number(d[key]) || 0) / maxVal) * h,
  }));
  ctx.beginPath();
  points.forEach((p, i) => (i ? ctx.lineTo(p.x, p.y) : ctx.moveTo(p.x, p.y)));
  ctx.lineTo(points[points.length - 1].x, pad.t + h);
  ctx.lineTo(points[0].x, pad.t + h);
  ctx.closePath();
  ctx.fillStyle = color + "22";
  ctx.fill();
  ctx.beginPath();
  points.forEach((p, i) => (i ? ctx.lineTo(p.x, p.y) : ctx.moveTo(p.x, p.y)));
  ctx.strokeStyle = color;
  ctx.lineWidth = 2;
  ctx.stroke();
  ctx.fillStyle = "#98a2b3";
  ctx.font = "10px Manrope, sans-serif";
  ctx.fillText(String(Math.round(maxVal)), 4, pad.t + 8);
}

function drawDualLine(canvas, series, keyA, keyB, colorA, colorB, emptyMsg, cssH = 150) {
  const prep = prepCanvas(canvas, cssH);
  if (!prep) return;
  const { ctx, cssW, cssH: H } = prep;
  const pad = { t: 10, r: 8, b: 18, l: 28 };
  const w = cssW - pad.l - pad.r;
  const h = H - pad.t - pad.b;
  const data = series || [];
  if (!data.length) {
    ctx.fillStyle = "#98a2b3";
    ctx.font = "12px Manrope, sans-serif";
    ctx.fillText(emptyMsg || "No data yet.", pad.l, H / 2);
    return;
  }
  const maxVal = Math.max(
    ...data.map((d) => Math.max(Number(d[keyA]) || 0, Number(d[keyB]) || 0)),
    1
  );
  const draw = (key, color) => {
    ctx.beginPath();
    data.forEach((d, i) => {
      const x = pad.l + (i / Math.max(data.length - 1, 1)) * w;
      const y = pad.t + h - ((Number(d[key]) || 0) / maxVal) * h;
      if (i === 0) ctx.moveTo(x, y);
      else ctx.lineTo(x, y);
    });
    ctx.strokeStyle = color;
    ctx.lineWidth = 2;
    ctx.stroke();
  };
  draw(keyA, colorA);
  draw(keyB, colorB);
  ctx.fillStyle = "#98a2b3";
  ctx.font = "10px Manrope, sans-serif";
  ctx.fillText(String(Math.round(maxVal)), 4, pad.t + 8);
}

function drawDonut(canvas, items, colors) {
  if (!canvas) return;
  const ctx = canvas.getContext("2d");
  const dpr = window.devicePixelRatio || 1;
  const size = 180;
  canvas.width = size * dpr;
  canvas.height = size * dpr;
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  ctx.clearRect(0, 0, size, size);
  const data = (items || []).filter((x) => (x.count || 0) > 0);
  const total = data.reduce((s, x) => s + (x.count || 0), 0) || 1;
  const cx = size / 2;
  const cy = size / 2;
  const r = 68;
  const rw = 18;
  let angle = -Math.PI / 2;
  if (!data.length) {
    ctx.beginPath();
    ctx.arc(cx, cy, r, 0, Math.PI * 2);
    ctx.strokeStyle = "#eef0f3";
    ctx.lineWidth = rw;
    ctx.stroke();
    return;
  }
  data.forEach((row) => {
    const slice = ((row.count || 0) / total) * Math.PI * 2;
    ctx.beginPath();
    ctx.arc(cx, cy, r, angle, angle + slice);
    ctx.strokeStyle = colors[row.key] || "#98a2b3";
    ctx.lineWidth = rw;
    ctx.lineCap = "butt";
    ctx.stroke();
    angle += slice;
  });
}

function dayLabel(iso) {
  if (!iso) return "Earlier";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "Earlier";
  const today = new Date();
  const yday = new Date();
  yday.setDate(today.getDate() - 1);
  const same = (a, b) =>
    a.getFullYear() === b.getFullYear() &&
    a.getMonth() === b.getMonth() &&
    a.getDate() === b.getDate();
  if (same(d, today)) return "Today";
  if (same(d, yday)) return "Yesterday";
  return d.toLocaleDateString([], { month: "short", day: "numeric" });
}

async function loadOpsHealth() {
  if (!["agent", "admin"].includes(currentRole())) return;
  const ops = await api("/stats/ops").then((r) => r.json());
  const k = ops.kpis || {};
  const insights = ops.insights || {};
  const trends = ops.trends || {};
  const sparks = ops.sparklines || {};
  const health = ops.health || {};

  const toneOpen =
    (k.open_tickets || 0) > 10 ? "bad" : (k.open_tickets || 0) > 5 ? "warn" : "good";
  const toneSla =
    k.sla_compliance_pct == null
      ? "warn"
      : k.sla_compliance_pct >= 90
        ? "good"
        : k.sla_compliance_pct >= 70
          ? "warn"
          : "bad";
  const toneMttr =
    k.mttr_hours == null
      ? "info"
      : k.mttr_hours > 48
        ? "bad"
        : k.mttr_hours > 24
          ? "warn"
          : "good";

  $("#ops-kpi-open")?.setAttribute("data-tone", toneOpen);
  $("#ops-kpi-sla")?.setAttribute("data-tone", toneSla);
  $("#ops-kpi-mttr")?.setAttribute("data-tone", toneMttr);
  $("#ops-kpi-resolved")?.setAttribute("data-tone", "good");
  $("#ops-kpi-created")?.setAttribute("data-tone", "info");

  if ($("#ops-health-score")) $("#ops-health-score").textContent = health.score ?? "—";
  if ($("#ops-health-status")) $("#ops-health-status").textContent = health.status || "—";
  $("#ops-health-ring")?.setAttribute("data-tone", health.tone || "good");

  if ($("#ops-open")) $("#ops-open").textContent = k.open_tickets ?? 0;
  if ($("#ops-open-trend")) {
    $("#ops-open-trend").textContent = `${k.open_todo || 0} todo · ${
      k.open_in_progress || 0
    } active · ${k.high_open || 0} high`;
  }
  if ($("#ops-created-30")) $("#ops-created-30").textContent = k.created_last_30d ?? 0;
  if ($("#ops-resolved-30")) $("#ops-resolved-30").textContent = k.resolved_last_30d ?? 0;

  const createdTrend = trendText(k.created_wow_pct);
  if ($("#ops-created-trend")) {
    $("#ops-created-trend").textContent = `${createdTrend.text} · +${
      k.created_today || 0
    } today`;
    $("#ops-created-trend").className = `ops-kpi-trend ${createdTrend.cls}`;
  }
  const resolvedTrend = trendText(k.resolved_wow_pct);
  if ($("#ops-resolved-trend")) {
    $("#ops-resolved-trend").textContent = `${resolvedTrend.text} · +${
      k.resolved_today || 0
    } today`;
    $("#ops-resolved-trend").className = `ops-kpi-trend ${resolvedTrend.cls}`;
  }

  if ($("#ops-sla")) {
    $("#ops-sla").textContent =
      k.sla_compliance_pct == null ? "—" : `${k.sla_compliance_pct}%`;
  }
  if ($("#ops-sla-sub")) {
    $("#ops-sla-sub").textContent = `target ≤ ${ops.sla_hours || 24}h`;
  }
  const slaRing = $("#ops-sla-ring");
  if (slaRing) {
    const pct = Math.max(0, Math.min(100, Number(k.sla_compliance_pct) || 0));
    slaRing.style.background = `conic-gradient(${
      toneSla === "good" ? "#12b76a" : toneSla === "warn" ? "#f79009" : "#f04438"
    } ${pct}%, #eef0f3 0)`;
    slaRing.style.border = "0";
    slaRing.style.mask = "radial-gradient(farthest-side, transparent calc(100% - 4px), #000 0)";
    slaRing.style.webkitMask =
      "radial-gradient(farthest-side, transparent calc(100% - 4px), #000 0)";
  }

  if ($("#ops-mttr")) $("#ops-mttr").textContent = formatHours(k.mttr_hours);
  if ($("#ops-mttr-sub")) {
    $("#ops-mttr-sub").textContent = `avg ${formatHours(k.avg_resolution_hours)}`;
  }

  drawSparkline($("#ops-spark-open"), sparks.backlog || [], "#f04438");
  drawSparkline($("#ops-spark-created"), sparks.created || [], "#2e90fa");
  drawSparkline($("#ops-spark-resolved"), sparks.resolved || [], "#12b76a");

  drawAreaLine(
    $("#ops-chart-backlog"),
    downsampleSeries(trends.backlog_90d, 40),
    "backlog",
    "#f04438",
    "No backlog history yet.",
    160
  );
  drawDualLine(
    $("#ops-chart-created-resolved"),
    downsampleSeries(trends.created_vs_resolved_90d, 40),
    "created",
    "resolved",
    "#2e90fa",
    "#12b76a",
    "No volume yet.",
    150
  );
  drawAreaLine(
    $("#ops-chart-resolution"),
    trends.resolution_time_weekly || [],
    "avg_hours",
    "#2e90fa",
    "No resolution samples yet.",
    150
  );
  drawDualLine(
    $("#ops-chart-throughput"),
    trends.throughput_weekly || [],
    "created",
    "resolved",
    "#2e90fa",
    "#12b76a",
    "No weekly throughput yet.",
    120
  );

  const statusMap = Object.fromEntries(
    (insights.by_status || []).map((r) => [r.key, r.count])
  );
  const funnel = $("#ops-status-funnel");
  if (funnel) {
    funnel.innerHTML = [
      ["open", "Open", statusMap.open || 0],
      ["assigned", "In Progress", statusMap.assigned || 0],
      ["resolved", "Done", statusMap.resolved || 0],
    ]
      .map(
        ([cls, label, count]) =>
          `<div class="ops-funnel-step is-${cls}"><strong>${count}</strong><span>${label}</span></div>`
      )
      .join("");
  }

  const priColors = { high: "#f04438", routine: "#12b76a", medium: "#f79009", low: "#98a2b3" };
  drawDonut($("#ops-chart-priority"), insights.by_priority || [], priColors);
  const priTotal = (insights.by_priority || []).reduce((s, r) => s + (r.count || 0), 0);
  if ($("#ops-priority-total")) $("#ops-priority-total").textContent = String(priTotal);
  const priLegend = $("#ops-priority-legend");
  if (priLegend) {
    priLegend.innerHTML = (insights.by_priority || [])
      .map((r) => {
        const pct = priTotal ? Math.round((r.count / priTotal) * 100) : 0;
        return `<span><i style="background:${priColors[r.key] || "#98a2b3"}"></i>${escapeHtml(
          r.key
        )} ${pct}%</span>`;
      })
      .join("");
  }

  const agingOrder = ["0-1d", "1-3d", "3-7d", "7-14d", "14d+"];
  const agingColors = {
    "0-1d": "#12b76a",
    "1-3d": "#2e90fa",
    "3-7d": "#f79009",
    "7-14d": "#f04438",
    "14d+": "#7a8699",
  };
  const agingMax = Math.max(...agingOrder.map((k) => (insights.aging || {})[k] || 0), 1);
  const agingRoot = $("#ops-aging-bars");
  if (agingRoot) {
    agingRoot.innerHTML = agingOrder
      .map((key) => {
        const n = (insights.aging || {})[key] || 0;
        const pct = Math.round((n / agingMax) * 100);
        return `<div class="ops-stack-row"><span>${key}</span><div class="track"><div class="fill" style="width:${pct}%;background:${agingColors[key]}"></div></div><strong>${n}</strong></div>`;
      })
      .join("");
  }

  barList($("#ops-assignee-bars"), counterToBarData(insights.by_assignee), DEPT_COLORS);

  const tbody = $("#ops-open-tbody");
  if (tbody) {
    const rows = insights.aging_tickets || [];
    tbody.innerHTML = rows.length
      ? rows
          .map((t) => {
            const sev = (t.severity || "routine").toLowerCase();
            return `<tr>
              <td><strong>${escapeHtml(t.key || "")}</strong><div class="ops-act-meta">${escapeHtml(
                (t.question || "").slice(0, 48)
              )}</div></td>
              <td><span class="ops-pri ${escapeHtml(sev)}">${escapeHtml(sev)}</span></td>
              <td>${formatHours(t.age_hours)}</td>
              <td>${escapeHtml(t.owner || "—")}</td>
              <td>${escapeHtml(t.status || "—")}</td>
            </tr>`;
          })
          .join("")
      : `<tr><td colspan="5">No open tickets.</td></tr>`;
  }

  const actRoot = $("#ops-activity");
  if (actRoot) {
    const items = ops.activity || [];
    if (!items.length) {
      actRoot.innerHTML = `<p class="empty" style="padding:12px;box-shadow:none">No recent activity.</p>`;
    } else {
      const groups = {};
      items.slice(0, 24).forEach((a) => {
        const label = dayLabel(a.at);
        (groups[label] ||= []).push(a);
      });
      actRoot.innerHTML = Object.entries(groups)
        .map(([label, rows]) => {
          const list = rows
            .map((a) => {
              const high = (a.severity || "") === "high";
              const cls = a.kind === "resolved" ? "resolved" : high ? "high" : "";
              return `<div class="ops-act-item">
                <div class="ops-act-dot ${cls}"></div>
                <div>
                  <div>${a.kind === "resolved" ? "Resolved" : "Opened"} <strong>${escapeHtml(
                    a.key || ""
                  )}</strong></div>
                  <div class="ops-act-meta">${escapeHtml(a.question || "")}</div>
                </div>
              </div>`;
            })
            .join("");
          return `<div class="ops-day-group"><p class="ops-day-label">${escapeHtml(
            label
          )}</p>${list}</div>`;
        })
        .join("");
    }
  }
}

async function loadStats() {
  const [stats, health] = await Promise.all([
    api("/stats").then((r) => r.json()),
    fetch("/health").then((r) => r.json()),
  ]);

  if ($("#kpi-queries")) $("#kpi-queries").textContent = stats.total_queries;
  if ($("#kpi-queries-sub")) $("#kpi-queries-sub").textContent = `${stats.cache_misses} misses`;
  if ($("#kpi-cache")) $("#kpi-cache").textContent = `${stats.cache_hit_rate}%`;
  if ($("#kpi-cache-sub")) $("#kpi-cache-sub").textContent = `${stats.cache_hits} cache hits`;
  if ($("#kpi-tickets")) $("#kpi-tickets").textContent = stats.open_tickets;
  if ($("#kpi-tickets-sub")) {
    $("#kpi-tickets-sub").textContent = `${stats.unknown_tickets_created} unknown this session`;
  }
  if ($("#kpi-escalations")) {
    $("#kpi-escalations").textContent = stats.open_escalations ?? 0;
  }
  if ($("#kpi-escalations-sub")) {
    $("#kpi-escalations-sub").textContent = "high-severity HITL";
  }
  if ($("#kpi-esc-session")) {
    $("#kpi-esc-session").textContent = stats.escalated ?? 0;
  }
  if ($("#kpi-latency")) {
    $("#kpi-latency").textContent =
      stats.avg_latency_ms >= 1000
        ? `${(stats.avg_latency_ms / 1000).toFixed(1)}s`
        : `${Math.round(stats.avg_latency_ms)}ms`;
  }

  const provider = health.models?.provider || "—";
  if ($("#provider-pill")) $("#provider-pill").textContent = `LLM: ${provider}`;

  if ($("#dept-bars") && !$("#dept-bars").hidden) {
    barList($("#dept-bars"), stats.by_department, DEPT_COLORS);
  }

  const list = $("#recent-list");
  if (list && !list.hidden) {
    const recent = stats.recent || [];
    if (!recent.length) {
      list.innerHTML = `<p class="empty" style="padding:20px;box-shadow:none">No queries yet.</p>`;
    } else {
      list.innerHTML = recent
        .map((item) => {
          const tags = [
            `<span class="tag ${item.department === "unknown" ? "unknown" : ""}">${item.department}</span>`,
            item.escalated ? `<span class="tag escalation">escalated</span>` : "",
            item.cached ? `<span class="tag cached">cached</span>` : "",
          ]
            .filter(Boolean)
            .join(" ");
          return `<div class="recent-item">
          <div>
            <p>${escapeHtml(item.question || "(no text)")}</p>
            <small>${item.model_used || "—"} · ${item.latency_ms}ms</small>
          </div>
          <div>${tags}</div>
        </div>`;
        })
        .join("");
    }
  }
  renderDashNotifyList();
  if (canSeeNotifications()) refreshNotifications();
  try {
    await loadOpsHealth();
  } catch (e) {
    console.warn("ops health load failed", e);
  }
}

function escapeHtml(str) {
  return String(str)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;");
}

function truncateCheckpoint(text, max = 48) {
  const s = String(text || "").replace(/\s+/g, " ").trim();
  if (s.length <= max) return s || "Message";
  return s.slice(0, max - 1).trimEnd() + "…";
}

let _checkpointHoverTimer = null;

function userCheckpointBubbles() {
  return $$("#chat-messages .bubble.user").filter(
    (el) => !el.classList.contains("error") && el.dataset.checkpointId
  );
}

function closeCheckpointPanel() {
  const wrap = $("#chat-checkpoints");
  const panel = $("#chat-checkpoint-panel");
  const rail = $("#chat-checkpoint-rail");
  if (panel) panel.hidden = true;
  if (rail) rail.setAttribute("aria-expanded", "false");
  wrap?.classList.remove("is-open");
  if (_checkpointHoverTimer) {
    clearTimeout(_checkpointHoverTimer);
    _checkpointHoverTimer = null;
  }
}

function openCheckpointPanel() {
  const wrap = $("#chat-checkpoints");
  const panel = $("#chat-checkpoint-panel");
  const rail = $("#chat-checkpoint-rail");
  if (!panel || !rail || wrap?.hidden) return;
  if (_checkpointHoverTimer) {
    clearTimeout(_checkpointHoverTimer);
    _checkpointHoverTimer = null;
  }
  refreshCheckpoints();
  panel.hidden = false;
  rail.setAttribute("aria-expanded", "true");
  wrap?.classList.add("is-open");
}

function scheduleCloseCheckpointPanel(delay = 180) {
  if (_checkpointHoverTimer) clearTimeout(_checkpointHoverTimer);
  _checkpointHoverTimer = setTimeout(() => {
    _checkpointHoverTimer = null;
    closeCheckpointPanel();
  }, delay);
}

function jumpToCheckpoint(id) {
  const el = document.querySelector(
    `#chat-messages [data-checkpoint-id="${CSS.escape(id)}"]`
  );
  if (!el) return;
  const container = $("#chat-messages");
  if (container) {
    const top = el.offsetTop - 12;
    container.scrollTo({ top: Math.max(0, top), behavior: "smooth" });
  } else {
    el.scrollIntoView({ behavior: "smooth", block: "start" });
  }
  el.classList.add("checkpoint-flash");
  setTimeout(() => el.classList.remove("checkpoint-flash"), 900);
  closeCheckpointPanel();
  updateActiveCheckpointTick(id);
}

function updateActiveCheckpointTick(forcedId) {
  const bubbles = userCheckpointBubbles();
  if (!bubbles.length) return;
  let activeId = forcedId || null;
  if (!activeId) {
    const container = $("#chat-messages");
    const top = container ? container.getBoundingClientRect().top + 24 : 80;
    let best = bubbles[0];
    for (const b of bubbles) {
      const rect = b.getBoundingClientRect();
      if (rect.top <= top + 40) best = b;
    }
    if (container) {
      const nearBottom =
        container.scrollHeight - container.scrollTop - container.clientHeight < 48;
      if (nearBottom) best = bubbles[bubbles.length - 1];
    }
    activeId = best.dataset.checkpointId;
  }
  $$("#chat-checkpoint-rail .chat-checkpoint-tick").forEach((tick) => {
    tick.classList.toggle("active", tick.dataset.checkpointId === activeId);
  });
  $$("#chat-checkpoint-list .chat-checkpoint-item").forEach((item) => {
    item.classList.toggle("active", item.dataset.checkpointId === activeId);
  });
}

function refreshCheckpoints() {
  const wrap = $("#chat-checkpoints");
  const rail = $("#chat-checkpoint-rail");
  const list = $("#chat-checkpoint-list");
  const view = $("#view-chat");
  const panelWasOpen = Boolean($("#chat-checkpoint-panel") && !$("#chat-checkpoint-panel").hidden);
  if (!wrap || !rail || !list) return;

  const bubbles = userCheckpointBubbles();
  const show = Boolean(view?.classList.contains("chat-active") && bubbles.length >= 2);
  wrap.hidden = !show;
  if (!show) {
    closeCheckpointPanel();
    rail.innerHTML = "";
    list.innerHTML = "";
    return;
  }

  rail.innerHTML = bubbles
    .map(
      (b, i) =>
        `<span class="chat-checkpoint-tick${i === bubbles.length - 1 ? " active" : ""}" data-checkpoint-id="${escapeHtml(b.dataset.checkpointId)}"></span>`
    )
    .join("");

  list.innerHTML = bubbles
    .map((b, i) => {
      const label = truncateCheckpoint(b.textContent || "");
      return `<li><button type="button" class="chat-checkpoint-item${i === bubbles.length - 1 ? " active" : ""}" data-checkpoint-id="${escapeHtml(b.dataset.checkpointId)}" title="${escapeHtml(b.textContent || "")}">${escapeHtml(label)}</button></li>`;
    })
    .join("");

  updateActiveCheckpointTick();
  if (panelWasOpen) {
    const panel = $("#chat-checkpoint-panel");
    if (panel) panel.hidden = false;
    wrap.classList.add("is-open");
    rail.setAttribute("aria-expanded", "true");
  }
}

function initChatCheckpoints() {
  if (initChatCheckpoints._bound) return;
  initChatCheckpoints._bound = true;

  const wrap = $("#chat-checkpoints");

  wrap?.addEventListener("mouseenter", () => {
    if (wrap.hidden) return;
    openCheckpointPanel();
  });
  wrap?.addEventListener("mouseleave", () => {
    scheduleCloseCheckpointPanel();
  });

  // Keep open while moving between rail and panel
  $("#chat-checkpoint-panel")?.addEventListener("mouseenter", () => {
    if (_checkpointHoverTimer) {
      clearTimeout(_checkpointHoverTimer);
      _checkpointHoverTimer = null;
    }
  });

  $("#chat-checkpoint-rail")?.addEventListener("click", (e) => {
    e.stopPropagation();
    const tick = e.target.closest?.(".chat-checkpoint-tick");
    if (tick?.dataset.checkpointId) {
      jumpToCheckpoint(tick.dataset.checkpointId);
      return;
    }
    openCheckpointPanel();
  });

  $("#chat-checkpoint-list")?.addEventListener("click", (e) => {
    const item = e.target.closest?.(".chat-checkpoint-item");
    if (!item) return;
    e.stopPropagation();
    jumpToCheckpoint(item.dataset.checkpointId);
  });

  // Highlight the prompt under the pointer on the rail
  $("#chat-checkpoint-rail")?.addEventListener("mousemove", (e) => {
    const tick = e.target.closest?.(".chat-checkpoint-tick");
    if (!tick?.dataset.checkpointId) return;
    $$("#chat-checkpoint-list .chat-checkpoint-item").forEach((item) => {
      item.classList.toggle("active", item.dataset.checkpointId === tick.dataset.checkpointId);
    });
  });

  document.addEventListener("click", (e) => {
    if (e.target.closest?.("#chat-checkpoints")) return;
    closeCheckpointPanel();
  });

  $("#chat-messages")?.addEventListener("scroll", () => {
    if ($("#chat-checkpoints")?.hidden) return;
    updateActiveCheckpointTick();
  });
}

function addBubble(role, text, isError = false) {
  const el = document.createElement("div");
  el.className = `bubble ${role}${isError ? " error" : ""}`;
  el.textContent = text;
  if (role === "user" && !isError) {
    el.dataset.checkpointId = `cp_${Date.now().toString(36)}_${Math.random().toString(36).slice(2, 7)}`;
  }
  $("#chat-messages").appendChild(el);
  const container = $("#chat-messages");
  if (container) {
    container.scrollTo({ top: container.scrollHeight, behavior: "smooth" });
  }
  refreshCheckpoints();
  return el;
}

function addTicketConfirmBubble(text) {
  const el = document.createElement("div");
  el.className = "bubble bot ticket-confirm-bubble";
  const body = document.createElement("p");
  body.className = "ticket-confirm-text";
  body.textContent = text;
  el.appendChild(body);
  const actions = document.createElement("div");
  actions.className = "ticket-confirm-actions";
  const yesBtn = document.createElement("button");
  yesBtn.type = "button";
  yesBtn.className = "chip ticket-confirm-yes";
  yesBtn.textContent = "Yes, open ticket";
  yesBtn.addEventListener("click", () => confirmPendingTicket(true));
  const noBtn = document.createElement("button");
  noBtn.type = "button";
  noBtn.className = "chip ticket-confirm-no";
  noBtn.textContent = "No thanks";
  noBtn.addEventListener("click", () => confirmPendingTicket(false));
  actions.append(yesBtn, noBtn);
  el.appendChild(actions);
  $("#chat-messages").appendChild(el);
  const container = $("#chat-messages");
  if (container) {
    container.scrollTo({ top: container.scrollHeight, behavior: "smooth" });
  }
  refreshCheckpoints();
  return el;
}

const RES_CAL_WEEKDAYS = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"];

function formatResCalDate(iso) {
  if (!iso) return "—";
  try {
    const d = new Date(`${iso}T12:00:00`);
    return d.toLocaleDateString(undefined, { weekday: "short", month: "short", day: "numeric", year: "numeric" });
  } catch {
    return iso;
  }
}

function monthBounds(ym) {
  const [y, m] = ym.split("-").map(Number);
  const first = new Date(y, m - 1, 1);
  const last = new Date(y, m, 0);
  return { first, last, label: first.toLocaleDateString(undefined, { month: "long", year: "numeric" }) };
}

function addDaysIso(iso, n) {
  const d = new Date(`${iso}T12:00:00`);
  d.setDate(d.getDate() + n);
  return d.toISOString().slice(0, 10);
}

function addReservationCalendarBubble(_text, calendarData) {
  const el = document.createElement("div");
  el.className = "bubble bot reservation-calendar-bubble";
  const intro = document.createElement("p");
  intro.className = "res-cal-intro";
  intro.innerHTML = "<strong>Select Dates :</strong>";
  el.appendChild(intro);
  const widget = document.createElement("div");
  widget.className = "res-cal-widget";
  el.appendChild(widget);
  mountReservationCalendar(widget, calendarData);
  $("#chat-messages").appendChild(el);
  const container = $("#chat-messages");
  if (container) container.scrollTo({ top: container.scrollHeight, behavior: "smooth" });
  refreshCheckpoints();
  return el;
}

function mountReservationCalendar(container, data) {
  const state = {
    data,
    roomIdx: 0,
    month: (data.display_month || data.from_date?.slice(0, 7) || new Date().toISOString().slice(0, 7)),
    checkin: null,
    checkout: null,
    purpose: "Business travel",
    loading: false,
    error: "",
  };

  function dayMap(room) {
    const m = {};
    (room?.days || []).forEach((d) => { m[d.date] = d.status; });
    return m;
  }

  function room() {
    return state.data.rooms?.[state.roomIdx] || state.data.rooms?.[0];
  }

  function rangeAvailable(checkin, checkout) {
    const r = room();
    if (!r || !checkin || !checkout) return false;
    const map = dayMap(r);
    let d = checkin;
    while (d < checkout) {
      if ((map[d] || "available") !== "available") return false;
      d = addDaysIso(d, 1);
    }
    return true;
  }

  async function loadMonth(ym) {
    const { first, last } = monthBounds(ym);
    const padStart = addDaysIso(first.toISOString().slice(0, 10), -7);
    const padEnd = addDaysIso(last.toISOString().slice(0, 10), 7);
    state.loading = true;
    render();
    try {
      const q = new URLSearchParams({
        guesthouse_id: state.data.guesthouse_id,
        from_date: padStart,
        to_date: padEnd,
      });
      const res = await api(`/reservations/calendar?${q}`);
      if (res.ok) {
        const fresh = await res.json();
        state.data = { ...state.data, ...fresh, guesthouse_id: state.data.guesthouse_id };
        state.month = ym;
      }
    } catch (_) {
      state.error = "Could not refresh calendar.";
    } finally {
      state.loading = false;
      render();
    }
  }

  function onDayClick(iso, status) {
    if (state.loading) return;
    const today = new Date().toISOString().slice(0, 10);
    if (iso <= today) return;
    if (status !== "available") return;
    if (!state.checkin || (state.checkin && state.checkout)) {
      state.checkin = iso;
      state.checkout = null;
    } else if (iso <= state.checkin) {
      state.checkin = iso;
      state.checkout = null;
    } else {
      state.checkout = iso;
      if (!rangeAvailable(state.checkin, state.checkout)) {
        state.error = "Selected range includes unavailable dates.";
        state.checkout = null;
      } else {
        state.error = "";
      }
    }
    render();
  }

  async function confirmBooking() {
    if (state.loading || _askInFlight) return;
    const r = room();
    if (!r || !state.checkin || !state.checkout) {
      state.error = "Select check-in and check-out dates.";
      render();
      return;
    }
    if (!rangeAvailable(state.checkin, state.checkout)) {
      state.error = "Selected dates are no longer available.";
      render();
      return;
    }
    state.loading = true;
    state.error = "";
    render();
    try {
      const res = await api("/reservations", {
        method: "POST",
        body: JSON.stringify({
          room_id: r.room_id,
          checkin_date: state.checkin,
          checkout_date: state.checkout,
          purpose: state.purpose,
        }),
      });
      const body = await res.json().catch(() => ({}));
      if (!res.ok) {
        state.error = formatApiError(body, "Booking failed.");
        state.loading = false;
        render();
        return;
      }
      container.closest(".reservation-calendar-bubble")?.remove();
      addBubble(
        "bot",
        `Reservation submitted — ${body.confirmation_number || "confirmed"}.\n` +
          `${state.data.guesthouse_name} · Room ${r.room_number}\n` +
          `${formatResCalDate(state.checkin)} → ${formatResCalDate(state.checkout)}\n` +
          "HR will review shortly. You'll receive email updates."
      );
      if (canSeeNotifications()) refreshNotifications();
    } catch (err) {
      state.error = err.message || "Booking failed.";
      state.loading = false;
      render();
    }
  }

  function render() {
    const r = room();
    const map = dayMap(r);
    const { first, last, label } = monthBounds(state.month);
    const today = new Date().toISOString().slice(0, 10);

    const header = `<div class="res-cal-header">
      <span class="res-cal-title">${escapeHtml(state.data.guesthouse_name || "Guesthouse")}</span>
      <div class="res-cal-rooms">${(state.data.rooms || [])
        .map(
          (rm, i) =>
            `<button type="button" class="res-cal-room-btn${i === state.roomIdx ? " active" : ""}" data-room-idx="${i}">Room ${escapeHtml(rm.room_number)}</button>`
        )
        .join("")}</div>
    </div>`;

    const nav = `<div class="res-cal-nav">
      <button type="button" data-nav="prev" ${state.loading ? "disabled" : ""} aria-label="Previous month">‹</button>
      <span class="res-cal-month-label">${escapeHtml(label)}${state.loading ? " …" : ""}</span>
      <button type="button" data-nav="next" ${state.loading ? "disabled" : ""} aria-label="Next month">›</button>
    </div>`;

    const weekdays = `<div class="res-cal-weekdays">${RES_CAL_WEEKDAYS.map((d) => `<span>${d}</span>`).join("")}</div>`;

    const cells = [];
    const startPad = first.getDay();
    const daysInMonth = last.getDate();
    const totalSlots = Math.ceil((startPad + daysInMonth) / 7) * 7;
    for (let slot = 0; slot < totalSlots; slot++) {
      const day = slot - startPad + 1;
      if (day < 1 || day > daysInMonth) {
        cells.push('<div class="res-cal-day empty" aria-hidden="true"></div>');
        continue;
      }
      const iso = `${state.month}-${String(day).padStart(2, "0")}`;
      const status = map[iso] || (iso >= state.data.from_date && iso <= state.data.to_date ? "available" : "confirmed");
      const isPast = iso <= today;
      let cls = `res-cal-day ${status}`;
      if (isPast) cls += " past";
      if (iso === state.checkin || iso === state.checkout) cls += " selected";
      if (state.checkin && state.checkout && iso > state.checkin && iso < state.checkout) cls += " in-range";
      const disabled = isPast || status !== "available" || state.loading;
      cells.push(
        `<button type="button" class="${cls}" data-date="${iso}" data-status="${status}" ${disabled ? "disabled" : ""}>${day}</button>`
      );
    }

    const legend = `<div class="res-cal-legend">
      <span><i class="res-cal-swatch available"></i> Available</span>
      <span><i class="res-cal-swatch pending"></i> Awaiting confirmation</span>
      <span><i class="res-cal-swatch confirmed"></i> Confirmed / unavailable</span>
    </div>`;

    const sel = state.checkin
      ? `<p class="res-cal-selection">Check-in: <strong>${escapeHtml(formatResCalDate(state.checkin))}</strong>` +
        (state.checkout ? ` · Out: <strong>${escapeHtml(formatResCalDate(state.checkout))}</strong>` : " · pick check-out") +
        `</p>`
      : "";

    const err = state.error ? `<p class="res-cal-error">${escapeHtml(state.error)}</p>` : "";

    container.innerHTML =
      header +
      legend +
      nav +
      weekdays +
      `<div class="res-cal-grid">${cells.join("")}</div>` +
      `<div class="res-cal-footer">
        ${sel}
        <div class="res-cal-actions">
          <button type="button" class="btn-primary res-cal-confirm" ${state.loading ? "disabled" : ""}>Confirm reservation</button>
        </div>
      </div>` +
      err;

    container.querySelectorAll(".res-cal-room-btn").forEach((btn) => {
      btn.addEventListener("click", () => {
        state.roomIdx = Number(btn.dataset.roomIdx) || 0;
        state.checkin = null;
        state.checkout = null;
        state.error = "";
        render();
      });
    });

    container.querySelector('[data-nav="prev"]')?.addEventListener("click", () => {
      const [y, m] = state.month.split("-").map(Number);
      const prev = m === 1 ? `${y - 1}-12` : `${y}-${String(m - 1).padStart(2, "0")}`;
      loadMonth(prev);
    });
    container.querySelector('[data-nav="next"]')?.addEventListener("click", () => {
      const [y, m] = state.month.split("-").map(Number);
      const next = m === 12 ? `${y + 1}-01` : `${y}-${String(m + 1).padStart(2, "0")}`;
      loadMonth(next);
    });

    container.querySelectorAll(".res-cal-day[data-date]").forEach((btn) => {
      btn.addEventListener("click", () => onDayClick(btn.dataset.date, btn.dataset.status));
    });

    container.querySelector(".res-cal-confirm")?.addEventListener("click", confirmBooking);
  }

  render();
}

async function confirmPendingTicket(confirm) {
  if (_askInFlight) return;
  _askInFlight = true;
  const label = confirm ? "Yes, open ticket" : "No thanks";
  addBubble("user", label);
  addBubble("bot", confirm ? "Opening ticket…" : "Got it.");
  const thinking = $("#chat-messages").lastElementChild;
  try {
    const res = await api("/query", {
      method: "POST",
      body: JSON.stringify({
        question: "(confirm)",
        confirm_ticket: confirm,
        model_preference: selectedModelPreference(),
        session_id: getActiveSessionId(),
      }),
    });
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const data = await res.json();
    if (data.session_id) setActiveSessionId(data.session_id);
    thinking.remove();
    addBubble("bot", data.answer || (confirm ? "Ticket opened." : "Okay."));
    if (data.ticket_id) loadStats();
    loadSessionList();
  } catch (err) {
    thinking.remove();
    addBubble("bot", `Error: ${err.message}`, true);
  } finally {
    _askInFlight = false;
    $("#chat-input")?.focus();
  }
}

function enterChatActive() {
  const view = $("#view-chat");
  if (!view) return;
  view.classList.remove("chat-home");
  view.classList.add("chat-active");
  refreshCheckpoints();
}

function clearChatUi() {
  const msgs = $("#chat-messages");
  if (msgs) msgs.innerHTML = "";
  const view = $("#view-chat");
  if (view) {
    view.classList.add("chat-home");
    view.classList.remove("chat-active");
  }
  closeCheckpointPanel();
  closeDocSidePanel?.();
  removeDocOptionCards?.();
  _activeDocMeta = null;
  _docAskMode = false;
  setDocComposerPlaceholder?.(false);
  refreshCheckpoints();
}

function makeSessionId() {
  if (crypto?.randomUUID) return `sess_${crypto.randomUUID().replace(/-/g, "")}`;
  return `sess_${Date.now().toString(16)}${Math.random().toString(16).slice(2)}`;
}

function getActiveSessionId() {
  let id = localStorage.getItem(CHAT_SESSION_KEY);
  if (!id) {
    id = makeSessionId();
    localStorage.setItem(CHAT_SESSION_KEY, id);
  }
  return id;
}

function setActiveSessionId(id) {
  const sid = (id || "").trim() || makeSessionId();
  localStorage.setItem(CHAT_SESSION_KEY, sid);
  const email = (getAuth()?.user?.email || "").trim().toLowerCase();
  if (email) localStorage.setItem(CHAT_SESSION_OWNER_KEY, email);
  return sid;
}

function isStaleSessionError(err) {
  return /session belongs to another user/i.test(String(err?.message || err || ""));
}

/** If local session was created under a different login, start a fresh chat. */
function ensureSessionOwnedByCurrentUser() {
  const email = (getAuth()?.user?.email || "").trim().toLowerCase();
  if (!email) return;
  const owner = (localStorage.getItem(CHAT_SESSION_OWNER_KEY) || "").trim().toLowerCase();
  if (owner && owner !== email) {
    setActiveSessionId(makeSessionId());
    clearChatUi?.();
  } else {
    localStorage.setItem(CHAT_SESSION_OWNER_KEY, email);
    getActiveSessionId();
  }
}

const CHAT_META_KEY = "ampcus_chat_session_meta";
let _sessionMenuSid = null;
let _sessionMenuTitle = "";

function readSessionMeta() {
  try {
    return JSON.parse(localStorage.getItem(CHAT_META_KEY) || "{}") || {};
  } catch {
    return {};
  }
}

function writeSessionMeta(meta) {
  localStorage.setItem(CHAT_META_KEY, JSON.stringify(meta || {}));
}

function getSessionFlags(sessionId) {
  const row = readSessionMeta()[sessionId] || {};
  return { starred: !!row.starred, unread: !!row.unread };
}

function setSessionFlag(sessionId, key, value) {
  const meta = readSessionMeta();
  const row = { ...(meta[sessionId] || {}) };
  row[key] = !!value;
  meta[sessionId] = row;
  writeSessionMeta(meta);
}

function closeSessionMenu() {
  const menu = $("#chat-session-menu");
  if (menu) menu.hidden = true;
  $$("#chat-session-list .chat-session-item.menu-open").forEach((li) =>
    li.classList.remove("menu-open")
  );
  _sessionMenuSid = null;
  _sessionMenuTitle = "";
}

function openSessionMenu(anchor, sessionId, title) {
  const menu = $("#chat-session-menu");
  if (!menu || !anchor) return;
  closeSessionMenu();
  _sessionMenuSid = sessionId;
  _sessionMenuTitle = title || "";
  const flags = getSessionFlags(sessionId);
  const starLabel = menu.querySelector("[data-star-label]");
  const unreadLabel = menu.querySelector("[data-unread-label]");
  if (starLabel) starLabel.textContent = flags.starred ? "Unstar" : "Star";
  if (unreadLabel) unreadLabel.textContent = flags.unread ? "Mark as read" : "Mark as unread";
  menu.hidden = false;
  const rect = anchor.getBoundingClientRect();
  const menuW = menu.offsetWidth || 200;
  const menuH = menu.offsetHeight || 160;
  let left = rect.right - menuW;
  let top = rect.bottom + 4;
  if (left < 8) left = 8;
  if (top + menuH > window.innerHeight - 8) top = Math.max(8, rect.top - menuH - 4);
  menu.style.left = `${left}px`;
  menu.style.top = `${top}px`;
  anchor.closest(".chat-session-item")?.classList.add("menu-open");
}

function clearSessionMeta(sessionId) {
  const meta = readSessionMeta();
  if (meta[sessionId]) {
    delete meta[sessionId];
    writeSessionMeta(meta);
  }
}

async function deleteChatSession(sessionId, title) {
  const label = (title || "this chat").trim();
  const ok = confirm(
    `Delete "${label}"?\n\nThis permanently removes the chat and its messages.`
  );
  if (!ok) return;
  const res = await api(`/sessions/${encodeURIComponent(sessionId)}`, {
    method: "DELETE",
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    alert(err.detail || `Delete failed (${res.status})`);
    return;
  }
  clearSessionMeta(sessionId);
  if (getActiveSessionId() === sessionId) {
    startNewChat();
  }
  await loadSessionList();
}

async function renameChatSession(sessionId, currentTitle) {
  const next = prompt("Rename chat", currentTitle || "");
  if (next == null) return;
  const title = next.trim();
  if (!title) return;
  const res = await api(`/sessions/${encodeURIComponent(sessionId)}`, {
    method: "PATCH",
    body: JSON.stringify({ title }),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    alert(err.detail || `Rename failed (${res.status})`);
    return;
  }
  await loadSessionList();
}

function startNewChat() {
  setActiveSessionId(makeSessionId());
  clearChatUi();
  switchView("chat");
  renderSessionListActive();
  $("#chat-input")?.focus();
}

async function loadSessionList() {
  const list = $("#chat-session-list");
  if (!list) return;
  closeSessionMenu();
  try {
    const res = await api("/sessions");
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const sessions = await res.json();
    if (!sessions.length) {
      list.innerHTML = `<li class="chat-session-empty">No past chats yet</li>`;
      return;
    }
    const active = getActiveSessionId();
    list.innerHTML = sessions
      .map((s) => {
        const flags = getSessionFlags(s.session_id);
        const classes = [
          "chat-session-item",
          s.session_id === active ? "active" : "",
          flags.starred ? "starred" : "",
          flags.unread ? "unread" : "",
        ]
          .filter(Boolean)
          .join(" ");
        return `
      <li class="${classes}" data-session-id="${escapeHtml(s.session_id)}" data-title="${escapeHtml(s.title || "Chat")}">
        <button type="button" class="chat-session-open" title="${escapeHtml(s.title || "Chat")}">${escapeHtml(s.title || "Chat")}</button>
        <button type="button" class="chat-session-more" title="Chat options" aria-label="Chat options" aria-haspopup="menu">⋯</button>
      </li>`;
      })
      .join("");
  } catch (err) {
    console.warn("session list failed", err);
    list.innerHTML = `<li class="chat-session-empty">Could not load history</li>`;
  }
}

function renderSessionListActive() {
  const active = getActiveSessionId();
  $$("#chat-session-list .chat-session-item").forEach((li) => {
    li.classList.toggle("active", li.dataset.sessionId === active);
  });
}

async function openChatSession(sessionId) {
  if (!sessionId) return;
  setActiveSessionId(sessionId);
  setSessionFlag(sessionId, "unread", false);
  switchView("chat");
  clearChatUi();
  let activeDoc = null;
  try {
    const docRes = await api(
      `/documents/active?session_id=${encodeURIComponent(sessionId)}`
    );
    if (docRes.ok) {
      activeDoc = await docRes.json();
      if (activeDoc) rememberActiveDoc({ ...activeDoc, session_id: sessionId });
    }
  } catch {
    activeDoc = null;
  }
  try {
    const res = await api(`/sessions/${encodeURIComponent(sessionId)}/messages`);
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const messages = await res.json();
    if (messages.length) {
      enterChatActive();
      let showedOptions = false;
      for (const m of messages) {
        const content = m.content || "";
        if (m.role === "user" && content.startsWith("Uploaded document:")) {
          const fname = content.replace(/^Uploaded document:\s*/, "").trim() || activeDoc?.filename;
          addDocAttachBubble({
            ...(activeDoc || {}),
            filename: fname || activeDoc?.filename || "document",
            session_id: sessionId,
            doc_id: activeDoc?.doc_id,
          });
          continue;
        }
        if (
          m.role === "assistant" &&
          content.startsWith("I've read your document") &&
          activeDoc &&
          !showedOptions
        ) {
          renderDocOptionsCard({ ...activeDoc, session_id: sessionId });
          showedOptions = true;
          continue;
        }
        if (
          m.role === "assistant" &&
          content.includes("Choose an option below") &&
          activeDoc &&
          !showedOptions
        ) {
          renderDocOptionsCard({ ...activeDoc, session_id: sessionId });
          showedOptions = true;
          continue;
        }
        const role = m.role === "assistant" ? "bot" : "user";
        addBubble(role, content);
      }
    }
  } catch (err) {
    addBubble("bot", `Could not load chat: ${err.message}`, true);
  }
  await loadSessionList();
  $("#chat-input")?.focus();
}

function initChatSessions() {
  getActiveSessionId();
  $("#chat-new-btn")?.addEventListener("click", () => {
    closeSessionMenu();
    startNewChat();
    loadSessionList();
  });
  $("#chat-session-list")?.addEventListener("click", (e) => {
    const more = e.target.closest?.(".chat-session-more");
    const open = e.target.closest?.(".chat-session-open");
    const item = e.target.closest?.(".chat-session-item");
    if (!item) return;
    const sid = item.dataset.sessionId;
    if (more) {
      e.preventDefault();
      e.stopPropagation();
      openSessionMenu(more, sid, item.dataset.title || "");
      return;
    }
    if (open) openChatSession(sid);
  });
  $("#chat-session-menu")?.addEventListener("click", async (e) => {
    const btn = e.target.closest?.("[data-action]");
    if (!btn || !_sessionMenuSid) return;
    e.stopPropagation();
    const sid = _sessionMenuSid;
    const title = _sessionMenuTitle;
    const action = btn.dataset.action;
    closeSessionMenu();
    if (action === "star") {
      const flags = getSessionFlags(sid);
      setSessionFlag(sid, "starred", !flags.starred);
      await loadSessionList();
      return;
    }
    if (action === "unread") {
      const flags = getSessionFlags(sid);
      setSessionFlag(sid, "unread", !flags.unread);
      await loadSessionList();
      return;
    }
    if (action === "rename") {
      await renameChatSession(sid, title);
      return;
    }
    if (action === "project") {
      alert("Projects are not available in this demo yet.");
      return;
    }
    if (action === "delete") {
      await deleteChatSession(sid, title);
    }
  });
  document.addEventListener("click", (e) => {
    if (e.target.closest?.("#chat-session-menu") || e.target.closest?.(".chat-session-more")) return;
    closeSessionMenu();
  });
  window.addEventListener("resize", () => closeSessionMenu());
}

async function resetSession() {
  const ok = confirm(
    "Reset session?\n\nThis clears dashboard KPIs, recent queries, semantic cache, and the chat transcript.\nTickets and knowledge-base documents are kept."
  );
  if (!ok) return;
  const res = await api("/stats/reset", { method: "POST" });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    alert(err.detail || `Reset failed (${res.status})`);
    return;
  }
  clearChatUi();
  startNewChat();
  await loadStats();
  if ($("#view-insights")?.classList.contains("active")) {
    await loadInsights();
  }
  if ($("#view-attribution")?.classList.contains("active")) {
    await loadUserAttribution();
  }
}

const CHAT_MODEL_KEY = "ampcus_chat_model_preference";
const CHAT_MODEL_OPTIONS = {
  auto: { name: "Auto", effort: "Auto" },
  routine: { name: "Haiku", effort: "Low" },
  high: { name: "Sonnet", effort: "Medium" },
  opus: { name: "Opus", effort: "High" },
};
let _askInFlight = false;
let _chatModelValue = "auto";

function selectedModelPreference() {
  const value = (_chatModelValue || "auto").toLowerCase();
  return CHAT_MODEL_OPTIONS[value] ? value : "auto";
}

function setChatModelPreference(value, { persist = true } = {}) {
  const key = CHAT_MODEL_OPTIONS[value] ? value : "auto";
  _chatModelValue = key;
  const meta = CHAT_MODEL_OPTIONS[key];
  const hidden = $("#chat-model");
  if (hidden) hidden.value = key;
  const nameEl = $("#chat-model-name");
  const effortEl = $("#chat-model-effort");
  if (nameEl) nameEl.textContent = meta.name;
  if (effortEl) effortEl.textContent = meta.effort;
  $$("#chat-model-menu [role='option']").forEach((opt) => {
    opt.setAttribute("aria-selected", opt.dataset.value === key ? "true" : "false");
  });
  if (persist) localStorage.setItem(CHAT_MODEL_KEY, key);
}

function closeChatModelMenu() {
  const menu = $("#chat-model-menu");
  const btn = $("#chat-model-btn");
  if (menu) menu.hidden = true;
  if (btn) btn.setAttribute("aria-expanded", "false");
}

function initChatModelSelect() {
  const btn = $("#chat-model-btn");
  const menu = $("#chat-model-menu");
  if (!btn || !menu) return;

  const saved = localStorage.getItem(CHAT_MODEL_KEY) || "auto";
  setChatModelPreference(saved, { persist: false });

  btn.addEventListener("click", (e) => {
    e.stopPropagation();
    if (btn.disabled) return;
    const open = menu.hidden;
    menu.hidden = !open;
    btn.setAttribute("aria-expanded", open ? "true" : "false");
  });

  menu.querySelectorAll("[role='option']").forEach((opt) => {
    opt.addEventListener("click", (e) => {
      e.stopPropagation();
      setChatModelPreference(opt.dataset.value || "auto");
      closeChatModelMenu();
    });
  });

  document.addEventListener("click", (e) => {
    if (!e.target.closest?.("#chat-model-wrap")) closeChatModelMenu();
  });
}

async function ask(question) {
  const q = question.trim();
  if (!q || _askInFlight) return;

  if (_docAskMode) {
    _docAskMode = false;
    const input = $("#chat-input");
    if (input) input.placeholder = "How can I help you today?";
    await runDocumentAnalyze("ask", q);
    return;
  }

  _askInFlight = true;
  enterChatActive();
  addBubble("user", q);
  $("#chat-input").value = "";
  const modelBtn = $("#chat-model-btn");
  if (modelBtn) modelBtn.disabled = true;
  closeChatModelMenu();
  addBubble(
    "bot",
    "Thinking… (local models can take ~30–60s)"
  );
  const thinking = $("#chat-messages").lastElementChild;

  try {
    let data;
    try {
      const res = await api("/query", {
        method: "POST",
        body: JSON.stringify({
          question: q,
          model_preference: selectedModelPreference(),
          session_id: getActiveSessionId(),
        }),
      });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      data = await res.json();
    } catch (err) {
      if (!isStaleSessionError(err)) throw err;
      setActiveSessionId(makeSessionId());
      const res = await api("/query", {
        method: "POST",
        body: JSON.stringify({
          question: q,
          model_preference: selectedModelPreference(),
          session_id: getActiveSessionId(),
        }),
      });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      data = await res.json();
    }
    if (data.session_id) setActiveSessionId(data.session_id);
    thinking.remove();
    const blocked = data.nlp_allowed === false || data.block_kind;
    if (data.pending_ticket_confirmation) {
      addTicketConfirmBubble(
        data.answer || "Would you like me to open a support ticket for human review?"
      );
    } else if (data.reservation_calendar) {
      addReservationCalendarBubble(
        data.answer || "Select your guesthouse dates below.",
        data.reservation_calendar
      );
    } else {
      addBubble(
        "bot",
        data.answer || (blocked ? "Request blocked." : "(empty answer)"),
        blocked
      );
    }
    if (data.intent === "helpdesk_query") loadStats();
    loadSessionList();
  } catch (err) {
    thinking.remove();
    addBubble("bot", `Error: ${err.message}`, true);
  } finally {
    _askInFlight = false;
    if (modelBtn) modelBtn.disabled = false;
    $("#chat-input").focus();
  }
}

$("#chat-form").addEventListener("submit", (e) => {
  e.preventDefault();
  ask($("#chat-input").value);
});

$("#chat-input").addEventListener("keydown", (e) => {
  if (e.key === "Enter" && !e.shiftKey) {
    e.preventDefault();
    $("#chat-form").requestSubmit();
  }
});

initChatModelSelect();
initChatSessions();
initChatCheckpoints();

$("#chat-attach")?.addEventListener("click", () => {
  $("#chat-file-input")?.click();
});

let _docAskMode = false;
let _docSuggestedDept = "hr";
let _docBusy = false;
let _activeDocMeta = null;

const DOC_OP_ICONS = {
  summarize:
    '<svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="2"><path d="M4 6h16M4 12h10M4 18h14"/></svg>',
  takeaways:
    '<svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="2"><path d="M8 6h13M8 12h13M8 18h13M3 6h.01M3 12h.01M3 18h.01"/></svg>',
  actions:
    '<svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="2"><path d="M9 11l3 3L22 4"/><path d="M21 12v7a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h11"/></svg>',
  explain:
    '<svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="2"><path d="M9 18h6M10 22h4M12 2a7 7 0 0 0-4 12c.6.6 1 1.4 1 2.2V17h6v-.8c0-.8.4-1.6 1-2.2A7 7 0 0 0 12 2z"/></svg>',
  risks:
    '<svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="2"><path d="M10.3 3.9L1.8 18a2 2 0 0 0 1.7 3h17a2 2 0 0 0 1.7-3L13.7 3.9a2 2 0 0 0-3.4 0z"/><path d="M12 9v4M12 17h.01"/></svg>',
  ask:
    '<svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="2"><path d="M21 15a4 4 0 0 1-4 4H7l-4 3V7a4 4 0 0 1 4-4h10a4 4 0 0 1 4 4z"/></svg>',
  push_to_kb:
    '<svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="2"><path d="M12 5v14M5 12h14"/></svg>',
};

function formatFileSize(bytes) {
  const n = Number(bytes);
  if (!Number.isFinite(n) || n < 0) return "";
  if (n < 1024) return `${n} B`;
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} KB`;
  return `${(n / (1024 * 1024)).toFixed(1)} MB`;
}

function fileExtLabel(filename) {
  const ext = String(filename || "").split(".").pop() || "file";
  return ext.toUpperCase().slice(0, 4);
}

function fileExtKey(filename) {
  return String(filename || "").split(".").pop()?.toLowerCase() || "file";
}

function setDocComposerPlaceholder(active) {
  const input = $("#chat-input");
  if (!input) return;
  if (_docAskMode) {
    input.placeholder = "Ask a question about the uploaded document…";
  } else if (active) {
    input.placeholder = "Ask about the document or type a question…";
  } else {
    input.placeholder = "How can I help you today?";
  }
}

function rememberActiveDoc(data) {
  if (!data?.doc_id) {
    _activeDocMeta = null;
    setDocComposerPlaceholder(false);
    return;
  }
  _activeDocMeta = {
    doc_id: data.doc_id,
    session_id: data.session_id || getActiveSessionId(),
    filename: data.filename || "document",
    preview_kind: data.preview_kind || "",
    char_count: data.char_count || 0,
    file_size_bytes: data.file_size_bytes ?? null,
    page_count: data.page_count ?? null,
    available_options: data.available_options || [],
    suggested_department: data.suggested_department || "hr",
    created_at: data.created_at || null,
  };
  _docSuggestedDept = _activeDocMeta.suggested_department || "hr";
  setDocComposerPlaceholder(true);
}

function removeDocOptionCards() {
  $$(".doc-options-card").forEach((el) => el.remove());
}

function makeDocOptionButton(op) {
  const btn = document.createElement("button");
  btn.type = "button";
  btn.className = "doc-option-btn";
  const icon = DOC_OP_ICONS[op.id] || DOC_OP_ICONS.ask;
  btn.innerHTML = `${icon}<span>${escapeHtml(op.label || op.id)}</span>`;
  btn.title = op.description || op.label || "";
  btn.dataset.op = op.id;
  btn.dataset.needsQuestion = op.needs_question ? "1" : "0";
  return btn;
}

function renderDocOptionsCard(data) {
  removeDocOptionCards();
  const msgs = $("#chat-messages");
  if (!msgs) return;
  rememberActiveDoc(data);

  const card = document.createElement("div");
  card.className = "doc-options-card";
  card.dataset.docId = data.doc_id || "";
  card.dataset.sessionId = data.session_id || getActiveSessionId();
  card.innerHTML = `
    <h4>I've read your document. Here are the things I can do with it:</h4>
    <p>Nothing is sent to the model until you pick an action.</p>
    <div class="doc-options-grid"></div>
  `;
  const grid = card.querySelector(".doc-options-grid");
  for (const op of data.available_options || []) {
    grid.appendChild(makeDocOptionButton(op));
  }
  msgs.appendChild(card);
  msgs.scrollTo({ top: msgs.scrollHeight, behavior: "smooth" });
}

function docFileIconSvg(ext) {
  const kind = String(ext || "").toLowerCase();
  if (kind === "pdf") {
    return `<svg class="doc-file-icon" viewBox="0 0 24 24" width="18" height="18" aria-hidden="true">
      <path fill="#e2556f" d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8l-6-6z"/>
      <path fill="#fff" d="M14 2v6h6"/>
      <path fill="#fff" d="M8.2 17.2h1.1l.55-1.55h1.9l.55 1.55H14l-2.05-5.1h-1.7L8.2 17.2zm2.05-2.45.7-1.95.7 1.95h-1.4z"/>
    </svg>`;
  }
  if (kind === "docx" || kind === "doc") {
    return `<svg class="doc-file-icon" viewBox="0 0 24 24" width="18" height="18" aria-hidden="true">
      <path fill="#2b6cb0" d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8l-6-6z"/>
      <path fill="#fff" d="M14 2v6h6"/>
      <path fill="#fff" d="M8 12h8v1.2H8V12zm0 2.4h8v1.2H8v-1.2zm0 2.4h5v1.2H8v-1.2z"/>
    </svg>`;
  }
  return `<svg class="doc-file-icon" viewBox="0 0 24 24" width="18" height="18" aria-hidden="true">
    <path fill="#5a6570" d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8l-6-6z"/>
    <path fill="#fff" d="M14 2v6h6"/>
    <path fill="#fff" d="M8 12h8v1.2H8V12zm0 2.4h8v1.2H8v-1.2zm0 2.4h5v1.2H8v-1.2z"/>
  </svg>`;
}

function addDocAttachBubble(meta, { pending = false } = {}) {
  const msgs = $("#chat-messages");
  if (!msgs) return null;
  const el = document.createElement("div");
  el.className = "bubble user bubble-doc";
  el.dataset.checkpointId = `cp_${Date.now().toString(36)}_${Math.random().toString(36).slice(2, 7)}`;
  const filename = meta.filename || "document";
  const ext = fileExtKey(filename);
  const size = formatFileSize(meta.file_size_bytes ?? meta.size);
  const sub = pending
    ? `${size || fileExtLabel(filename)} · Uploading…`
    : `${[size, "Click to preview"].filter(Boolean).join(" · ")}`;
  el.innerHTML = `
    <button type="button" class="doc-attach-chip" data-doc-chip ${pending ? "disabled" : ""}>
      <span class="doc-file-badge" data-ext="${escapeHtml(ext)}">${docFileIconSvg(ext)}</span>
      <span class="doc-attach-meta">
        <span class="doc-attach-name">${escapeHtml(filename)}</span>
        <span class="doc-attach-sub">${escapeHtml(sub)}</span>
      </span>
      <span class="doc-attach-chevron" aria-hidden="true">
        <svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="2"><path d="M9 6l6 6-6 6"/></svg>
      </span>
    </button>
  `;
  const chip = el.querySelector("[data-doc-chip]");
  if (chip && !pending) {
    chip.dataset.docId = meta.doc_id || "";
    chip.dataset.sessionId = meta.session_id || getActiveSessionId();
    chip.dataset.filename = filename;
    chip.dataset.previewKind = meta.preview_kind || "";
    chip.dataset.charCount = String(meta.char_count || 0);
    if (meta.file_size_bytes != null) chip.dataset.fileSize = String(meta.file_size_bytes);
    if (meta.page_count != null) chip.dataset.pageCount = String(meta.page_count);
  }
  msgs.appendChild(el);
  msgs.scrollTo({ top: msgs.scrollHeight, behavior: "smooth" });
  refreshCheckpoints();
  return el;
}

let _docSideBlobUrl = null;

function revokeDocSideBlob() {
  if (_docSideBlobUrl) {
    URL.revokeObjectURL(_docSideBlobUrl);
    _docSideBlobUrl = null;
  }
}

function closeDocSidePanel() {
  const panel = $("#doc-side-panel");
  const view = $("#view-chat");
  if (panel) {
    panel.hidden = true;
    panel.classList.remove("is-wide");
  }
  view?.classList.remove("doc-panel-open");
  document.body.classList.remove("doc-panel-resizing");
  revokeDocSideBlob();
  const body = $("#doc-side-body");
  if (body) {
    body.classList.remove("has-text");
    body.innerHTML = `<p class="doc-side-placeholder">Upload a document to preview it here.</p>`;
  }
}

const DOC_PANEL_WIDTH_KEY = "ampcus_doc_panel_width";
const DOC_PANEL_MIN = 320;
const DOC_PANEL_DEFAULT = 420;

function getDocPanelMaxWidth() {
  return Math.max(DOC_PANEL_MIN + 40, Math.floor(window.innerWidth * 0.72));
}

function getSavedDocPanelWidth() {
  const raw = Number(localStorage.getItem(DOC_PANEL_WIDTH_KEY) || DOC_PANEL_DEFAULT);
  if (!Number.isFinite(raw)) return DOC_PANEL_DEFAULT;
  return raw;
}

function applyDocPanelWidth(px, { persist = true } = {}) {
  const max = getDocPanelMaxWidth();
  const w = Math.max(DOC_PANEL_MIN, Math.min(max, Math.round(px)));
  document.documentElement.style.setProperty("--doc-panel-width", `${w}px`);
  const panel = $("#doc-side-panel");
  if (panel) panel.classList.toggle("is-wide", w >= Math.floor(window.innerWidth * 0.55));
  const expandBtn = $("#doc-side-expand");
  if (expandBtn) {
    const wide = panel?.classList.contains("is-wide");
    expandBtn.title = wide ? "Narrow preview" : "Widen preview";
    expandBtn.setAttribute("aria-label", wide ? "Narrow preview" : "Widen preview");
  }
  if (persist) localStorage.setItem(DOC_PANEL_WIDTH_KEY, String(w));
  return w;
}

function initDocPanelResize() {
  const handle = $("#doc-side-resize");
  if (!handle || handle.dataset.bound === "1") return;
  handle.dataset.bound = "1";
  let dragging = false;

  const onMove = (e) => {
    if (!dragging) return;
    if (e.cancelable) e.preventDefault();
    const x = e.touches?.[0]?.clientX ?? e.clientX;
    applyDocPanelWidth(window.innerWidth - x);
  };
  const onUp = () => {
    if (!dragging) return;
    dragging = false;
    handle.classList.remove("is-dragging");
    document.body.classList.remove("doc-panel-resizing");
    window.removeEventListener("mousemove", onMove);
    window.removeEventListener("mouseup", onUp);
    window.removeEventListener("touchmove", onMove);
    window.removeEventListener("touchend", onUp);
  };

  const onDown = (e) => {
    e.preventDefault();
    dragging = true;
    handle.classList.add("is-dragging");
    document.body.classList.add("doc-panel-resizing");
    window.addEventListener("mousemove", onMove);
    window.addEventListener("mouseup", onUp);
    window.addEventListener("touchmove", onMove, { passive: false });
    window.addEventListener("touchend", onUp);
  };

  handle.addEventListener("mousedown", onDown);
  handle.addEventListener("touchstart", onDown, { passive: false });

  $("#doc-side-expand")?.addEventListener("click", () => {
    const wideTarget = Math.floor(window.innerWidth * 0.62);
    const current = getSavedDocPanelWidth();
    if (current >= Math.floor(window.innerWidth * 0.55)) {
      applyDocPanelWidth(DOC_PANEL_DEFAULT);
    } else {
      applyDocPanelWidth(wideTarget);
    }
  });

  window.addEventListener("resize", () => {
    if ($("#view-chat")?.classList.contains("doc-panel-open")) {
      applyDocPanelWidth(getSavedDocPanelWidth(), { persist: false });
    }
  });
}

function renderDocSideStats(meta) {
  const stats = $("#doc-side-stats");
  if (!stats) return;
  const rows = [];
  if (meta.page_count != null) {
    rows.push(`<div><dt>Pages</dt><dd>${Number(meta.page_count).toLocaleString()}</dd></div>`);
  }
  if (meta.char_count != null) {
    rows.push(`<div><dt>Characters</dt><dd>${Number(meta.char_count || 0).toLocaleString()}</dd></div>`);
  }
  rows.push(`<div><dt>Uploaded</dt><dd>just now</dd></div>`);
  stats.innerHTML = rows.join("");
}

async function renderNativeDocPreview(meta, body) {
  const sid = meta.session_id || getActiveSessionId();
  const docId = meta.doc_id;
  const kind = String(meta.preview_kind || fileExtKey(meta.filename || "")).toLowerCase();
  const previewKind =
    kind === "pdf" || kind === "html" || kind === "text"
      ? kind
      : fileExtKey(meta.filename || "") === "pdf"
        ? "pdf"
        : fileExtKey(meta.filename || "") === "docx"
          ? "html"
          : "text";

  const res = await api(
    `/documents/preview?session_id=${encodeURIComponent(sid)}&doc_id=${encodeURIComponent(docId)}`
  );
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(formatApiError(err, `Preview failed (${res.status})`));
  }

  body.classList.remove("has-text");
  revokeDocSideBlob();

  if (previewKind === "html") {
    const html = await res.text();
    body.innerHTML = `<iframe class="doc-side-frame" title="Document preview" sandbox="allow-same-origin"></iframe>`;
    const frame = body.querySelector("iframe");
    if (frame) frame.srcdoc = html;
    return;
  }

  if (previewKind === "text") {
    const text = await res.text();
    body.classList.add("has-text");
    body.textContent = text;
    return;
  }

  const blob = await res.blob();
  _docSideBlobUrl = URL.createObjectURL(blob);
  body.innerHTML = `<iframe class="doc-side-frame" title="Document preview" src="${_docSideBlobUrl}"></iframe>`;
}

async function openDocSidePanel(meta) {
  const panel = $("#doc-side-panel");
  const view = $("#view-chat");
  if (!panel || !meta?.doc_id) return;
  rememberActiveDoc({ ...(_activeDocMeta || {}), ...meta });
  applyDocPanelWidth(getSavedDocPanelWidth(), { persist: false });
  initDocPanelResize();
  panel.hidden = false;
  view?.classList.add("doc-panel-open");

  const filename = meta.filename || "document";
  const ext = fileExtKey(filename);
  const badge = $("#doc-side-badge");
  if (badge) {
    badge.textContent = fileExtLabel(filename);
    badge.dataset.ext = ext;
  }
  const nameEl = $("#doc-side-name");
  if (nameEl) nameEl.textContent = filename;
  const subEl = $("#doc-side-sub");
  if (subEl) {
    const size = formatFileSize(meta.file_size_bytes);
    subEl.textContent = [fileExtLabel(filename), size].filter(Boolean).join(" · ");
  }
  renderDocSideStats(meta);

  const body = $("#doc-side-body");
  if (body) {
    body.classList.remove("has-text");
    body.innerHTML = `<p class="doc-side-placeholder">Loading preview…</p>`;
  }
  try {
    const sid = meta.session_id || getActiveSessionId();
    // Refresh meta (size, char count) without using extracted text for display
    try {
      const metaRes = await api(`/documents/active?session_id=${encodeURIComponent(sid)}`);
      if (metaRes.ok) {
        const data = await metaRes.json();
        if (data) {
          rememberActiveDoc({ ...meta, ...data, session_id: sid });
          meta = { ...meta, ...data, session_id: sid };
          renderDocSideStats({
            ...meta,
            page_count: meta.page_count ?? data.page_count,
            file_size_bytes: data.file_size_bytes ?? meta.file_size_bytes,
          });
        }
      }
    } catch {
      /* preview can still proceed with chip meta */
    }
    if (body) await renderNativeDocPreview(meta, body);
  } catch (err) {
    if (body) {
      body.classList.remove("has-text");
      body.innerHTML = `<p class="doc-side-error">${escapeHtml(err.message || "Failed to load")}</p>`;
    }
  }
}

async function uploadChatDocument(file) {
  if (!file || _docBusy) return;
  _docBusy = true;
  enterChatActive();
  ensureSessionOwnedByCurrentUser();
  const pendingBubble = addDocAttachBubble(
    { filename: file.name, file_size_bytes: file.size },
    { pending: true }
  );
  addBubble("bot", "Reading document…");
  const thinking = $("#chat-messages").lastElementChild;
  try {
    const postUpload = async (sessionId) => {
      const body = new FormData();
      body.append("file", file);
      body.append("session_id", sessionId);
      const res = await api("/documents/upload", { method: "POST", body });
      const payload = await res.json().catch(() => ({}));
      if (!res.ok) {
        throw new Error(formatApiError(payload, `Upload failed (${res.status})`));
      }
      return payload;
    };

    let errBody;
    try {
      errBody = await postUpload(getActiveSessionId());
    } catch (err) {
      if (!isStaleSessionError(err)) throw err;
      setActiveSessionId(makeSessionId());
      errBody = await postUpload(getActiveSessionId());
    }
    if (errBody.session_id) setActiveSessionId(errBody.session_id);
    pendingBubble?.remove();
    thinking.remove();
    addDocAttachBubble({
      ...errBody,
      file_size_bytes: errBody.file_size_bytes ?? file.size,
    });
    renderDocOptionsCard(errBody);
    loadSessionList();
  } catch (err) {
    pendingBubble?.remove();
    thinking?.remove();
    addBubble("bot", `Error: ${err.message}`, true);
  } finally {
    _docBusy = false;
    const input = $("#chat-file-input");
    if (input) input.value = "";
  }
}

async function runDocumentAnalyze(operation, question = null) {
  if (_docBusy) return;
  _docBusy = true;
  enterChatActive();
  const label =
    operation === "ask" && question
      ? question
      : `Document: ${String(operation || "").replace(/_/g, " ")}`;
  addBubble("user", label);
  addBubble("bot", "Analyzing document…");
  const thinking = $("#chat-messages").lastElementChild;
  try {
    const res = await api("/documents/analyze", {
      method: "POST",
      body: JSON.stringify({
        session_id: getActiveSessionId(),
        operation,
        question: question || undefined,
      }),
    });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) {
      throw new Error(formatApiError(data, `Analyze failed (${res.status})`));
    }
    thinking.remove();
    addBubble("bot", data.result || "(empty result)");
    loadSessionList();
  } catch (err) {
    thinking?.remove();
    addBubble("bot", `Error: ${err.message}`, true);
  } finally {
    _docBusy = false;
    $("#chat-input")?.focus();
  }
}

function openDocKbModal() {
  const modal = $("#doc-kb-modal");
  const select = $("#doc-kb-dept");
  if (select) select.value = _docSuggestedDept || "hr";
  if (modal) modal.hidden = false;
}

function closeDocKbModal() {
  const modal = $("#doc-kb-modal");
  if (modal) modal.hidden = true;
}

async function confirmDocKbPush() {
  if (_docBusy) return;
  const dept = $("#doc-kb-dept")?.value || "hr";
  closeDocKbModal();
  _docBusy = true;
  enterChatActive();
  addBubble("user", `Add to KB (${dept})`);
  addBubble("bot", "Adding document to the knowledge base…");
  const thinking = $("#chat-messages").lastElementChild;
  try {
    const res = await api("/documents/push-to-kb", {
      method: "POST",
      body: JSON.stringify({
        session_id: getActiveSessionId(),
        department: dept,
      }),
    });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) {
      throw new Error(formatApiError(data, `KB push failed (${res.status})`));
    }
    thinking.remove();
    addBubble(
      "bot",
      `Added ${data.filename || "document"} to the ${data.department} knowledge base (${data.chunks_created} chunk(s)).`
    );
    loadSessionList();
  } catch (err) {
    thinking?.remove();
    addBubble("bot", `Error: ${err.message}`, true);
  } finally {
    _docBusy = false;
  }
}

function handleDocOptionClick(btn) {
  const op = btn.dataset.op;
  if (!op) return;
  if (op === "push_to_kb") {
    openDocKbModal();
    return;
  }
  if (op === "ask" || btn.dataset.needsQuestion === "1") {
    _docAskMode = true;
    setDocComposerPlaceholder(true);
    $("#chat-input")?.focus();
    return;
  }
  runDocumentAnalyze(op);
}

$("#chat-file-input")?.addEventListener("change", (e) => {
  const file = e.target?.files?.[0];
  if (file) uploadChatDocument(file);
});

$("#chat-messages")?.addEventListener("click", (e) => {
  const chip = e.target?.closest?.("[data-doc-chip]");
  if (chip && !chip.disabled) {
    openDocSidePanel({
      doc_id: chip.dataset.docId,
      session_id: chip.dataset.sessionId || getActiveSessionId(),
      filename: chip.dataset.filename,
      preview_kind: chip.dataset.previewKind,
      char_count: Number(chip.dataset.charCount || 0),
      file_size_bytes: chip.dataset.fileSize ? Number(chip.dataset.fileSize) : null,
      page_count: chip.dataset.pageCount ? Number(chip.dataset.pageCount) : null,
      available_options: _activeDocMeta?.available_options || [],
    });
    return;
  }
  const btn = e.target?.closest?.(".doc-option-btn");
  if (!btn || btn.disabled) return;
  handleDocOptionClick(btn);
});

$("#doc-side-close")?.addEventListener("click", closeDocSidePanel);

$("#doc-kb-cancel")?.addEventListener("click", closeDocKbModal);
$("#doc-kb-backdrop")?.addEventListener("click", closeDocKbModal);
$("#doc-kb-confirm")?.addEventListener("click", confirmDocKbPush);

$("#chat-mic")?.addEventListener("click", () => {
  alert("Voice input is not enabled in this MVP.");
});
$("#chat-wave")?.addEventListener("click", () => {
  alert("Voice mode is not enabled in this MVP.");
});

function ticketItems(payload) {
  return Array.isArray(payload) ? payload : payload.value || [];
}

const PAGE_SIZE = 6;

function pageSlice(items, page, size = PAGE_SIZE) {
  const list = items || [];
  const total = list.length;
  const totalPages = Math.max(1, Math.ceil(total / size) || 1);
  const safePage = Math.min(Math.max(1, page || 1), totalPages);
  const start = (safePage - 1) * size;
  return {
    items: list.slice(start, start + size),
    page: safePage,
    totalPages,
    total,
    start: total ? start + 1 : 0,
    end: Math.min(start + size, total),
  };
}

function renderPagination(container, { page, totalPages, total, start, end }, onPage) {
  if (!container) return;
  if (!total) {
    container.hidden = true;
    container.innerHTML = "";
    return;
  }
  container.hidden = false;
  const pages = Array.from({ length: totalPages }, (_, i) => i + 1);
  container.innerHTML = `
    <p class="pagination-meta">Showing ${start}–${end} of ${total}</p>
    <div class="pagination-controls">
      <button type="button" class="pagination-btn" data-page="${page - 1}" ${page <= 1 ? "disabled" : ""}>Prev</button>
      <div class="pagination-pages">
        ${pages
          .map(
            (p) =>
              `<button type="button" class="pagination-page ${p === page ? "active" : ""}" data-page="${p}">${p}</button>`
          )
          .join("")}
      </div>
      <button type="button" class="pagination-btn" data-page="${page + 1}" ${page >= totalPages ? "disabled" : ""}>Next</button>
    </div>`;
  container.querySelectorAll("[data-page]").forEach((btn) => {
    btn.addEventListener("click", () => {
      if (btn.disabled) return;
      const next = Number(btn.dataset.page);
      if (!Number.isFinite(next) || next < 1 || next > totalPages) return;
      onPage(next);
    });
  });
}

let _boardTickets = [];
let _boardFilter = "";
let _selectedTicketId = null;
let _boardDnDBound = false;

function boardStatus(ticket) {
  const s = (ticket.status || "open").toLowerCase();
  if (s === "resolved") return "resolved";
  if (s === "assigned") return "assigned";
  return "open";
}

function boardTypePrefix(ticket) {
  return (ticket.ticket_type || "unknown") === "escalation" ? "ESC" : "UNK";
}

function boardKey(ticket) {
  const id = String(ticket.id || "");
  return `${boardTypePrefix(ticket)}-${id.slice(0, 8).toUpperCase()}`;
}

function boardTypeLabel(ticket) {
  return (ticket.ticket_type || "unknown") === "escalation" ? "escalation" : "unknown";
}

function boardCardHtml(t) {
  const dept = (t.department || "unknown").toLowerCase();
  const created = (t.created_at || "").replace("T", " ").slice(0, 16);
  const emp = t.created_by_email || "—";
  const type = boardTypeLabel(t);
  return `<article class="board-card" draggable="true" data-id="${escapeHtml(t.id)}" data-status="${boardStatus(t)}" data-dept="${escapeHtml(dept)}" data-type="${escapeHtml(type)}">
    <div class="card-tags">
      <span class="epic ${escapeHtml(dept)}">${escapeHtml(dept)}</span>
      <span class="tag ${escapeHtml(type)}">${escapeHtml(type)}</span>
    </div>
    <h4>${escapeHtml(t.question || "Untitled")}</h4>
    <div class="card-meta">
      <span class="key">${boardKey(t)}</span>
      <span class="${(t.severity || "") === "high" ? "sev-high" : ""}">${escapeHtml(t.severity || "—")}</span>
      <span>${escapeHtml(created)}</span>
      <span title="Reporter">${escapeHtml(emp)}</span>
    </div>
  </article>`;
}

function filterBoardTickets(tickets) {
  const q = (_boardFilter || "").trim().toLowerCase();
  if (!q) return tickets;
  return tickets.filter((t) => {
    const blob = `${t.question} ${t.department} ${t.ticket_type} ${t.id} ${t.created_by_email} ${t.reason}`.toLowerCase();
    return blob.includes(q);
  });
}

function renderTicketsBoard() {
  const rootSel = "#tickets-jira-board";
  const items = filterBoardTickets(_boardTickets);
  const byStatus = { open: [], assigned: [], resolved: [] };
  items.forEach((t) => byStatus[boardStatus(t)].push(t));

  const countEl = $("#board-count");
  if (countEl) {
    countEl.textContent = `${items.length} work item${items.length === 1 ? "" : "s"}`;
  }

  ["open", "assigned", "resolved"].forEach((status) => {
    const body = $(`${rootSel} .board-col-body[data-drop="${status}"]`);
    const count = $(`[data-count-for="board-${status}"]`);
    if (count) count.textContent = String(byStatus[status].length);
    if (!body) return;
    if (!byStatus[status].length) {
      body.innerHTML = `<div class="empty" style="padding:12px;font-size:13px">No stories</div>`;
    } else {
      body.innerHTML = byStatus[status].map((t) => boardCardHtml(t)).join("");
    }
  });

  bindBoardDnD(rootSel);
  $$(`${rootSel} .board-card`).forEach((card) => {
    card.addEventListener("click", () => openBoardDetail(card.dataset.id));
  });
}

function bindBoardDnD(rootSel) {
  $$(`${rootSel} .board-card`).forEach((card) => {
    card.addEventListener("dragstart", (e) => {
      e.dataTransfer.setData("text/ticket-id", card.dataset.id);
      e.dataTransfer.effectAllowed = "move";
    });
  });
  if (_boardDnDBound) return;
  _boardDnDBound = true;
  $$(`${rootSel} .board-col-body`).forEach((col) => {
    col.addEventListener("dragover", (e) => {
      e.preventDefault();
      col.classList.add("drag-over");
    });
    col.addEventListener("dragleave", () => col.classList.remove("drag-over"));
    col.addEventListener("drop", async (e) => {
      e.preventDefault();
      col.classList.remove("drag-over");
      const id = e.dataTransfer.getData("text/ticket-id");
      const target = col.dataset.drop;
      if (!id || !target) return;
      await moveBoardStory(id, target);
    });
  });
}

async function moveBoardStory(id, targetStatus) {
  const ticket = _boardTickets.find((t) => t.id === id);
  if (!ticket) return;
  const current = boardStatus(ticket);
  if (current === targetStatus) return;

  try {
    if (targetStatus === "assigned") {
      let dept = (ticket.department || ticket.assigned_department || "").toLowerCase();
      if (!["hr", "it", "compliance", "legal"].includes(dept)) {
        openBoardDetail(id);
        alert("Pick a department in the detail panel, then click Assign / In Progress.");
        return;
      }
      const res = await api(`/tickets/${id}/assign`, {
        method: "PATCH",
        body: JSON.stringify({ department: dept }),
      });
      if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        throw new Error(formatApiError(err, `HTTP ${res.status}`));
      }
    } else if (targetStatus === "resolved") {
      const notes =
        $("#board-detail-notes")?.value?.trim() ||
        ticket.admin_notes ||
        "Resolved on board";
      const res = await api(`/tickets/${id}/resolve`, {
        method: "PATCH",
        body: JSON.stringify({ status: "resolved", admin_notes: notes }),
      });
      if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        throw new Error(formatApiError(err, `HTTP ${res.status}`));
      }
    } else if (targetStatus === "open" && current !== "open") {
      alert(
        "Re-opening a story to TO DO is not supported yet. Leave it In Progress or move to Done."
      );
      return;
    }
    await loadTickets();
    loadStats();
  } catch (e) {
    alert(e.message || String(e));
    await loadTickets();
  }
}

function statusLabel(ticket) {
  const s = boardStatus(ticket);
  if (s === "assigned") return "IN PROGRESS";
  if (s === "resolved") return "DONE";
  return "TO DO";
}

function openBoardDetail(id) {
  const ticket = _boardTickets.find((t) => t.id === id);
  if (!ticket) return;
  _selectedTicketId = id;
  const panel = $("#board-detail");
  if (!panel) return;
  panel.hidden = false;
  document.body.classList.add("board-modal-open");

  const key = boardKey(ticket);
  const type = boardTypeLabel(ticket);
  const status = boardStatus(ticket);

  $("#board-detail-title").textContent = ticket.question || "Story";
  $("#board-detail-key").textContent = key;
  $("#board-detail-type").textContent = type;
  $("#board-detail-type-value").textContent = type;
  $("#board-detail-meta").textContent = `${key} · opened ${(ticket.created_at || "")
    .replace("T", " ")
    .slice(0, 16)}`;
  $("#board-detail-description").textContent =
    ticket.question || ticket.reason || "No description";
  $("#board-detail-notes").value = ticket.admin_notes || "";
  $("#board-detail-answer").value = "";
  $("#board-detail-severity").textContent = ticket.severity || "—";
  $("#board-detail-reporter").textContent = ticket.created_by_email || "—";

  const statusEl = $("#board-detail-status");
  if (statusEl) {
    statusEl.textContent = statusLabel(ticket);
    statusEl.classList.toggle("is-assigned", status === "assigned");
    statusEl.classList.toggle("is-resolved", status === "resolved");
  }

  const sel = $("#board-detail-dept");
  const dept = (ticket.assigned_department || ticket.department || "it").toLowerCase();
  if (sel) {
    sel.value = ["hr", "it", "compliance", "legal"].includes(dept) ? dept : "it";
  }
}

function closeBoardDetail() {
  const panel = $("#board-detail");
  if (panel) panel.hidden = true;
  document.body.classList.remove("board-modal-open");
  _selectedTicketId = null;
}

async function loadTickets() {
  const tickets = await api("/tickets").then((r) => r.json());
  _boardTickets = ticketItems(tickets).sort((a, b) =>
    String(b.created_at || "").localeCompare(String(a.created_at || ""))
  );
  renderTicketsBoard();
  if (_selectedTicketId) {
    const still = _boardTickets.find((t) => t.id === _selectedTicketId);
    if (still) openBoardDetail(_selectedTicketId);
    else closeBoardDetail();
  }
}

$("#board-detail-close")?.addEventListener("click", () => closeBoardDetail());
$("#board-detail-backdrop")?.addEventListener("click", () => closeBoardDetail());
$("#board-detail-key")?.addEventListener("click", (e) => e.preventDefault());
document.addEventListener("keydown", (e) => {
  if (e.key === "Escape" && !$("#board-detail")?.hidden) closeBoardDetail();
});

$("#board-search")?.addEventListener("input", (e) => {
  _boardFilter = e.target.value || "";
  renderTicketsBoard();
});

$("#board-detail-assign")?.addEventListener("click", async () => {
  if (!_selectedTicketId) return;
  const dept = $("#board-detail-dept").value;
  const notes = $("#board-detail-notes").value.trim();
  const res = await api(`/tickets/${_selectedTicketId}/assign`, {
    method: "PATCH",
    body: JSON.stringify({ department: dept, admin_notes: notes || null }),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    alert(formatApiError(err, `HTTP ${res.status}`));
    return;
  }
  const id = _selectedTicketId;
  await loadTickets();
  loadStats();
  openBoardDetail(id);
});

$("#board-detail-resolve")?.addEventListener("click", async () => {
  if (!_selectedTicketId) return;
  const notes = $("#board-detail-notes").value.trim();
  const res = await api(`/tickets/${_selectedTicketId}/resolve`, {
    method: "PATCH",
    body: JSON.stringify({ status: "resolved", admin_notes: notes || null }),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    alert(formatApiError(err, `HTTP ${res.status}`));
    return;
  }
  closeBoardDetail();
  await loadTickets();
  loadStats();
});

$("#board-detail-promote")?.addEventListener("click", async () => {
  if (!_selectedTicketId) return;
  const answer = $("#board-detail-answer").value.trim();
  const notes = $("#board-detail-notes").value.trim();
  const dept = $("#board-detail-dept").value;
  if (!answer) {
    alert("Enter a KB answer to promote.");
    return;
  }
  const res = await api(`/tickets/${_selectedTicketId}/promote`, {
    method: "POST",
    body: JSON.stringify({
      department: dept,
      answer,
      admin_notes: notes || null,
    }),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    alert(formatApiError(err, `HTTP ${res.status}`));
    return;
  }
  closeBoardDetail();
  await loadTickets();
  loadStats();
});

$("#refresh-stats")?.addEventListener("click", loadStats);
$("#reset-session")?.addEventListener("click", () => resetSession());
$("#refresh-kb")?.addEventListener("click", () => loadKnowledgeBase());
$("#refresh-tickets")?.addEventListener("click", loadTickets);
$("#refresh-insights")?.addEventListener("click", loadInsights);
$("#refresh-nlp-logs")?.addEventListener("click", loadNlpLogs);

function openTextPreview(title, text) {
  const modal = $("#text-preview-modal");
  const titleEl = $("#text-preview-title");
  const body = $("#text-preview-body");
  if (!modal || !body) return;
  if (titleEl) titleEl.textContent = title || "Detail";
  body.textContent = text || "—";
  modal.hidden = false;
  document.body.classList.add("text-preview-open");
}

function closeTextPreview() {
  const modal = $("#text-preview-modal");
  if (modal) modal.hidden = true;
  document.body.classList.remove("text-preview-open");
}

function nlpClipButton(label, fullText, extraClass = "") {
  const text = fullText || "—";
  return `<button type="button" class="nlp-clip-btn ${extraClass}" data-preview-title="${escapeHtml(label)}" data-preview-text="${escapeHtml(text)}" title="Click to expand">${escapeHtml(text)}</button>`;
}

async function loadNlpLogs() {
  const tbody = $("#nlp-logs-table tbody");
  if (!tbody) return;
  tbody.innerHTML = `<tr><td colspan="7">Loading…</td></tr>`;
  try {
    const res = await api("/admin/nlp-logs?limit=100");
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const data = await res.json();
    const logs = data.logs || [];
    if (!logs.length) {
      tbody.innerHTML = `<tr><td colspan="7">No Company data queries logged yet.</td></tr>`;
      return;
    }
    tbody.innerHTML = logs
      .map((r) => {
        const ts = (r.timestamp || "").replace("T", " ").slice(0, 19);
        const access = r.allowed
          ? "allowed"
          : `blocked${r.block_kind ? ` (${escapeHtml(r.block_kind)})` : ""}`;
        return `<tr>
          <td class="mono">${escapeHtml(ts)}</td>
          <td>${escapeHtml(r.user_email || "—")}</td>
          <td>${escapeHtml(r.user_role || "—")}</td>
          <td>${access}</td>
          <td class="nlp-clip">${nlpClipButton("Question", r.question || "", "nlp-q-btn")}</td>
          <td class="nlp-clip">${nlpClipButton("SQL", r.sql || "—", "nlp-sql-btn")}</td>
          <td class="nlp-clip">${nlpClipButton("Answer", r.answer || "", "nlp-q-btn")}</td>
        </tr>`;
      })
      .join("");
  } catch (err) {
    tbody.innerHTML = `<tr><td colspan="7">Failed to load: ${escapeHtml(err.message)}</td></tr>`;
  }
}

$("#nlp-logs-table")?.addEventListener("click", (e) => {
  const btn = e.target.closest?.(".nlp-clip-btn");
  if (!btn) return;
  openTextPreview(btn.dataset.previewTitle || "Detail", btn.dataset.previewText || "");
});
$("#text-preview-close")?.addEventListener("click", closeTextPreview);
$("#text-preview-backdrop")?.addEventListener("click", closeTextPreview);
document.addEventListener("keydown", (e) => {
  if (e.key === "Escape" && !$("#text-preview-modal")?.hidden) closeTextPreview();
});
$("#refresh-attribution")?.addEventListener("click", loadUserAttribution);

function money(n) {
  const v = Number(n) || 0;
  if (v === 0) return "$0";
  if (v < 0.0001) return `$${v.toExponential(2)}`;
  if (v < 0.01) return `$${v.toFixed(5)}`;
  return `$${v.toFixed(4)}`;
}

function drawDualBarChart(canvas, series, keyA, keyB, colorA, colorB) {
  if (!canvas) return;
  const ctx = canvas.getContext("2d");
  const dpr = window.devicePixelRatio || 1;
  const cssW = canvas.clientWidth || 640;
  const cssH = 260;
  canvas.width = cssW * dpr;
  canvas.height = cssH * dpr;
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  ctx.clearRect(0, 0, cssW, cssH);

  const pad = { t: 16, r: 12, b: 28, l: 44 };
  const w = cssW - pad.l - pad.r;
  const h = cssH - pad.t - pad.b;
  const data = series || [];
  if (!data.length) {
    ctx.fillStyle = "#888";
    ctx.font = "13px Manrope, sans-serif";
    ctx.fillText("No queries yet — ask something in Chat.", pad.l, cssH / 2);
    return;
  }

  const maxVal = Math.max(
    ...data.map((d) => Math.max(Number(d[keyA]) || 0, Number(d[keyB]) || 0)),
    0.000001
  );
  const n = data.length;
  const group = w / n;
  const barW = Math.max(3, Math.min(14, group * 0.35));

  // grid
  ctx.strokeStyle = "#ece8f4";
  ctx.lineWidth = 1;
  for (let i = 0; i <= 4; i++) {
    const y = pad.t + (h * i) / 4;
    ctx.beginPath();
    ctx.moveTo(pad.l, y);
    ctx.lineTo(pad.l + w, y);
    ctx.stroke();
  }

  data.forEach((d, i) => {
    const x0 = pad.l + i * group + group / 2;
    const a = Number(d[keyA]) || 0;
    const b = Number(d[keyB]) || 0;
    const ha = (a / maxVal) * h;
    const hb = (b / maxVal) * h;
    ctx.fillStyle = colorA;
    ctx.fillRect(x0 - barW - 1, pad.t + h - ha, barW, ha);
    ctx.fillStyle = colorB;
    ctx.fillRect(x0 + 1, pad.t + h - hb, barW, hb);
  });

  ctx.fillStyle = "#8a8499";
  ctx.font = "11px Manrope, sans-serif";
  ctx.fillText("0", 8, pad.t + h + 4);
  ctx.fillText(maxVal < 0.01 ? maxVal.toExponential(1) : maxVal.toFixed(4), 4, pad.t + 10);
}

function drawLatencyChart(canvas, series) {
  if (!canvas) return;
  const ctx = canvas.getContext("2d");
  const dpr = window.devicePixelRatio || 1;
  const cssW = canvas.clientWidth || 640;
  const cssH = 260;
  canvas.width = cssW * dpr;
  canvas.height = cssH * dpr;
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  ctx.clearRect(0, 0, cssW, cssH);

  const pad = { t: 16, r: 12, b: 28, l: 48 };
  const w = cssW - pad.l - pad.r;
  const h = cssH - pad.t - pad.b;
  const data = series || [];
  if (!data.length) {
    ctx.fillStyle = "#888";
    ctx.font = "13px Manrope, sans-serif";
    ctx.fillText("No latency data yet.", pad.l, cssH / 2);
    return;
  }
  const maxVal = Math.max(...data.map((d) => Number(d.latency_ms) || 0), 1);

  ctx.strokeStyle = "#ece8f4";
  for (let i = 0; i <= 4; i++) {
    const y = pad.t + (h * i) / 4;
    ctx.beginPath();
    ctx.moveTo(pad.l, y);
    ctx.lineTo(pad.l + w, y);
    ctx.stroke();
  }

  ctx.beginPath();
  ctx.strokeStyle = "#3dcfb0";
  ctx.lineWidth = 2.5;
  data.forEach((d, i) => {
    const x = pad.l + (i / Math.max(data.length - 1, 1)) * w;
    const y = pad.t + h - ((Number(d.latency_ms) || 0) / maxVal) * h;
    if (i === 0) ctx.moveTo(x, y);
    else ctx.lineTo(x, y);
  });
  ctx.stroke();

  data.forEach((d, i) => {
    const x = pad.l + (i / Math.max(data.length - 1, 1)) * w;
    const y = pad.t + h - ((Number(d.latency_ms) || 0) / maxVal) * h;
    ctx.fillStyle = "#2a9f84";
    ctx.beginPath();
    ctx.arc(x, y, 3.5, 0, Math.PI * 2);
    ctx.fill();
  });

  ctx.fillStyle = "#8a8499";
  ctx.font = "11px Manrope, sans-serif";
  ctx.fillText("0", 20, pad.t + h + 4);
  ctx.fillText(`${Math.round(maxVal)}ms`, 8, pad.t + 10);
}

function statusBadge(status) {
  const s = (status || "good").toLowerCase();
  const label = s === "restricted" ? "Restricted" : s === "training" ? "Training" : "Good";
  const cls =
    s === "restricted" ? "unknown" : s === "training" ? "cached" : "";
  return `<span class="tag ${cls}">${label}</span>`;
}

async function loadUserAttribution() {
  if (currentRole() !== "admin") return;
  const data = await api("/admin/insights").then((r) => r.json());
  const kpis = $("#attr-kpis");
  if (kpis) {
    const biggest = data.biggest_spender;
    kpis.innerHTML = `
      <article class="kpi-card"><p class="kpi-label">Total cost (audit)</p><h2>${money(
        data.total_cost_usd
      )}</h2><p class="kpi-sub">${data.total_queries || 0} queries</p></article>
      <article class="kpi-card"><p class="kpi-label">Cache savings</p><h2>${money(
        data.cache_savings_usd
      )}</h2><p class="kpi-sub">${data.cache_hit_rate || 0}% hit rate</p></article>
      <article class="kpi-card"><p class="kpi-label">Biggest spender</p><h2 style="font-size:1rem">${
        biggest ? escapeHtml(biggest.user_email) : "—"
      }</h2><p class="kpi-sub">${biggest ? money(biggest.total_cost_usd) : ""}</p></article>
      <article class="kpi-card"><p class="kpi-label">Top dept cost</p><h2 style="font-size:1rem">${
        data.most_expensive_dept
          ? escapeHtml(data.most_expensive_dept.department)
          : "—"
      }</h2><p class="kpi-sub">${
      data.most_expensive_dept ? money(data.most_expensive_dept.cost_usd) : ""
    }</p></article>`;
  }
  const tbody = $("#attr-users-table tbody");
  const users = data.users || [];
  if (!users.length) {
    tbody.innerHTML = `<tr><td colspan="7">No audited queries yet.</td></tr>`;
    return;
  }
  tbody.innerHTML = users
    .map(
      (u) => `<tr class="attr-user-row" data-email="${escapeHtml(u.user_email)}" style="cursor:pointer">
        <td>${escapeHtml(u.user_email)}</td>
        <td>${escapeHtml(u.user_role || "—")}</td>
        <td class="mono">${u.queries}</td>
        <td class="mono">${money(u.total_cost_usd)}</td>
        <td class="mono">${u.cache_hit_rate}%</td>
        <td class="mono">${u.avg_prompt_score}</td>
        <td>${statusBadge(u.status)}</td>
      </tr>`
    )
    .join("");
  tbody.querySelectorAll(".attr-user-row").forEach((row) => {
    row.addEventListener("click", () => loadUserQueries(row.dataset.email));
  });
}

async function loadUserQueries(email) {
  const wrap = $("#attr-drilldown");
  const title = $("#attr-drill-title");
  const tbody = $("#attr-queries-table tbody");
  if (!wrap || !tbody) return;
  wrap.hidden = false;
  title.textContent = `Recent queries — ${email}`;
  const data = await api(`/admin/users/${encodeURIComponent(email)}/queries?limit=50`).then((r) =>
    r.json()
  );
  const rows = data.queries || [];
  if (!rows.length) {
    tbody.innerHTML = `<tr><td colspan="5">No queries.</td></tr>`;
    return;
  }
  tbody.innerHTML = rows
    .map((r) => {
      const ts = (r.timestamp || "").replace("T", " ").slice(0, 19);
      return `<tr>
        <td class="mono">${escapeHtml(ts)}</td>
        <td class="q">${escapeHtml(r.query || "")}</td>
        <td class="mono">${r.prompt_score ?? "—"}</td>
        <td class="mono">${money(r.cost_usd)}</td>
        <td>${escapeHtml(r.department || "—")}</td>
      </tr>`;
    })
    .join("");
}

async function loadInsights() {
  const stats = await api("/stats").then((r) => r.json());
  $("#ins-cost-actual").textContent = money(stats.cost_actual_sum_usd);
  $("#ins-cost-actual-sub").textContent = `${stats.total_queries} queries`;
  $("#ins-cost-opus").textContent = money(stats.cost_opus_sum_usd);
  $("#ins-savings").textContent = money(stats.cost_savings_sum_usd);
  $("#ins-savings-pct").textContent = `${stats.cost_savings_pct || 0}% vs always Opus`;
  $("#ins-latency").textContent =
    stats.avg_latency_ms >= 1000
      ? `${(stats.avg_latency_ms / 1000).toFixed(1)}s`
      : `${Math.round(stats.avg_latency_ms || 0)}ms`;
  $("#ins-avg-cost").textContent = `avg ${money(stats.avg_cost_actual_usd)} / query (Opus avg ${money(
    stats.avg_cost_opus_usd
  )})`;

  barList($("#role-bars"), stats.by_model_role || {}, {
    haiku: "#6c4dff",
    sonnet: "#3dcfb0",
    opus: "#e2556f",
  });
  barList($("#sev-bars"), stats.by_severity || {}, {
    routine: "#6c4dff",
    high: "#e2556f",
  });

  drawDualBarChart(
    $("#chart-cost"),
    stats.cost_series || [],
    "actual",
    "opus",
    "#6c4dff",
    "#e2556f"
  );
  drawLatencyChart($("#chart-latency"), stats.cost_series || []);

  const tbody = $("#insights-table tbody");
  const rows = stats.recent || [];
  if (!rows.length) {
    tbody.innerHTML = `<tr><td colspan="9">No queries yet.</td></tr>`;
  } else {
    tbody.innerHTML = rows
      .map((r) => {
        const lat =
          r.latency_ms >= 1000
            ? `${(r.latency_ms / 1000).toFixed(1)}s`
            : `${Math.round(r.latency_ms)}ms`;
        const reason = r.classify_reason
          ? `<div style="color:#888;font-weight:500;margin-top:4px">${escapeHtml(
              r.classify_reason
            )}</div>`
          : "";
        return `<tr>
        <td class="q">${escapeHtml(r.question || "")}${reason}${
          r.cached ? ' <span class="tag cached">cached</span>' : ""
        }</td>
        <td><span class="tag ${r.department === "unknown" ? "unknown" : ""}">${escapeHtml(
          r.department
        )}</span></td>
        <td>${escapeHtml(r.severity)}</td>
        <td>${escapeHtml(r.model_used || "—")}</td>
        <td>${escapeHtml(r.model_role || "—")}</td>
        <td class="mono">${lat}</td>
        <td class="mono">${money(r.cost_actual_usd)}</td>
        <td class="mono">${money(r.cost_opus_always_usd)}</td>
        <td class="mono">${money(r.cost_savings_usd)}</td>
      </tr>`;
      })
      .join("");
  }
}

let _kbData = null;
let _kbDept = "hr";
let _kbPage = 1;

async function loadKnowledgeBase() {
  const data = await api("/kb").then((r) => r.json());
  _kbData = data;
  const depts = (data.departments || []).map((d) => d.department);
  if (!depts.includes(_kbDept) && depts.length) {
    _kbDept = depts[0];
  }
  _kbPage = 1;

  const tabs = $("#kb-tabs");
  tabs.innerHTML = (data.departments || [])
    .map((d) => {
      const active = d.department === _kbDept ? "active" : "";
      return `<button type="button" class="kb-tab ${active}" data-dept="${d.department}">
        <span>${d.department}</span>
        <strong>${d.count}</strong>
      </button>`;
    })
    .join("");

  tabs.querySelectorAll(".kb-tab").forEach((btn) => {
    btn.addEventListener("click", () => {
      _kbDept = btn.dataset.dept;
      _kbPage = 1;
      renderKbPanel();
      tabs
        .querySelectorAll(".kb-tab")
        .forEach((b) => b.classList.toggle("active", b.dataset.dept === _kbDept));
    });
  });

  renderKbPanel();
}

function renderKbPanel() {
  const panel = $("#kb-panel");
  const pager = $("#kb-pagination");
  if (!_kbData) {
    panel.innerHTML = `<p class="empty">Loading knowledge base…</p>`;
    renderPagination(pager, { page: 1, totalPages: 1, total: 0, start: 0, end: 0 }, () => {});
    return;
  }
  const block = (_kbData.departments || []).find((d) => d.department === _kbDept);
  if (!block || !block.documents?.length) {
    panel.innerHTML = `<p class="empty">No documents in this department yet.</p>`;
    renderPagination(pager, { page: 1, totalPages: 1, total: 0, start: 0, end: 0 }, () => {});
    return;
  }
  const pageData = pageSlice(block.documents, _kbPage);
  _kbPage = pageData.page;
  const color = DEPT_COLORS[block.department] || "var(--violet)";
  panel.innerHTML = `
    <div class="kb-dept-head">
      <h2 style="--dept-color:${color}">${escapeHtml(block.department.toUpperCase())}</h2>
      <p>${block.count} official document${block.count === 1 ? "" : "s"} / protocols</p>
    </div>
    <div class="kb-doc-grid">
      ${pageData.items
        .map(
          (doc) => `<article class="kb-doc-card">
            <p class="kb-doc-label">Official document / protocol</p>
            <h3>${escapeHtml(doc.title || "Untitled")}</h3>
            <p class="kb-doc-id">${escapeHtml(doc.id || "")}</p>
            <p class="kb-doc-body">${escapeHtml(doc.content || "")}</p>
          </article>`
        )
        .join("")}
    </div>`;

  renderPagination(pager, pageData, (p) => {
    _kbPage = p;
    renderKbPanel();
  });
}

let _onboardingFilter = "all";
let _onboardingSelectedEmail = "";

const WORKSPACE_CATEGORY_LABELS = {
  identity: "Identity & access",
  payroll: "Payroll",
  benefits: "Benefits",
  documents: "Documents",
  apps: "Apps & tools",
};

const WORKSPACE_CATEGORY_ORDER = ["identity", "payroll", "benefits", "documents", "apps"];

function workspaceTicketStatusLabel(status) {
  const s = String(status || "open").toLowerCase();
  if (s === "assigned") return "In progress";
  if (s === "resolved") return "Resolved";
  return "Open";
}

function workspaceTicketStatusClass(status) {
  const s = String(status || "open").toLowerCase();
  if (s === "assigned") return "assigned";
  if (s === "resolved") return "resolved";
  return "open";
}

function workspaceFormatDate(iso) {
  if (!iso) return "—";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return String(iso).slice(0, 10);
  return d.toLocaleDateString([], { month: "short", day: "numeric", year: "numeric" });
}

function renderWorkspaceOnboarding(data) {
  const body = $("#workspace-onboarding-body");
  const meta = $("#workspace-onboarding-meta");
  const badge = $("#workspace-onboarding-badge");
  const track = $("#workspace-onboarding-progress");
  const fill = $("#workspace-onboarding-progress-fill");
  if (!body) return;

  const total = Number(data?.total || 0);
  const completed = Number(data?.completed || 0);
  const pct = Number(data?.percentage || 0);

  if (total === 0) {
    if (meta) meta.textContent = "No onboarding checklist assigned to your account yet.";
    if (badge) badge.hidden = true;
    if (track) track.hidden = true;
    body.innerHTML =
      '<p class="empty workspace-empty">When HR adds you to onboarding, your first-week tasks will appear here.</p>';
    return;
  }

  const pending = total - completed;
  if (meta) {
    meta.textContent =
      pending > 0
        ? `${pending} task${pending === 1 ? "" : "s"} remaining · ${completed} of ${total} complete`
        : "All onboarding tasks complete — great work!";
  }
  if (badge) {
    badge.hidden = false;
    badge.textContent = `${Math.round(pct)}%`;
    badge.classList.toggle("done", pct >= 100);
  }
  if (track) track.hidden = false;
  if (fill) fill.style.width = `${Math.min(100, pct)}%`;

  const grouped = data.tasks_by_category || {};
  const categories = WORKSPACE_CATEGORY_ORDER.filter((c) => grouped[c]?.length).concat(
    Object.keys(grouped).filter((c) => !WORKSPACE_CATEGORY_ORDER.includes(c))
  );

  body.innerHTML = categories
    .map((cat) => {
      const tasks = grouped[cat] || [];
      const label = WORKSPACE_CATEGORY_LABELS[cat] || cat;
      const items = tasks
        .map((t) => {
          const done = t.status === "completed";
          const skipped = t.status === "skipped";
          const due = t.due_date ? `<span class="workspace-task-due">Due ${escapeHtml(workspaceFormatDate(t.due_date))}</span>` : "";
          const link = t.link_url
            ? `<a class="workspace-task-link" href="${escapeHtml(t.link_url)}" target="_blank" rel="noopener noreferrer">Open link</a>`
            : "";
          return `<li class="workspace-task${done ? " is-done" : ""}${skipped ? " is-skipped" : ""}" data-task-id="${escapeHtml(t.id)}">
            <label class="workspace-task-check">
              <input type="checkbox" class="workspace-task-toggle" data-task-id="${escapeHtml(t.id)}" ${done ? "checked disabled" : ""} ${skipped ? "disabled" : ""} />
              <span class="workspace-task-title">${escapeHtml(t.task_title)}</span>
            </label>
            ${due}${link}
          </li>`;
        })
        .join("");
      return `<section class="workspace-task-group">
        <h4>${escapeHtml(label)}</h4>
        <ul class="workspace-task-list">${items}</ul>
      </section>`;
    })
    .join("");

  body.querySelectorAll(".workspace-task-toggle").forEach((input) => {
    input.addEventListener("change", async () => {
      if (!input.checked) return;
      const taskId = input.dataset.taskId;
      input.disabled = true;
      try {
        const res = await api(`/me/tasks/${taskId}`, {
          method: "PATCH",
          body: JSON.stringify({ status: "completed" }),
        });
        if (!res.ok) {
          const err = await res.json().catch(() => ({}));
          throw new Error(formatApiError(err, `HTTP ${res.status}`));
        }
        await loadWorkspace();
      } catch (e) {
        input.disabled = false;
        input.checked = false;
        alert(e.message || "Could not update task.");
      }
    });
  });
}

function renderWorkspaceTickets(tickets) {
  const body = $("#workspace-tickets-body");
  const badge = $("#workspace-tickets-badge");
  if (!body) return;

  const list = Array.isArray(tickets) ? tickets : [];
  if (badge) badge.textContent = `${list.length} open`;

  if (!list.length) {
    body.innerHTML =
      '<p class="empty workspace-empty">No open tickets. Ask a question in chat — if we cannot answer, a ticket is created automatically.</p>';
    return;
  }

  body.innerHTML = `<ul class="workspace-ticket-list">${list
    .map((t) => {
      const status = workspaceTicketStatusLabel(t.status);
      const statusClass = workspaceTicketStatusClass(t.status);
      const type = t.ticket_type === "escalation" ? "Escalation" : "Helpdesk";
      const dept = t.assigned_department || t.department || "—";
      const notes = t.admin_notes
        ? `<p class="workspace-ticket-notes"><strong>Update:</strong> ${escapeHtml(t.admin_notes)}</p>`
        : "";
      return `<li class="workspace-ticket">
        <div class="workspace-ticket-top">
          <span class="workspace-ticket-status ${statusClass}">${escapeHtml(status)}</span>
          <span class="workspace-ticket-type">${escapeHtml(type)}</span>
          <time class="workspace-ticket-date">${escapeHtml(workspaceFormatDate(t.created_at))}</time>
        </div>
        <p class="workspace-ticket-question">${escapeHtml(t.question || "—")}</p>
        <p class="workspace-ticket-meta">Department: <span class="mono">${escapeHtml(dept)}</span></p>
        ${notes}
      </li>`;
    })
    .join("")}</ul>`;
}

function renderWorkspaceSummary(tasksData, tickets, reservations = []) {
  const wrap = $("#workspace-summary");
  if (!wrap) return;

  const taskTotal = Number(tasksData?.total || 0);
  const taskPending = taskTotal ? taskTotal - Number(tasksData?.completed || 0) : 0;
  const openTickets = Array.isArray(tickets) ? tickets.length : 0;

  wrap.innerHTML = `<div class="workspace-kpi-row">
    <article class="kpi-card">
      <p class="kpi-label">Onboarding tasks</p>
      <p class="kpi-value">${taskTotal ? `${taskPending} pending` : "—"}</p>
    </article>
    <article class="kpi-card">
      <p class="kpi-label">Open tickets</p>
      <p class="kpi-value">${openTickets}</p>
    </article>
    <article class="kpi-card muted-card">
      <p class="kpi-label">Guesthouse stays</p>
      <p class="kpi-value">${Array.isArray(reservations) ? reservations.length : "—"}</p>
    </article>
  </div>`;
}

function renderWorkspaceReservations(list) {
  const body = $("#workspace-reservations-body");
  const badge = $("#workspace-reservations-badge");
  if (!body) return;
  const rows = Array.isArray(list) ? list : [];
  if (badge) badge.textContent = `${rows.length} upcoming`;
  if (!rows.length) {
    body.innerHTML =
      '<p class="empty workspace-empty">No upcoming reservations. Ask in chat: "book the guesthouse next week".</p>';
    return;
  }
  body.innerHTML = `<ul class="workspace-ticket-list">${rows
    .map((r) => {
      const status = (r.status || "").replace(/_/g, " ");
      return `<li class="workspace-ticket" data-reservation-id="${escapeHtml(r.id)}">
        <div class="workspace-ticket-top">
          <span class="workspace-ticket-status">${escapeHtml(status)}</span>
          <span class="mono">${escapeHtml(r.confirmation_number || "")}</span>
          <time class="workspace-ticket-date">${escapeHtml(workspaceFormatDate(r.checkin_date))}</time>
        </div>
        <p class="workspace-ticket-question">${escapeHtml(r.guesthouse_name || "Guesthouse")} — Room ${escapeHtml(r.room_number || "?")}</p>
        <p class="workspace-ticket-meta">${escapeHtml(workspaceFormatDate(r.checkin_date))} → ${escapeHtml(workspaceFormatDate(r.checkout_date))}</p>
        <button type="button" class="chip danger workspace-res-cancel" data-id="${escapeHtml(r.id)}">Cancel</button>
      </li>`;
    })
    .join("")}</ul>`;
  body.querySelectorAll(".workspace-res-cancel").forEach((btn) => {
    btn.addEventListener("click", async () => {
      const id = btn.getAttribute("data-id");
      if (!id || !confirm("Cancel this reservation?")) return;
      const res = await api(`/reservations/${encodeURIComponent(id)}`, { method: "DELETE" });
      if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        alert(formatApiError(err, "Could not cancel reservation."));
        return;
      }
      loadWorkspace();
    });
  });
}

async function loadWorkspace() {
  const onboardingBody = $("#workspace-onboarding-body");
  const ticketsBody = $("#workspace-tickets-body");
  const reservationsBody = $("#workspace-reservations-body");
  if (onboardingBody) onboardingBody.innerHTML = '<p class="empty">Loading checklist…</p>';
  if (ticketsBody) ticketsBody.innerHTML = '<p class="empty">Loading tickets…</p>';
  if (reservationsBody) reservationsBody.innerHTML = '<p class="empty">Loading reservations…</p>';

  const [tasksRes, ticketsRes, reservationsRes] = await Promise.all([
    api("/me/tasks").catch(() => null),
    api("/me/tickets").catch(() => null),
    api("/reservations/my").catch(() => null),
  ]);

  let tasksData = { total: 0, completed: 0, percentage: 0, tasks_by_category: {} };
  if (tasksRes?.ok) {
    tasksData = await tasksRes.json();
  } else if (tasksRes && !tasksRes.ok) {
    const err = await tasksRes.json().catch(() => ({}));
    if (onboardingBody) {
      onboardingBody.innerHTML = `<p class="empty workspace-empty">${escapeHtml(formatApiError(err, "Could not load checklist."))}</p>`;
    }
  }

  let tickets = [];
  if (ticketsRes?.ok) {
    tickets = await ticketsRes.json();
  } else if (ticketsRes && !ticketsRes.ok) {
    const err = await ticketsRes.json().catch(() => ({}));
    if (ticketsBody) {
      ticketsBody.innerHTML = `<p class="empty workspace-empty">${escapeHtml(formatApiError(err, "Could not load tickets."))}</p>`;
    }
  }

  let reservations = [];
  if (reservationsRes?.ok) {
    reservations = await reservationsRes.json();
  } else if (reservationsRes && !reservationsRes.ok) {
    const err = await reservationsRes.json().catch(() => ({}));
    if (reservationsBody) {
      reservationsBody.innerHTML = `<p class="empty workspace-empty">${escapeHtml(formatApiError(err, "Could not load reservations."))}</p>`;
    }
  }

  renderWorkspaceSummary(tasksData, tickets, reservations);
  renderWorkspaceOnboarding(tasksData);
  renderWorkspaceTickets(tickets);
  renderWorkspaceReservations(reservations);
}

$("#refresh-workspace")?.addEventListener("click", () => loadWorkspace());

function employeeDisplayName(email) {
  if (!email) return "—";
  const local = String(email).split("@")[0] || email;
  return local
    .replace(/[._-]+/g, " ")
    .replace(/\b\w/g, (c) => c.toUpperCase());
}

function renderResAdminTable(container, rows, mode) {
  if (!container) return;
  if (!rows.length) {
    container.innerHTML = `<p class="empty">${mode === "pending" ? "No pending reservations." : "No approved reservations."}</p>`;
    return;
  }
  if (mode === "pending") {
    container.innerHTML = `<table class="res-admin-table"><thead><tr>
      <th>Confirmation</th><th>Employee</th><th>Property</th><th>Check-in</th><th>Check-out</th><th></th>
    </tr></thead><tbody>${rows
      .map(
        (r) => `<tr>
        <td class="mono">${escapeHtml(r.confirmation_number || "")}</td>
        <td>
          <span class="res-admin-name">${escapeHtml(employeeDisplayName(r.employee_email))}</span>
          <span class="res-admin-email">${escapeHtml(r.employee_email || "")}</span>
        </td>
        <td>${escapeHtml(r.guesthouse_name || "")} · Room ${escapeHtml(r.room_number || "")}</td>
        <td class="mono">${escapeHtml(r.checkin_date || "")}</td>
        <td class="mono">${escapeHtml(r.checkout_date || "")}</td>
        <td class="res-admin-actions">
          <button type="button" class="chip res-approve" data-id="${escapeHtml(r.id)}">Approve</button>
          <button type="button" class="chip danger res-reject" data-id="${escapeHtml(r.id)}">Reject</button>
        </td>
      </tr>`
      )
      .join("")}</tbody></table>`;
    container.querySelectorAll(".res-approve").forEach((btn) => {
      btn.addEventListener("click", async () => {
        const id = btn.getAttribute("data-id");
        const r = await api(`/admin/reservations/${encodeURIComponent(id)}/approve`, { method: "POST" });
        if (!r.ok) alert("Approve failed");
        else loadReservationsAdmin();
      });
    });
    container.querySelectorAll(".res-reject").forEach((btn) => {
      btn.addEventListener("click", async () => {
        const id = btn.getAttribute("data-id");
        const reason = prompt("Rejection reason:") || "Not approved";
        const r = await api(`/admin/reservations/${encodeURIComponent(id)}/reject`, {
          method: "POST",
          body: JSON.stringify({ reason }),
        });
        if (!r.ok) alert("Reject failed");
        else loadReservationsAdmin();
      });
    });
    return;
  }

  container.innerHTML = `<table class="res-admin-table"><thead><tr>
    <th>Employee</th><th>Property</th><th>Check-in</th><th>Check-out</th><th>Confirmation</th>
  </tr></thead><tbody>${rows
    .map(
      (r) => `<tr data-res-id="${escapeHtml(r.id)}" class="res-admin-approved-row">
      <td>
        <span class="res-admin-name">${escapeHtml(employeeDisplayName(r.employee_email))}</span>
        <span class="res-admin-email">${escapeHtml(r.employee_email || "")}</span>
      </td>
      <td>${escapeHtml(r.guesthouse_name || "")} · Room ${escapeHtml(r.room_number || "")}</td>
      <td class="mono">${escapeHtml(r.checkin_date || "")}</td>
      <td class="mono">${escapeHtml(r.checkout_date || "")}</td>
      <td class="mono">${escapeHtml(r.confirmation_number || "")}</td>
    </tr>`
    )
    .join("")}</tbody></table>`;
}

let _adminCalApi = null;

function mountAdminReservationCalendar(hostEl, guesthouses) {
  if (!hostEl) return;
  const widget = document.createElement("div");
  widget.className = "res-cal-widget";
  hostEl.innerHTML = "";
  hostEl.appendChild(widget);

  const ghSelect = $("#res-admin-gh-select");
  const emailInput = $("#res-admin-employee-email");
  const detailEl = $("#res-admin-cal-detail");
  const errEl = $("#res-admin-cal-error");

  const state = {
    guesthouses: guesthouses || [],
    guesthouseId: guesthouses?.[0]?.id || "",
    data: null,
    roomIdx: 0,
    month: new Date().toISOString().slice(0, 7),
    checkin: null,
    checkout: null,
    selectedReservation: null,
    loading: false,
    error: "",
  };

  function showError(msg) {
    state.error = msg || "";
    if (errEl) {
      errEl.textContent = state.error;
      errEl.hidden = !state.error;
    }
  }

  function dayMap(room) {
    const m = {};
    (room?.days || []).forEach((d) => { m[d.date] = d; });
    return m;
  }

  function room() {
    return state.data?.rooms?.[state.roomIdx] || state.data?.rooms?.[0];
  }

  function rangeAvailable(checkin, checkout) {
    const r = room();
    if (!r || !checkin || !checkout) return false;
    const map = dayMap(r);
    let d = checkin;
    while (d < checkout) {
      const entry = map[d];
      if (!entry || entry.status !== "available") return false;
      d = addDaysIso(d, 1);
    }
    return true;
  }

  function updateDetail() {
    if (!detailEl) return;
    const sel = state.selectedReservation;
    if (!sel) {
      detailEl.hidden = true;
      detailEl.innerHTML = "";
      return;
    }
    detailEl.hidden = false;
    detailEl.innerHTML =
      `<strong>${escapeHtml(employeeDisplayName(sel.employee_email))}</strong> · ${escapeHtml(sel.employee_email || "")}<br>` +
      `${escapeHtml(sel.confirmation_number || sel.reservation_id || "")} · ` +
      `${escapeHtml(sel.checkin_date || "")} → ${escapeHtml(sel.checkout_date || "")} · ` +
      `<span class="mono">${escapeHtml(sel.reservation_status || "")}</span>`;
  }

  async function loadMonth(ym) {
    if (!state.guesthouseId) return;
    const { first, last } = monthBounds(ym);
    const padStart = addDaysIso(first.toISOString().slice(0, 10), -7);
    const padEnd = addDaysIso(last.toISOString().slice(0, 10), 7);
    state.loading = true;
    showError("");
    render();
    try {
      const q = new URLSearchParams({
        guesthouse_id: state.guesthouseId,
        from_date: padStart,
        to_date: padEnd,
      });
      const res = await api(`/admin/reservations/calendar/widget?${q}`);
      if (res.ok) {
        const fresh = await res.json();
        state.data = { ...fresh, guesthouse_id: state.guesthouseId };
        state.month = ym;
      } else {
        const err = await res.json().catch(() => ({}));
        showError(formatApiError(err, "Could not load calendar."));
      }
    } catch (_) {
      showError("Could not refresh calendar.");
    } finally {
      state.loading = false;
      render();
    }
  }

  function onDayClick(iso, dayEntry) {
    if (state.loading) return;
    const status = dayEntry?.status || "available";
    if (status !== "available") {
      if (dayEntry?.reservation_id) {
        state.selectedReservation = {
          reservation_id: dayEntry.reservation_id,
          employee_email: dayEntry.employee_email,
          confirmation_number: dayEntry.confirmation_number,
          reservation_status: dayEntry.reservation_status,
          checkin_date: dayEntry.checkin_date,
          checkout_date: dayEntry.checkout_date,
        };
        state.checkin = dayEntry.checkin_date || null;
        state.checkout = dayEntry.checkout_date || null;
        if (emailInput && dayEntry.employee_email) {
          emailInput.value = dayEntry.employee_email;
        }
        updateDetail();
        render();
      }
      return;
    }
    const today = new Date().toISOString().slice(0, 10);
    if (iso < today) return;
    state.selectedReservation = null;
    updateDetail();
    if (!state.checkin || (state.checkin && state.checkout)) {
      state.checkin = iso;
      state.checkout = null;
    } else if (iso <= state.checkin) {
      state.checkin = iso;
      state.checkout = null;
    } else {
      state.checkout = iso;
      if (!rangeAvailable(state.checkin, state.checkout)) {
        showError("Selected range includes unavailable dates.");
        state.checkout = null;
      } else {
        showError("");
      }
    }
    render();
  }

  function render() {
    if (!state.data) {
      widget.innerHTML = '<p class="empty">Select a property to load the calendar.</p>';
      return;
    }
    const r = room();
    const map = dayMap(r);
    const { first, last, label } = monthBounds(state.month);
    const today = new Date().toISOString().slice(0, 10);

    const header = `<div class="res-cal-header">
      <span class="res-cal-title">${escapeHtml(state.data.guesthouse_name || "Guesthouse")}</span>
      <div class="res-cal-rooms">${(state.data.rooms || [])
        .map(
          (rm, i) =>
            `<button type="button" class="res-cal-room-btn${i === state.roomIdx ? " active" : ""}" data-room-idx="${i}">Room ${escapeHtml(rm.room_number)}</button>`
        )
        .join("")}</div>
    </div>`;

    const legend = `<div class="res-cal-legend">
      <span><i class="res-cal-swatch available"></i> Available</span>
      <span><i class="res-cal-swatch pending"></i> Awaiting confirmation</span>
      <span><i class="res-cal-swatch confirmed"></i> Confirmed / unavailable</span>
    </div>`;

    const nav = `<div class="res-cal-nav">
      <button type="button" data-nav="prev" ${state.loading ? "disabled" : ""} aria-label="Previous month">‹</button>
      <span class="res-cal-month-label">${escapeHtml(label)}${state.loading ? " …" : ""}</span>
      <button type="button" data-nav="next" ${state.loading ? "disabled" : ""} aria-label="Next month">›</button>
    </div>`;

    const weekdays = `<div class="res-cal-weekdays">${RES_CAL_WEEKDAYS.map((d) => `<span>${d}</span>`).join("")}</div>`;

    const cells = [];
    const startPad = first.getDay();
    const daysInMonth = last.getDate();
    const totalSlots = Math.ceil((startPad + daysInMonth) / 7) * 7;
    for (let slot = 0; slot < totalSlots; slot++) {
      const day = slot - startPad + 1;
      if (day < 1 || day > daysInMonth) {
        cells.push('<div class="res-cal-day empty" aria-hidden="true"></div>');
        continue;
      }
      const iso = `${state.month}-${String(day).padStart(2, "0")}`;
      const entry = map[iso] || { date: iso, status: "available" };
      const status = entry.status || "available";
      const isPast = iso < today;
      let cls = `res-cal-day ${status}`;
      if (isPast) cls += " past";
      if (iso === state.checkin || iso === state.checkout) cls += " selected";
      if (state.checkin && state.checkout && iso > state.checkin && iso < state.checkout) cls += " in-range";
      const disabled = state.loading || (status === "available" && isPast);
      cells.push(
        `<button type="button" class="${cls}" data-date="${iso}" ${disabled ? "disabled" : ""}>${day}</button>`
      );
    }

    const sel = state.checkin
      ? `<p class="res-cal-selection">Check-in: <strong>${escapeHtml(formatResCalDate(state.checkin))}</strong>` +
        (state.checkout ? ` · Out: <strong>${escapeHtml(formatResCalDate(state.checkout))}</strong>` : " · pick check-out") +
        `</p>`
      : "";

    widget.innerHTML =
      header +
      legend +
      nav +
      weekdays +
      `<div class="res-cal-grid">${cells.join("")}</div>` +
      (sel ? `<div class="res-cal-footer">${sel}</div>` : "");

    widget.querySelectorAll(".res-cal-room-btn").forEach((btn) => {
      btn.addEventListener("click", () => {
        state.roomIdx = Number(btn.dataset.roomIdx) || 0;
        state.checkin = null;
        state.checkout = null;
        state.selectedReservation = null;
        showError("");
        updateDetail();
        render();
      });
    });

    widget.querySelector('[data-nav="prev"]')?.addEventListener("click", () => {
      const [y, m] = state.month.split("-").map(Number);
      const prev = m === 1 ? `${y - 1}-12` : `${y}-${String(m - 1).padStart(2, "0")}`;
      loadMonth(prev);
    });
    widget.querySelector('[data-nav="next"]')?.addEventListener("click", () => {
      const [y, m] = state.month.split("-").map(Number);
      const next = m === 12 ? `${y + 1}-01` : `${y}-${String(m + 1).padStart(2, "0")}`;
      loadMonth(next);
    });

    widget.querySelectorAll(".res-cal-day[data-date]").forEach((btn) => {
      btn.addEventListener("click", () => {
        const iso = btn.dataset.date;
        onDayClick(iso, map[iso]);
      });
    });
  }

  async function reserveForEmployee() {
    const r = room();
    const email = emailInput?.value?.trim();
    if (!r || !email || !state.checkin || !state.checkout) {
      showError("Enter employee email and select check-in / check-out dates.");
      return;
    }
    if (!rangeAvailable(state.checkin, state.checkout)) {
      showError("Selected dates are not available.");
      return;
    }
    state.loading = true;
    showError("");
    render();
    try {
      const res = await api("/admin/reservations", {
        method: "POST",
        body: JSON.stringify({
          employee_email: email,
          room_id: r.room_id,
          checkin_date: state.checkin,
          checkout_date: state.checkout,
          purpose: "Business travel",
          auto_confirm: true,
        }),
      });
      const body = await res.json().catch(() => ({}));
      if (!res.ok) {
        showError(formatApiError(body, "Could not create reservation."));
        state.loading = false;
        render();
        return;
      }
      state.checkin = null;
      state.checkout = null;
      state.selectedReservation = null;
      updateDetail();
      await loadReservationsAdmin();
    } catch (err) {
      showError(err.message || "Could not create reservation.");
      state.loading = false;
      render();
    }
  }

  async function modifySelected() {
    const id = state.selectedReservation?.reservation_id;
    if (!id || !state.checkin || !state.checkout) {
      showError("Select a reservation and new check-in / check-out dates.");
      return;
    }
    state.loading = true;
    showError("");
    render();
    try {
      const res = await api(`/admin/reservations/${encodeURIComponent(id)}`, {
        method: "PUT",
        body: JSON.stringify({
          checkin_date: state.checkin,
          checkout_date: state.checkout,
        }),
      });
      const body = await res.json().catch(() => ({}));
      if (!res.ok) {
        showError(formatApiError(body, "Could not modify reservation."));
        state.loading = false;
        render();
        return;
      }
      state.selectedReservation = null;
      updateDetail();
      await loadReservationsAdmin();
    } catch (err) {
      showError(err.message || "Could not modify reservation.");
      state.loading = false;
      render();
    }
  }

  async function cancelSelected() {
    const id = state.selectedReservation?.reservation_id;
    if (!id) {
      showError("Click a booked date to select a reservation to cancel.");
      return;
    }
    if (!confirm("Cancel this reservation and free the dates?")) return;
    state.loading = true;
    showError("");
    render();
    try {
      const res = await api(`/admin/reservations/${encodeURIComponent(id)}`, { method: "DELETE" });
      const body = await res.json().catch(() => ({}));
      if (!res.ok) {
        showError(formatApiError(body, "Could not cancel reservation."));
        state.loading = false;
        render();
        return;
      }
      state.selectedReservation = null;
      state.checkin = null;
      state.checkout = null;
      updateDetail();
      await loadReservationsAdmin();
    } catch (err) {
      showError(err.message || "Could not cancel reservation.");
      state.loading = false;
      render();
    }
  }

  async function approveSelected() {
    const id = state.selectedReservation?.reservation_id;
    if (!id) {
      showError("Click a pending reservation on the calendar.");
      return;
    }
    const res = await api(`/admin/reservations/${encodeURIComponent(id)}/approve`, { method: "POST" });
    if (!res.ok) showError("Approve failed.");
    else await loadReservationsAdmin();
  }

  async function rejectSelected() {
    const id = state.selectedReservation?.reservation_id;
    if (!id) {
      showError("Click a pending reservation on the calendar.");
      return;
    }
    const reason = prompt("Rejection reason:") || "Not approved";
    const res = await api(`/admin/reservations/${encodeURIComponent(id)}/reject`, {
      method: "POST",
      body: JSON.stringify({ reason }),
    });
    if (!res.ok) showError("Reject failed.");
    else await loadReservationsAdmin();
  }

  if (ghSelect) {
    ghSelect.innerHTML = state.guesthouses
      .map((g) => `<option value="${escapeHtml(g.id)}">${escapeHtml(g.name)}</option>`)
      .join("");
    ghSelect.value = state.guesthouseId;
    ghSelect.onchange = () => {
      state.guesthouseId = ghSelect.value;
      state.roomIdx = 0;
      state.checkin = null;
      state.checkout = null;
      state.selectedReservation = null;
      updateDetail();
      loadMonth(state.month);
    };
  }

  $("#res-admin-cal-reserve")?.addEventListener("click", reserveForEmployee);
  $("#res-admin-cal-modify")?.addEventListener("click", modifySelected);
  $("#res-admin-cal-cancel")?.addEventListener("click", cancelSelected);
  $("#res-admin-cal-approve")?.addEventListener("click", approveSelected);
  $("#res-admin-cal-reject")?.addEventListener("click", rejectSelected);

  _adminCalApi = {
    reload: () => loadMonth(state.month),
    setGuesthouse: (id) => {
      state.guesthouseId = id;
      if (ghSelect) ghSelect.value = id;
      loadMonth(state.month);
    },
  };

  if (state.guesthouseId) loadMonth(state.month);
  else render();
}

async function loadReservationsAdmin() {
  const pendingBody = $("#reservations-pending-body");
  const approvedBody = $("#reservations-approved-body");
  if (pendingBody) pendingBody.innerHTML = '<p class="empty">Loading…</p>';
  if (approvedBody) approvedBody.innerHTML = '<p class="empty">Loading…</p>';

  const [pendingRes, approvedRes, ghRes] = await Promise.all([
    api("/admin/reservations/pending"),
    api("/admin/reservations?status=confirmed"),
    api("/admin/guesthouses"),
  ]);

  if (!pendingRes.ok) {
    const err = await pendingRes.json().catch(() => ({}));
    if (pendingBody) {
      pendingBody.innerHTML = `<p class="empty">${escapeHtml(formatApiError(err, "Could not load pending reservations."))}</p>`;
    }
  } else {
    renderResAdminTable(pendingBody, await pendingRes.json(), "pending");
  }

  if (!approvedRes.ok) {
    const err = await approvedRes.json().catch(() => ({}));
    if (approvedBody) {
      approvedBody.innerHTML = `<p class="empty">${escapeHtml(formatApiError(err, "Could not load approved reservations."))}</p>`;
    }
  } else {
    const approved = (await approvedRes.json()).sort(
      (a, b) => String(a.checkin_date).localeCompare(String(b.checkin_date))
    );
    renderResAdminTable(approvedBody, approved, "approved");
  }

  const host = $("#res-admin-cal-host");
  if (ghRes.ok && host) {
    const guesthouses = await ghRes.json();
    if (!_adminCalApi) {
      mountAdminReservationCalendar(host, guesthouses);
    } else {
      _adminCalApi.reload();
    }
  }
}

$("#refresh-reservations-admin")?.addEventListener("click", () => loadReservationsAdmin());

const ONBOARDING_CATEGORY_COLORS = {
  identity: "#6c4dff",
  payroll: "#3dcfb0",
  documents: "#f0b429",
  benefits: "#e2556f",
  apps: "#2a9f84",
};

function onboardingProgressCell(completed, total, pct) {
  const p = pct != null ? Number(pct) : total ? Math.round((100 * completed) / total) : 0;
  return `<div class="onboarding-progress-cell">
    <div class="onboarding-progress-track"><div class="onboarding-progress-fill" style="width:${Math.min(100, p)}%"></div></div>
    <span class="mono">${completed}/${total} (${p}%)</span>
  </div>`;
}

function onboardingStatusTag(complete) {
  if (complete) return '<span class="tag">Complete</span>';
  return '<span class="tag cached">In progress</span>';
}

function onboardingTaskStatusTag(status) {
  const s = (status || "pending").toLowerCase();
  if (s === "completed") return '<span class="tag">Done</span>';
  if (s === "skipped") return '<span class="tag unknown">Skipped</span>';
  return '<span class="tag cached">Pending</span>';
}

function onboardingActiveTag(active) {
  if (active) return '<span class="tag">Active</span>';
  return '<span class="tag unknown">Inactive</span>';
}

function onboardingActionButtons(email) {
  return `<div class="onboarding-row-actions">
    <button type="button" class="chip onboarding-edit-btn" data-email="${escapeHtml(email)}">Edit</button>
    <button type="button" class="chip danger onboarding-delete-btn" data-email="${escapeHtml(email)}">Delete</button>
  </div>`;
}

function bindOnboardingEmployeeActions(container) {
  if (!container) return;
  container.querySelectorAll(".onboarding-edit-btn").forEach((btn) => {
    btn.addEventListener("click", (e) => {
      e.stopPropagation();
      openOnboardingEditModal(btn.dataset.email);
    });
  });
  container.querySelectorAll(".onboarding-delete-btn").forEach((btn) => {
    btn.addEventListener("click", (e) => {
      e.stopPropagation();
      deleteOnboardingEmployee(btn.dataset.email);
    });
  });
  container.querySelectorAll(".onboarding-row").forEach((row) => {
    row.addEventListener("click", () => loadOnboardingEmployeeDetail(row.dataset.email));
  });
}

function bindOnboardingTaskActions(container, email) {
  if (!container) return;
  container.querySelectorAll(".onboarding-task-save").forEach((btn) => {
    btn.addEventListener("click", async () => {
      const row = btn.closest("tr");
      const taskId = row?.dataset.taskId;
      if (!taskId) return;
      const payload = {
        task_title: row.querySelector('[data-field="task_title"]')?.value?.trim(),
        category: row.querySelector('[data-field="category"]')?.value,
        status: row.querySelector('[data-field="status"]')?.value,
        due_date: row.querySelector('[data-field="due_date"]')?.value || null,
        link_url: row.querySelector('[data-field="link_url"]')?.value?.trim() || null,
        sort_order: parseInt(row.querySelector('[data-field="sort_order"]')?.value || "0", 10),
      };
      try {
        const res = await api(`/admin/tasks/${encodeURIComponent(taskId)}`, {
          method: "PATCH",
          body: JSON.stringify(payload),
        });
        const data = await res.json();
        if (!res.ok) throw new Error(formatApiError(data, "Could not save task"));
        btn.textContent = "Saved";
        setTimeout(() => {
          btn.textContent = "Save";
        }, 1200);
        await loadOnboardingEmployeeDetail(email);
        loadOnboarding();
      } catch (ex) {
        alert(ex.message || "Save failed");
      }
    });
  });
  container.querySelectorAll(".onboarding-task-delete").forEach((btn) => {
    btn.addEventListener("click", async (e) => {
      e.stopPropagation();
      if (!confirm("Delete this task permanently?")) return;
      try {
        const res = await api(`/admin/tasks/${encodeURIComponent(btn.dataset.taskId)}`, {
          method: "DELETE",
        });
        if (!res.ok && res.status !== 204) {
          const data = await res.json().catch(() => ({}));
          throw new Error(formatApiError(data, "Could not delete task"));
        }
        await loadOnboardingEmployeeDetail(email);
        loadOnboarding();
      } catch (ex) {
        alert(ex.message || "Delete failed");
      }
    });
  });
}

function bindOnboardingReminderActions(container, email) {
  if (!container) return;
  container.querySelectorAll(".onboarding-reminder-save").forEach((btn) => {
    btn.addEventListener("click", async () => {
      const row = btn.closest("tr");
      const reminderId = row?.dataset.reminderId;
      if (!reminderId) return;
      const sentRaw = row.querySelector('[data-field="sent_at"]')?.value?.trim() || "";
      const payload = {
        reminder_type: row.querySelector('[data-field="reminder_type"]')?.value?.trim(),
        delivery_status: row.querySelector('[data-field="delivery_status"]')?.value,
        channel: row.querySelector('[data-field="channel"]')?.value,
      };
      if (sentRaw) payload.sent_at = sentRaw.includes("T") ? sentRaw : sentRaw.replace(" ", "T");
      try {
        const res = await api(`/admin/reminders/${encodeURIComponent(reminderId)}`, {
          method: "PATCH",
          body: JSON.stringify(payload),
        });
        const data = await res.json();
        if (!res.ok) throw new Error(formatApiError(data, "Could not save reminder"));
        btn.textContent = "Saved";
        setTimeout(() => {
          btn.textContent = "Save";
        }, 1200);
        await loadOnboardingEmployeeDetail(email);
      } catch (ex) {
        alert(ex.message || "Save failed");
      }
    });
  });
  container.querySelectorAll(".onboarding-reminder-delete").forEach((btn) => {
    btn.addEventListener("click", async (e) => {
      e.stopPropagation();
      if (!confirm("Delete this reminder record?")) return;
      try {
        const res = await api(`/admin/reminders/${encodeURIComponent(btn.dataset.reminderId)}`, {
          method: "DELETE",
        });
        if (!res.ok && res.status !== 204) {
          const data = await res.json().catch(() => ({}));
          throw new Error(formatApiError(data, "Could not delete reminder"));
        }
        await loadOnboardingEmployeeDetail(email);
      } catch (ex) {
        alert(ex.message || "Delete failed");
      }
    });
  });
}

async function deleteOnboardingEmployee(email) {
  if (currentRole() !== "admin") return;
  if (
    !confirm(
      `Delete employee ${email} and all their tasks and reminders? This cannot be undone.`
    )
  ) {
    return;
  }
  try {
    const res = await api(`/admin/employees/${encodeURIComponent(email)}`, {
      method: "DELETE",
    });
    if (!res.ok && res.status !== 204) {
      const data = await res.json().catch(() => ({}));
      throw new Error(formatApiError(data, "Could not delete employee"));
    }
    if (_onboardingSelectedEmail === email) {
      _onboardingSelectedEmail = "";
      const wrap = $("#onboarding-drilldown");
      if (wrap) wrap.hidden = true;
    }
    await loadOnboarding();
  } catch (ex) {
    alert(ex.message || "Delete failed");
  }
}

function openOnboardingEditModal(email) {
  const modal = $("#onboarding-edit-modal");
  const form = $("#onboarding-edit-form");
  const err = $("#onboarding-edit-error");
  if (!modal || !form) return;
  err.hidden = true;
  modal.hidden = false;
  document.body.classList.add("board-modal-open");
  api(`/admin/employees/${encodeURIComponent(email)}`)
    .then((r) => r.json())
    .then((data) => {
      const emp = data.employee || {};
      $("#onboarding-edit-title").textContent = `Edit — ${emp.full_name || email}`;
      $("#onboarding-edit-email").value = emp.email || email;
      form.full_name.value = emp.full_name || "";
      form.employee_id.value = emp.employee_id || "";
      form.department.value = emp.department || "engineering";
      form.role_title.value = emp.role_title || "";
      form.manager_email.value = emp.manager_email || "";
      form.joining_date.value = emp.joining_date || "";
      form.onboarding_complete.value = emp.onboarding_complete ? "true" : "false";
      form.active.value = emp.active !== false ? "true" : "false";
    })
    .catch((ex) => {
      err.hidden = false;
      err.textContent = ex.message || "Could not load employee";
    });
}

function closeOnboardingEditModal() {
  const modal = $("#onboarding-edit-modal");
  if (modal) modal.hidden = true;
  document.body.classList.remove("board-modal-open");
}

const ONBOARDING_TASK_CATEGORIES = ["identity", "payroll", "benefits", "documents", "apps"];
const ONBOARDING_TASK_STATUSES = ["pending", "completed", "skipped"];
const ONBOARDING_REMINDER_STATUSES = ["sent", "failed", "opened"];
const ONBOARDING_REMINDER_CHANNELS = ["email", "slack", "teams"];

function onboardingDbSelect(value, options, field) {
  return `<select class="onboarding-db-input" data-field="${field}">${options
    .map(
      (o) =>
        `<option value="${o}"${String(value || "").toLowerCase() === o ? " selected" : ""}>${o}</option>`
    )
    .join("")}</select>`;
}

function onboardingDbInput(value, field, type = "text", extra = "") {
  const v = value == null ? "" : String(value);
  return `<input class="onboarding-db-input" type="${type}" data-field="${field}" value="${escapeHtml(v)}" ${extra} />`;
}

function formatReminderInput(sentAt) {
  if (!sentAt) return "";
  return sentAt.replace("T", " ").slice(0, 19);
}

function renderOnboardingTaskRow(t) {
  return `<tr data-task-id="${escapeHtml(t.id)}">
    <td class="mono onboarding-db-readonly" title="${escapeHtml(t.id)}">${escapeHtml(t.task_key)}</td>
    <td>${onboardingDbInput(t.task_title, "task_title")}</td>
    <td>${onboardingDbSelect(t.category, ONBOARDING_TASK_CATEGORIES, "category")}</td>
    <td>${onboardingDbSelect(t.status, ONBOARDING_TASK_STATUSES, "status")}</td>
    <td>${onboardingDbInput(t.due_date, "due_date", "date")}</td>
    <td>${onboardingDbInput(t.link_url, "link_url")}</td>
    <td>${onboardingDbInput(t.sort_order, "sort_order", "number", 'min="0" style="width:4rem"')}</td>
    <td class="onboarding-row-actions">
      <button type="button" class="chip onboarding-task-save">Save</button>
      <button type="button" class="chip danger onboarding-task-delete" data-task-id="${escapeHtml(t.id)}">Del</button>
    </td>
  </tr>`;
}

function renderOnboardingReminderRow(r) {
  return `<tr data-reminder-id="${escapeHtml(r.id)}">
    <td>${onboardingDbInput(formatReminderInput(r.sent_at), "sent_at")}</td>
    <td>${onboardingDbInput(r.reminder_type, "reminder_type")}</td>
    <td>${onboardingDbSelect(r.delivery_status, ONBOARDING_REMINDER_STATUSES, "delivery_status")}</td>
    <td>${onboardingDbSelect(r.channel || "email", ONBOARDING_REMINDER_CHANNELS, "channel")}</td>
    <td class="onboarding-row-actions">
      <button type="button" class="chip onboarding-reminder-save">Save</button>
      <button type="button" class="chip danger onboarding-reminder-delete" data-reminder-id="${escapeHtml(r.id)}">Del</button>
    </td>
  </tr>`;
}

function onboardingEmployeesUrl() {
  if (_onboardingFilter === "active") return "/admin/employees?onboarding_complete=false";
  if (_onboardingFilter === "complete") return "/admin/employees?onboarding_complete=true";
  return "/admin/employees";
}

async function loadOnboarding() {
  if (currentRole() !== "admin") return;

  const [overviewRes, employeesRes] = await Promise.all([
    api("/admin/onboarding/overview"),
    api(onboardingEmployeesUrl()),
  ]);
  const overview = await overviewRes.json();
  const employees = await employeesRes.json();

  const rateByEmail = {};
  (overview.completion_rates || []).forEach((r) => {
    rateByEmail[r.email] = r;
  });

  const kpis = $("#onboarding-kpis");
  if (kpis) {
    const activeCount = (overview.completion_rates || []).length;
    const followUp = (overview.employees_needing_followup || []).length;
    const pendingTotal = Object.values(overview.pending_by_category || {}).reduce(
      (s, n) => s + (n || 0),
      0
    );
    kpis.innerHTML = `
      <article class="kpi-card">
        <p class="kpi-label">New hires this week</p>
        <h2>${overview.new_hires_this_week || 0}</h2>
        <p class="kpi-sub">calendar week</p>
      </article>
      <article class="kpi-card">
        <p class="kpi-label">Active onboardings</p>
        <h2>${activeCount}</h2>
        <p class="kpi-sub">incomplete checklists</p>
      </article>
      <article class="kpi-card">
        <p class="kpi-label">Needs follow-up</p>
        <h2>${followUp}</h2>
        <p class="kpi-sub">day 5+ incomplete</p>
      </article>
      <article class="kpi-card">
        <p class="kpi-label">Pending tasks</p>
        <h2>${pendingTotal}</h2>
        <p class="kpi-sub">across categories</p>
      </article>`;
  }

  barList($("#onboarding-category-bars"), overview.pending_by_category || {}, ONBOARDING_CATEGORY_COLORS);

  const followBody = $("#onboarding-followup-table tbody");
  const followRows = overview.employees_needing_followup || [];
  if (followBody) {
    if (!followRows.length) {
      followBody.innerHTML = `<tr><td colspan="3">No employees need follow-up right now.</td></tr>`;
    } else {
      followBody.innerHTML = followRows
        .map(
          (r) => `<tr class="onboarding-row" data-email="${escapeHtml(r.email)}" style="cursor:pointer">
            <td>${escapeHtml(r.name)}</td>
            <td class="mono">Day ${r.onboarding_day}</td>
            <td>${onboardingProgressCell(r.completed, r.total, r.percentage)}</td>
          </tr>`
        )
        .join("");
      followBody.querySelectorAll(".onboarding-row").forEach((row) => {
        row.addEventListener("click", () => loadOnboardingEmployeeDetail(row.dataset.email));
      });
    }
  }

  const empBody = $("#onboarding-employees-table tbody");
  if (empBody) {
    if (!employees.length) {
      empBody.innerHTML = `<tr><td colspan="8">No employees yet — add a new hire to get started.</td></tr>`;
    } else {
      empBody.innerHTML = employees
        .map((e) => {
          const rate = rateByEmail[e.email] || { completed: 0, total: 0, percentage: 0 };
          return `<tr class="onboarding-row" data-email="${escapeHtml(e.email)}" style="cursor:pointer">
            <td>${escapeHtml(e.full_name)}</td>
            <td>${escapeHtml(e.email)}</td>
            <td>${escapeHtml(e.department)}</td>
            <td class="mono">${escapeHtml(e.joining_date || "—")}</td>
            <td>${onboardingProgressCell(rate.completed, rate.total, rate.percentage)}</td>
            <td>${onboardingStatusTag(e.onboarding_complete)}</td>
            <td>${onboardingActiveTag(e.active !== false)}</td>
            <td>${onboardingActionButtons(e.email)}</td>
          </tr>`;
        })
        .join("");
      bindOnboardingEmployeeActions(empBody);
    }
  }
}

async function loadOnboardingEmployeeDetail(email) {
  _onboardingSelectedEmail = email;
  const wrap = $("#onboarding-drilldown");
  const title = $("#onboarding-drill-title");
  const sub = $("#onboarding-drill-sub");
  const meta = $("#onboarding-drill-meta");
  const tasksBody = $("#onboarding-tasks-table tbody");
  const remindersBody = $("#onboarding-reminders-table tbody");
  if (!wrap || !tasksBody || !remindersBody) return;

  wrap.hidden = false;
  title.textContent = email;
  sub.textContent = "Loading…";
  meta.innerHTML = "";
  tasksBody.innerHTML = `<tr><td colspan="8">Loading…</td></tr>`;
  remindersBody.innerHTML = `<tr><td colspan="5">Loading…</td></tr>`;
  wrap.scrollIntoView({ behavior: "smooth", block: "nearest" });

  const data = await api(`/admin/onboarding/employee/${encodeURIComponent(email)}`).then((r) =>
    r.json()
  );
  const emp = data.employee || {};
  title.textContent = emp.full_name || email;
  sub.textContent = `${email} · ${emp.department || "—"} · joined ${emp.joining_date || "—"}`;
  meta.innerHTML = `
    <div class="onboarding-drill-stat">
      <span>Progress</span>
      <strong>${data.completed}/${data.total} (${data.percentage}%)</strong>
    </div>
    <div class="onboarding-drill-stat">
      <span>Manager</span>
      <strong>${escapeHtml(emp.manager_email || "—")}</strong>
    </div>
    <div class="onboarding-drill-stat">
      <span>Role</span>
      <strong>${escapeHtml(emp.role_title || "—")}</strong>
    </div>
    <div class="onboarding-drill-stat">
      <span>Status</span>
      <strong>${emp.onboarding_complete ? "Complete" : "In progress"} · ${emp.active !== false ? "Active" : "Inactive"}</strong>
    </div>
    <div class="onboarding-drill-stat">
      <span>Created</span>
      <strong class="mono">${escapeHtml((emp.created_at || "").replace("T", " ").slice(0, 19) || "—")}</strong>
    </div>
    <div class="onboarding-drill-stat">
      <span>Started</span>
      <strong class="mono">${escapeHtml((emp.onboarding_started_at || "—").replace("T", " ").slice(0, 19))}</strong>
    </div>`;

  const tasks = data.tasks || [];
  if (!tasks.length) {
    tasksBody.innerHTML = `<tr><td colspan="8">No tasks.</td></tr>`;
  } else {
    tasksBody.innerHTML = tasks.map(renderOnboardingTaskRow).join("");
    bindOnboardingTaskActions(tasksBody, email);
  }

  const reminders = data.reminders || [];
  if (!reminders.length) {
    remindersBody.innerHTML = `<tr><td colspan="5">No reminders sent yet.</td></tr>`;
  } else {
    remindersBody.innerHTML = reminders.map(renderOnboardingReminderRow).join("");
    bindOnboardingReminderActions(remindersBody, email);
  }
}

function setOnboardingCreatePanel(open) {
  const panel = $("#onboarding-create-panel");
  const err = $("#onboarding-create-error");
  const ok = $("#onboarding-create-success");
  if (!panel) return;
  panel.hidden = !open;
  if (err) err.hidden = true;
  if (ok) ok.hidden = true;
  if (open) {
    const dateInput = $("#onboarding-create-form input[name=joining_date]");
    if (dateInput && !dateInput.value) {
      dateInput.value = new Date().toISOString().slice(0, 10);
    }
  }
}

$("#refresh-onboarding")?.addEventListener("click", loadOnboarding);

$("#onboarding-toggle-create")?.addEventListener("click", () => {
  const panel = $("#onboarding-create-panel");
  setOnboardingCreatePanel(panel?.hidden);
});

$("#onboarding-cancel-create")?.addEventListener("click", () => setOnboardingCreatePanel(false));

$("#onboarding-edit-employee")?.addEventListener("click", () => {
  if (_onboardingSelectedEmail) openOnboardingEditModal(_onboardingSelectedEmail);
});

$("#onboarding-delete-employee")?.addEventListener("click", () => {
  if (_onboardingSelectedEmail) deleteOnboardingEmployee(_onboardingSelectedEmail);
});

$("#onboarding-edit-close")?.addEventListener("click", closeOnboardingEditModal);
$("#onboarding-edit-cancel")?.addEventListener("click", closeOnboardingEditModal);
$("#onboarding-edit-backdrop")?.addEventListener("click", closeOnboardingEditModal);

$("#onboarding-edit-form")?.addEventListener("submit", async (e) => {
  e.preventDefault();
  if (currentRole() !== "admin") return;
  const form = e.target;
  const err = $("#onboarding-edit-error");
  const save = $("#onboarding-edit-save");
  const email = String($("#onboarding-edit-email")?.value || "").trim();
  if (err) err.hidden = true;
  if (save) {
    save.disabled = true;
    save.textContent = "Saving…";
  }
  const payload = {
    full_name: String(form.full_name.value || "").trim(),
    employee_id: String(form.employee_id.value || "").trim() || null,
    department: String(form.department.value || "").trim(),
    role_title: String(form.role_title.value || "").trim(),
    manager_email: String(form.manager_email.value || "").trim() || null,
    joining_date: String(form.joining_date.value || "").trim(),
    onboarding_complete: form.onboarding_complete.value === "true",
    active: form.active.value === "true",
  };
  try {
    const res = await api(`/admin/employees/${encodeURIComponent(email)}`, {
      method: "PUT",
      body: JSON.stringify(payload),
    });
    const data = await res.json();
    if (!res.ok) {
      throw new Error(formatApiError(data, "Could not save employee"));
    }
    closeOnboardingEditModal();
    await loadOnboarding();
    if (email) await loadOnboardingEmployeeDetail(email);
  } catch (ex) {
    if (err) {
      err.hidden = false;
      err.textContent = ex.message || "Save failed";
    }
  } finally {
    if (save) {
      save.disabled = false;
      save.textContent = "Save changes";
    }
  }
});

$$(".onboarding-filter").forEach((btn) => {
  btn.addEventListener("click", () => {
    _onboardingFilter = btn.dataset.filter || "all";
    $$(".onboarding-filter").forEach((b) => b.classList.toggle("active", b === btn));
    loadOnboarding();
  });
});

$("#onboarding-create-form")?.addEventListener("submit", async (e) => {
  e.preventDefault();
  if (currentRole() !== "admin") return;
  const form = e.target;
  const err = $("#onboarding-create-error");
  const ok = $("#onboarding-create-success");
  const submit = $("#onboarding-submit-create");
  if (err) err.hidden = true;
  if (ok) ok.hidden = true;
  if (submit) {
    submit.disabled = true;
    submit.textContent = "Creating…";
  }
  const fd = new FormData(form);
  const payload = {
    email: String(fd.get("email") || "").trim(),
    full_name: String(fd.get("full_name") || "").trim(),
    employee_id: String(fd.get("employee_id") || "").trim() || null,
    department: String(fd.get("department") || "").trim(),
    role_title: String(fd.get("role_title") || "").trim(),
    manager_email: String(fd.get("manager_email") || "").trim() || null,
    joining_date: String(fd.get("joining_date") || "").trim(),
    provision_login: fd.get("provision_login") === "on",
  };
  try {
    const res = await api("/admin/employees", {
      method: "POST",
      body: JSON.stringify(payload),
    });
    const data = await res.json();
    if (!res.ok) {
      throw new Error(formatApiError(data, "Could not create employee"));
    }
    if (ok) {
      ok.hidden = false;
      let msg = `Created ${data.employee.full_name} with ${data.tasks_generated} onboarding tasks.`;
      if (data.temp_password) {
        msg += ` Temp password (share securely): ${data.temp_password}`;
      }
      ok.textContent = msg;
    }
    form.reset();
    await loadOnboarding();
    if (data.employee?.email) {
      loadOnboardingEmployeeDetail(data.employee.email);
    }
  } catch (ex) {
    if (err) {
      err.hidden = false;
      err.textContent = ex.message || "Create failed";
    }
  } finally {
    if (submit) {
      submit.disabled = false;
      submit.textContent = "Create & generate tasks";
    }
  }
});

(async function boot() {
  try {
    const auth = getAuth();
    if (!auth?.access_token) {
      showLogin();
      return;
    }
    const res = await api("/auth/me");
    if (!res.ok) throw new Error("bad session");
    const user = await res.json();
    setAuth({ access_token: auth.access_token, user });
    await enterApp();
  } catch (e) {
    console.error("boot failed", e);
    logout();
  }
})();
