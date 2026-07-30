const $ = (sel) => document.querySelector(sel);
const $$ = (sel) => [...document.querySelectorAll(sel)];

const AUTH_KEY = "ampcus_helpdesk_auth";

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
  clearAuth();
  clearChatUi?.();
  showLogin(message);
}

function showLogin(message) {
  $("#app-shell").hidden = true;
  $("#login-screen").hidden = false;
  document.body.classList.add("is-login");
  const err = $("#login-error");
  if (message) {
    err.hidden = false;
    err.textContent = message;
  } else {
    err.hidden = true;
    err.textContent = "";
  }
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
  const pill = $("#user-pill");
  if (pill) {
    const user = getAuth()?.user;
    pill.textContent = user?.role || "";
    pill.title = user ? `${user.name || ""} <${user.email}>` : "";
  }
  const roleEl = $("#chat-user-role");
  if (roleEl) {
    roleEl.textContent = role || "user";
  }
}

async function enterApp() {
  $("#login-screen").hidden = true;
  $("#app-shell").hidden = false;
  document.body.classList.remove("is-login");
  applyRoleGates();
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
  if ((name === "dashboard" || name === "insights") && !["agent", "admin"].includes(role)) {
    name = "chat";
  }
  $$(".view").forEach((v) => v.classList.remove("active"));
  $$(".nav-btn").forEach((b) => b.classList.toggle("active", b.dataset.view === name));
  const view = document.getElementById(`view-${name}`);
  if (view) view.classList.add("active");
  if (name === "dashboard") loadStats();
  if (name === "kb") loadKnowledgeBase();
  if (name === "tickets") loadTickets();
  if (name === "escalations") loadEscalations();
  if (name === "insights") loadInsights();
  if (name === "chat") {
    requestAnimationFrame(() => $("#chat-input")?.focus());
  }
}

$$(".nav-btn, [data-view].btn-primary").forEach((el) => {
  el.addEventListener("click", () => {
    if (el.dataset.view) switchView(el.dataset.view);
  });
});

$("#logout-btn")?.addEventListener("click", () => logout());

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

