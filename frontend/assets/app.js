/**
 * @file app.js
 * @description MongoFleet — shared UI behaviors (mock/front-end only, no backend calls).
 *              Handles initialization for tabs, modals, toasts, simulated steppers, and mobile sidebar navigation.
 * @author Madan U <madanu135@gmail.com>
 * @date 2026-09-17
 */

// ==========================================================================
// MongoFleet — shared UI behaviors (mock/front-end only, no backend calls)
// ==========================================================================

function initTabs(root = document) {
  root.querySelectorAll('.tabs').forEach(tabBar => {
    const group = tabBar.dataset.group;
    tabBar.querySelectorAll('.tab').forEach(tab => {
      tab.addEventListener('click', () => {
        tabBar.querySelectorAll('.tab').forEach(t => t.classList.remove('active'));
        tab.classList.add('active');
        const panelId = tab.dataset.target;
        document.querySelectorAll(`.tab-panel[data-group="${group}"]`).forEach(p => {
          p.classList.toggle('active', p.id === panelId);
        });
      });
    });
  });
}

function openModal(id) {
  const el = document.getElementById(id);
  if (el) el.classList.add('open');
}
function closeModal(id) {
  const el = document.getElementById(id);
  if (el) el.classList.remove('open');
}
document.addEventListener('click', (e) => {
  if (e.target.classList && e.target.classList.contains('modal-overlay')) {
    e.target.classList.remove('open');
  }
});

function showToast(message, icon = '✓') {
  let wrap = document.querySelector('.toast-wrap');
  if (!wrap) {
    wrap = document.createElement('div');
    wrap.className = 'toast-wrap';
    document.body.appendChild(wrap);
  }
  const t = document.createElement('div');
  t.className = 'toast';
  t.innerHTML = `<span class="ico">${icon}</span><span>${message}</span>`;
  wrap.appendChild(t);
  setTimeout(() => t.remove(), 3600);
}

// Advances a .stepper's steps from "active" to "done" one at a time, purely
// as a visual demo of what real-time operation tracking will look like once
// the backend job engine (SSE/WebSocket) is wired up.
function simulateStepper(stepperEl, intervalMs = 1100, onDone) {
  const steps = Array.from(stepperEl.querySelectorAll('.step'));
  let i = steps.findIndex(s => s.classList.contains('active'));
  if (i === -1) i = 0;
  const tick = () => {
    if (i >= steps.length) { onDone && onDone(); return; }
    steps.forEach(s => s.classList.remove('active'));
    for (let j = 0; j < i; j++) steps[j].classList.add('done');
    if (i < steps.length) steps[i].classList.add('active');
    i++;
    if (i <= steps.length) setTimeout(tick, intervalMs);
  };
  tick();
}

// Allows linking directly to a tab via ?tab=xxx (used by sidebar links that
// point at a specific tab on a shared page, e.g. governance.html?tab=audit)
function activateTabFromQuery() {
  const tab = new URLSearchParams(window.location.search).get('tab');
  if (!tab) return;
  const target = document.querySelector(`.tab[data-key="${tab}"]`);
  if (target) target.click();
}

// Sidebar "Alerts" nav badge — shared by every page that includes both
// api.js and app.js. Shows the count of unresolved (PENDING/FAILED) critical
// alerts; hidden entirely when there are none, so it never reads as "0" noise.
async function loadAlertBadge() {
  const badge = document.getElementById('nav-badge-alerts');
  if (!badge || typeof Api === 'undefined') return;
  try {
    const summary = await Api.alertsSummary();
    if (summary.unresolved_critical > 0) {
      badge.textContent = summary.unresolved_critical;
      badge.style.display = '';
    } else {
      badge.style.display = 'none';
    }
  } catch (_e) {
    badge.style.display = 'none';
  }
}

// Mobile sidebar drawer — wires up #sidebar / #sidebarScrim / #menuBtn if the
// page includes them. No-ops harmlessly on pages that don't (e.g. login).
function initSidebarToggle() {
  const sidebar = document.getElementById('sidebar');
  const scrim = document.getElementById('sidebarScrim');
  const btn = document.getElementById('menuBtn');
  if (!sidebar || !btn) return;
  const open = () => { sidebar.classList.add('open'); scrim && scrim.classList.add('show'); };
  const close = () => { sidebar.classList.remove('open'); scrim && scrim.classList.remove('show'); };
  btn.addEventListener('click', () => sidebar.classList.contains('open') ? close() : open());
  scrim && scrim.addEventListener('click', close);
  sidebar.querySelectorAll('.nav-item').forEach(a => a.addEventListener('click', close));
}


function _topbarToIST(iso) {
  if (!iso) return "—";
  return new Date(iso).toLocaleString("en-IN", {
    timeZone: "Asia/Kolkata", day: "2-digit", month: "short",
    hour: "2-digit", minute: "2-digit", hour12: true,
  }).replace(",", "") + " IST";
}
function _alertSeverityDot(sev) {
  const s = (sev || "").toUpperCase();
  if (s === "CRITICAL") return "sev-CRITICAL";
  if (s === "WARN" || s === "WARNING") return "sev-WARN";
  return "sev-OK";
}
async function loadAlertDropdown() {
  const list = document.getElementById("alert-dropdown-list");
  if (!list) return;
  list.innerHTML = `<p class="cell-sub" style="padding:14px;">Loading&hellip;</p>`;
  try {
    const data = await Api.listAlerts({ page_size: 5 });
    const alerts = (data.alerts || data.items || []).slice(0, 5);
    if (!alerts.length) { list.innerHTML = `<p class="cell-sub" style="padding:14px;">No alerts to show.</p>`; return; }
    list.innerHTML = alerts.map(a => `
      <div class="alert-dropdown-item">
        <div class="dot-mark ${_alertSeverityDot(a.severity)}"></div>
        <div style="flex:1;min-width:0;">
          <p class="alert-title">${a.title || a.message || a.alert_type || "Alert"}</p>
          <p class="alert-desc">${a.hostname || a.server_name || ""}${a.hostname || a.server_name ? " &middot; " : ""}${_topbarToIST(a.created_at || a.ts)}</p>
        </div>
      </div>`).join("");
  } catch (err) {
    list.innerHTML = `<p class="cell-sub" style="padding:14px;color:var(--red);">Failed to load: ${err.message}</p>`;
  }
}
function initAlertDropdown() {
  const bellBtn = document.getElementById("btn-alert-bell");
  const dropdown = document.getElementById("alert-dropdown");
  if (!bellBtn || !dropdown) return;
  bellBtn.addEventListener("click", (e) => {
    e.stopPropagation();
    const isOpen = dropdown.classList.contains("open");
    dropdown.classList.toggle("open", !isOpen);
    if (!isOpen) loadAlertDropdown();
  });
  document.addEventListener("click", (e) => {
    if (!dropdown.contains(e.target) && e.target !== bellBtn) dropdown.classList.remove("open");
  });
}

function initUserMenu() {
  const btn = document.getElementById("btn-user-menu");
  const dropdown = document.getElementById("user-dropdown");
  const logoutBtn = document.getElementById("btn-logout");
  if (!btn || !dropdown) return;
  btn.addEventListener("click", (e) => { e.stopPropagation(); dropdown.classList.toggle("open"); });
  document.addEventListener("click", (e) => {
    if (!dropdown.contains(e.target) && e.target !== btn) dropdown.classList.remove("open");
  });
  if (logoutBtn) {
    logoutBtn.addEventListener("click", async () => {
      logoutBtn.disabled = true;
      try { await Api.logout(); } catch (_e) {}
      finally { location.href = "login.html"; }
    });
  }
}