async function loadStats() {
  const [stats, health] = await Promise.all([
    api("/stats").then((r) => r.json()),
    fetch("/health").then((r) => r.json()),
  ]);

  $("#kpi-queries").textContent = stats.total_queries;
  $("#kpi-queries-sub").textContent = `${stats.cache_misses} misses`;
  $("#kpi-cache").textContent = `${stats.cache_hit_rate}%`;
  $("#kpi-cache-sub").textContent = `${stats.cache_hits} cache hits`;
  $("#kpi-tickets").textContent = stats.open_tickets;
  $("#kpi-tickets-sub").textContent = `${stats.unknown_tickets_created} unknown this session`;
  if ($("#kpi-escalations")) {
    $("#kpi-escalations").textContent = stats.open_escalations ?? 0;
    $("#kpi-escalations-sub").textContent = "high-severity HITL";
  }
  if ($("#kpi-esc-session")) {
    $("#kpi-esc-session").textContent = stats.escalated ?? 0;
  }
  $("#kpi-latency").textContent =
    stats.avg_latency_ms >= 1000
      ? `${(stats.avg_latency_ms / 1000).toFixed(1)}s`
      : `${Math.round(stats.avg_latency_ms)}ms`;

  const provider = health.models?.provider || "—";
  $("#provider-pill").textContent = `LLM: ${provider}`;

  barList($("#dept-bars"), stats.by_department, DEPT_COLORS);

  const recent = stats.recent || [];
  const list = $("#recent-list");
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

function escapeHtml(str) {
  return String(str)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;");
}

function addBubble(role, text, isError = false) {
  const el = document.createElement("div");
  el.className = `bubble ${role}${isError ? " error" : ""}`;
  el.textContent = text;
  $("#chat-messages").appendChild(el);
  el.scrollIntoView({ behavior: "smooth", block: "end" });
}

function enterChatActive() {
  const view = $("#view-chat");
  if (!view) return;
  view.classList.remove("chat-home");
  view.classList.add("chat-active");
}

function clearChatUi() {
  const msgs = $("#chat-messages");
  if (msgs) msgs.innerHTML = "";
  const view = $("#view-chat");
  if (view) {
    view.classList.add("chat-home");
    view.classList.remove("chat-active");
  }
  const meta = $("#chat-meta");
  if (meta) meta.hidden = true;
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
  await loadStats();
  if ($("#view-insights")?.classList.contains("active")) {
    await loadInsights();
  }
}

function showMeta(data) {
  const meta = $("#chat-meta");
  if (meta) meta.hidden = false;
  $("#meta-dept").textContent = data.department || "—";
  $("#meta-sev").textContent = data.severity || "—";
  $("#meta-model").textContent = data.model_used || "—";
  $("#meta-cached").textContent = String(Boolean(data.cached));
  $("#meta-sim").textContent =
    data.cache_similarity != null ? Number(data.cache_similarity).toFixed(3) : "—";
  $("#meta-esc").textContent = data.escalated
    ? `yes${data.escalation_reason ? ` — ${data.escalation_reason}` : ""}`
    : "no";
  $("#meta-ticket").textContent = data.ticket_id || "—";
  $("#meta-sources").textContent = (data.sources || []).join(", ") || "—";
}

async function ask(question) {
  const q = question.trim();
  if (!q) return;
  enterChatActive();
  addBubble("user", q);
  $("#chat-input").value = "";
  $("#chat-send").disabled = true;
  addBubble("bot", "Thinking… (local models can take ~30–60s)");
  const thinking = $("#chat-messages").lastElementChild;

  try {
    const res = await api("/query", {
      method: "POST",
      body: JSON.stringify({ question: q }),
    });
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const data = await res.json();
    thinking.remove();
    addBubble("bot", data.answer || "(empty answer)");
    showMeta(data);
    loadStats();
  } catch (err) {
    thinking.remove();
    addBubble("bot", `Error: ${err.message}`, true);
  } finally {
    $("#chat-send").disabled = false;
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

$("#chat-attach")?.addEventListener("click", () => {
  alert("Attachments are not enabled in this MVP.");
});
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

let _unknownTickets = [];
let _unknownPage = 1;
let _escalationTickets = [];
let _escalationPage = 1;

async function loadTickets() {
  const tickets = await api("/tickets?status=open&ticket_type=unknown").then((r) => r.json());
  _unknownTickets = ticketItems(tickets);
  _unknownPage = 1;
  renderUnknownTickets();
}

function renderUnknownTickets() {
  const root = $("#tickets-list");
  const pager = $("#tickets-pagination");
  if (!_unknownTickets.length) {
    root.innerHTML = `<div class="empty">No open unknown tickets.</div>`;
    renderPagination(pager, { page: 1, totalPages: 1, total: 0, start: 0, end: 0 }, () => {});
    return;
  }
  const pageData = pageSlice(_unknownTickets, _unknownPage);
  _unknownPage = pageData.page;
  root.innerHTML = pageData.items
    .map(
      (t) => `<article class="ticket-card" data-id="${t.id}">
      <div>
        <h4>${escapeHtml(t.question)}</h4>
        <p>ID: ${t.id}<br/>Reason: ${escapeHtml(t.reason)} · ${escapeHtml(t.created_at)}</p>
      </div>
      <div class="ticket-actions">
        <select class="dept-select">
          <option value="hr">hr</option>
          <option value="it">it</option>
          <option value="compliance">compliance</option>
          <option value="legal">legal</option>
        </select>
        <textarea class="answer-input" rows="3" placeholder="Canonical answer to store in KB"></textarea>
        <button class="promote-btn">Assign + promote to KB</button>
      </div>
    </article>`
    )
    .join("");

  renderPagination(pager, pageData, (p) => {
    _unknownPage = p;
    renderUnknownTickets();
  });

  root.querySelectorAll(".promote-btn").forEach((btn) => {
    btn.addEventListener("click", async () => {
      const card = btn.closest(".ticket-card");
      const id = card.dataset.id;
      const department = card.querySelector(".dept-select").value;
      const answer = card.querySelector(".answer-input").value.trim();
      if (!answer) {
        alert("Enter an answer to store in the KB.");
        return;
      }
      btn.disabled = true;
      btn.textContent = "Saving…";
      try {
        const res = await api(`/tickets/${id}/promote`, {
          method: "POST",
          body: JSON.stringify({ department, answer }),
        });
        if (!res.ok) {
          const err = await res.json().catch(() => ({}));
          throw new Error(formatApiError(err, `HTTP ${res.status}`));
        }
        loadTickets();
        loadStats();
      } catch (e) {
        alert(e.message);
        btn.disabled = false;
        btn.textContent = "Assign + promote to KB";
      }
    });
  });
}

async function loadEscalations() {
  const tickets = await api("/tickets?status=open&ticket_type=escalation").then((r) =>
    r.json()
  );
  _escalationTickets = ticketItems(tickets);
  _escalationPage = 1;
  renderEscalations();
}

function renderEscalations() {
  const root = $("#escalations-list");
  const pager = $("#escalations-pagination");
  if (!_escalationTickets.length) {
    root.innerHTML = `<div class="empty">No open escalations. High-severity legal/HR chats will appear here.</div>`;
    renderPagination(pager, { page: 1, totalPages: 1, total: 0, start: 0, end: 0 }, () => {});
    return;
  }
  const pageData = pageSlice(_escalationTickets, _escalationPage);
  _escalationPage = pageData.page;
  root.innerHTML = pageData.items
    .map(
      (t) => `<article class="ticket-card" data-id="${t.id}">
      <div>
        <h4>${escapeHtml(t.question)}</h4>
        <p>
          <span class="tag escalation">escalation</span>
          <span class="tag">${escapeHtml(t.department || "—")}</span>
          <span class="tag">${escapeHtml(t.severity || "high")}</span>
        </p>
        <p style="margin-top:8px">ID: ${t.id}<br/>${escapeHtml(t.reason)} · ${escapeHtml(t.created_at)}</p>
      </div>
      <div class="ticket-actions">
        <textarea class="notes-input" rows="3" placeholder="Admin notes / resolution summary"></textarea>
        <button class="resolve-btn">Mark reviewed / resolved</button>
        <button class="promote-esc-btn" style="background:#221b3a">Also promote answer to KB</button>
        <textarea class="answer-input" rows="2" placeholder="Optional KB answer if promoting"></textarea>
      </div>
    </article>`
    )
    .join("");

  renderPagination(pager, pageData, (p) => {
    _escalationPage = p;
    renderEscalations();
  });

  root.querySelectorAll(".resolve-btn").forEach((btn) => {
    btn.addEventListener("click", async () => {
      const card = btn.closest(".ticket-card");
      const id = card.dataset.id;
      const notes = card.querySelector(".notes-input").value.trim();
      btn.disabled = true;
      try {
        const res = await api(`/tickets/${id}/resolve`, {
          method: "PATCH",
          body: JSON.stringify({ status: "resolved", admin_notes: notes || null }),
        });
        if (!res.ok) {
          const err = await res.json().catch(() => ({}));
          throw new Error(formatApiError(err, `HTTP ${res.status}`));
        }
        loadEscalations();
        loadStats();
      } catch (e) {
        alert(e.message);
        btn.disabled = false;
      }
    });
  });

  root.querySelectorAll(".promote-esc-btn").forEach((btn) => {
    btn.addEventListener("click", async () => {
      const card = btn.closest(".ticket-card");
      const id = card.dataset.id;
      const answer = card.querySelector(".answer-input").value.trim();
      const notes = card.querySelector(".notes-input").value.trim();
      if (!answer) {
        alert("Enter a KB answer to promote.");
        return;
      }
      btn.disabled = true;
      try {
        const res = await api(`/tickets/${id}/promote`, {
          method: "POST",
          body: JSON.stringify({ answer, admin_notes: notes || null }),
        });
        if (!res.ok) {
          const err = await res.json().catch(() => ({}));
          throw new Error(formatApiError(err, `HTTP ${res.status}`));
        }
        loadEscalations();
        loadStats();
      } catch (e) {
        alert(e.message);
        btn.disabled = false;
      }
    });
  });
}

$("#refresh-stats")?.addEventListener("click", loadStats);
$("#reset-session")?.addEventListener("click", () => resetSession());
$("#refresh-kb")?.addEventListener("click", () => loadKnowledgeBase());
$("#refresh-tickets")?.addEventListener("click", loadTickets);
$("#refresh-escalations")?.addEventListener("click", loadEscalations);
$("#refresh-insights")?.addEventListener("click", loadInsights);

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
    return;
  }
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

$(".brand")?.addEventListener("click", () => switchView("chat"));

(async function boot() {
  const auth = getAuth();
  if (!auth?.access_token) {
    showLogin();
    return;
  }
  try {
    const res = await api("/auth/me");
    if (!res.ok) throw new Error("bad session");
    const user = await res.json();
    setAuth({ access_token: auth.access_token, user });
    await enterApp();
  } catch {
    logout();
  }
})();