function initSupportModal() {
  const supportBtn = document.getElementById("btn-support");
  const submitBtn = document.getElementById("btn-submit-support");
  if (!supportBtn || !submitBtn) return;
  supportBtn.addEventListener("click", async () => {
    document.getElementById("s-error").style.display = "none";
    document.getElementById("s-issue").value = "";
    try {
      const me = await Api.me();
      document.getElementById("s-username").value = me.username || me.full_name || "";
      document.getElementById("s-email").value = me.email || "";
    } catch (_e) {}
    openModal("m-support");
  });
  submitBtn.addEventListener("click", async () => {
    const errorEl = document.getElementById("s-error");
    errorEl.style.display = "none";
    const username = document.getElementById("s-username").value.trim();
    const email = document.getElementById("s-email").value.trim();
    const issue = document.getElementById("s-issue").value.trim();
    if (!username || !email || !issue) { errorEl.textContent = "Please fill in your name, email, and the issue."; errorEl.style.display = ""; return; }
    if (!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email)) { errorEl.textContent = "Enter a valid email address."; errorEl.style.display = ""; return; }
    submitBtn.disabled = true;
    try {
      await Api.submitSupportRequest({ username, email, issue, page: document.title });
      showToast("Sent to the DBA team");
      closeModal("m-support");
    } catch (err) {
      errorEl.textContent = err.message || "Could not send. Please try again.";
      errorEl.style.display = "";
    } finally { submitBtn.disabled = false; }
  });
}

// ---------------------------------------------------------------------------
// Custom-styled dropdowns — every <select> on every page becomes a modern
// floating-panel menu (matches the Operations timeframe picker). The real
// <select> stays in the DOM as the single source of truth for its value,
// options and "change" event, just visually hidden — so nothing else in any
// page needs to change: code that reads a select's .value or listens for its
// "change" event keeps working exactly as before.
// ---------------------------------------------------------------------------
function enhanceSelect(select) {
  if (!select || select.dataset.tsEnhanced || select.multiple) return;
  select.dataset.tsEnhanced = "1";

  const inFieldWrap = !!select.closest(".field, .field-group");
  const inlineWidth = select.style.width;
  const inlineMinWidth = select.style.minWidth;

  const wrap = document.createElement("div");
  wrap.className = "ts-select";
  if (inFieldWrap) wrap.classList.add("ts-select-block");
  select.parentNode.insertBefore(wrap, select);
  wrap.appendChild(select);
  select.classList.add("ts-native-select");
  select.tabIndex = -1;
  select.setAttribute("aria-hidden", "true");

  const trigger = document.createElement("button");
  trigger.type = "button";
  trigger.className = "ts-trigger";
  trigger.disabled = select.disabled;
  trigger.setAttribute("aria-haspopup", "listbox");
  trigger.setAttribute("aria-expanded", "false");
  if (inlineWidth) trigger.style.width = inlineWidth;
  if (inlineMinWidth) trigger.style.minWidth = inlineMinWidth;
  trigger.innerHTML = `<span class="ts-trigger-label"></span>
    <svg class="ts-chevron" width="12" height="8" viewBox="0 0 12 8" fill="none" aria-hidden="true"><path d="M1 1.5L6 6.5L11 1.5" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"/></svg>`;
  wrap.appendChild(trigger);

  const panel = document.createElement("div");
  panel.className = "ts-panel";
  panel.setAttribute("role", "listbox");
  wrap.appendChild(panel);

  let optionEls = [];
  let focusedIdx = -1;

  function buildOption(node) {
    const item = document.createElement("div");
    item.className = "ts-option";
    item.setAttribute("role", "option");
    item.dataset.value = node.value;
    if (node.disabled) item.classList.add("disabled");
    item.innerHTML = `<span class="ts-check"><svg width="12" height="10" viewBox="0 0 12 10" fill="none" aria-hidden="true"><path d="M1 5L4.2 8.2L11 1" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"/></svg></span><span class="ts-option-label">${node.textContent}</span>`;
    if (!node.disabled) {
      item.addEventListener("click", () => selectOption(node.value));
      item.addEventListener("mouseenter", () => setFocused(optionEls.length));
    }
    panel.appendChild(item);
    optionEls.push({ el: item, value: node.value });
  }

  function rebuild() {
    panel.innerHTML = "";
    optionEls = [];
    Array.from(select.children).forEach((node) => {
      if (node.tagName === "OPTGROUP") {
        const label = document.createElement("div");
        label.className = "ts-group-label";
        label.textContent = node.label;
        panel.appendChild(label);
        Array.from(node.children).forEach(buildOption);
      } else if (node.tagName === "OPTION") {
        buildOption(node);
      }
    });
    syncTrigger();
  }

  function syncTrigger() {
    const opt = select.options[select.selectedIndex];
    trigger.querySelector(".ts-trigger-label").textContent = opt ? opt.textContent : "";
    optionEls.forEach((o) => o.el.classList.toggle("selected", o.value === select.value));
  }

  function setFocused(idx) {
    if (focusedIdx >= 0 && optionEls[focusedIdx]) optionEls[focusedIdx].el.classList.remove("focused");
    focusedIdx = idx;
    if (optionEls[focusedIdx]) optionEls[focusedIdx].el.classList.add("focused");
  }

  function selectOption(value) {
    if (select.value !== value) {
      select.value = value;
      select.dispatchEvent(new Event("change", { bubbles: true }));
    }
    syncTrigger();
    closePanel();
    trigger.focus();
  }

  function openPanel() {
    if (trigger.disabled) return;
    rebuild(); // pick up options a page added/changed dynamically (async server lists, etc.)
    wrap.classList.add("open");
    trigger.setAttribute("aria-expanded", "true");
    const selIdx = optionEls.findIndex((o) => o.value === select.value);
    setFocused(selIdx >= 0 ? selIdx : 0);
    const activeEl = optionEls[focusedIdx] && optionEls[focusedIdx].el;
    if (activeEl) activeEl.scrollIntoView({ block: "nearest" });
  }
  function closePanel() {
    wrap.classList.remove("open");
    trigger.setAttribute("aria-expanded", "false");
  }
  function togglePanel() {
    if (wrap.classList.contains("open")) closePanel();
    else openPanel();
  }

  trigger.addEventListener("click", (e) => {
    e.stopPropagation();
    togglePanel();
  });
  document.addEventListener("click", (e) => {
    if (!wrap.contains(e.target)) closePanel();
  });
  wrap.addEventListener("keydown", (e) => {
    if (e.key === "Escape") {
      closePanel();
      trigger.focus();
    } else if (e.key === "ArrowDown" || e.key === "ArrowUp") {
      e.preventDefault();
      if (!wrap.classList.contains("open")) { openPanel(); return; }
      const dir = e.key === "ArrowDown" ? 1 : -1;
      const next = Math.min(optionEls.length - 1, Math.max(0, focusedIdx + dir));
      setFocused(next);
      optionEls[next].el.scrollIntoView({ block: "nearest" });
    } else if (e.key === "Enter" || e.key === " ") {
      if (wrap.classList.contains("open")) {
        e.preventDefault();
        const cur = optionEls[focusedIdx];
        if (cur && !cur.el.classList.contains("disabled")) selectOption(cur.value);
      }
    }
  });

  // Stay in sync if a page sets select.value / rebuilds its options in code.
  select.addEventListener("change", syncTrigger);
  new MutationObserver(() => {
    trigger.disabled = select.disabled;
    trigger.classList.toggle("is-disabled", select.disabled);
    if (!wrap.classList.contains("open")) syncTrigger();
  }).observe(select, { childList: true, subtree: true, attributes: true, attributeFilter: ["disabled"] });

  rebuild();
}

function enhanceAllSelects(root) {
  (root || document).querySelectorAll("select:not(.ts-native-select)").forEach(enhanceSelect);
}

function initCustomSelects() {
  enhanceAllSelects();
  // Filter rows, edit/add modals, and server pickers on several pages populate
  // their <select> (or add a brand-new one) after an async fetch — catch those
  // too, without every page needing to call this itself.
  new MutationObserver((mutations) => {
    mutations.forEach((m) => {
      m.addedNodes.forEach((n) => {
        if (n.nodeType !== 1) return;
        if (n.classList && (n.classList.contains("ts-select") || n.classList.contains("ts-panel") || n.classList.contains("ts-trigger") || n.classList.contains("ts-option") || n.classList.contains("ts-group-label"))) return;
        if (n.tagName === "SELECT") enhanceSelect(n);
        else if (n.querySelectorAll) enhanceAllSelects(n);
      });
    });
  }).observe(document.body, { childList: true, subtree: true });
}

document.addEventListener('DOMContentLoaded', () => {
  initTabs();
  activateTabFromQuery();
  loadAlertBadge();
  initSidebarToggle();
  initAlertDropdown();
  initUserMenu();
  initSupportModal();
  initCustomSelects();
});


