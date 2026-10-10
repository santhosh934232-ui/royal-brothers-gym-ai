/* ============================================
   ROYAL BROTHERS FITNESS GYM - ADMIN PANEL SCRIPT
   Handles both admin-login.html and admin-dashboard.html
   (checks which page is loaded based on which elements exist).
   ============================================ */

document.addEventListener("DOMContentLoaded", () => {
  initAdminPasswordToggle();
  initAdminLoginForm();
  initAdminDashboard();
});

/* Escapes server-provided text before it is placed in an innerHTML template,
   so names/subjects/messages typed by visitors can never run as markup. */
function escapeHtml(value) {
  return String(value ?? "").replace(/[&<>"']/g, (ch) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
  })[ch]);
}

/* ---------- TOAST HELPER (shared) ---------- */
function showAdminToast(message, isError) {
  const toast = document.getElementById("toast");
  if (!toast) return;
  toast.textContent = message;
  toast.classList.toggle("error", !!isError);
  toast.classList.add("show");
  clearTimeout(showAdminToast._timer);
  showAdminToast._timer = setTimeout(
    () => toast.classList.remove("show"),
    4000,
  );
}

/* ============================================
   ADMIN LOGIN PAGE
   ============================================ */
function initAdminPasswordToggle() {
  const toggleBtn = document.getElementById("toggleAdminPassword");
  if (!toggleBtn) return;

  toggleBtn.addEventListener("click", () => {
    const input = document.getElementById(toggleBtn.dataset.target);
    if (!input) return;
    const isHidden = input.type === "password";
    input.type = isHidden ? "text" : "password";
    const icon = toggleBtn.querySelector("i");
    if (icon) {
      icon.classList.toggle("fa-eye", !isHidden);
      icon.classList.toggle("fa-eye-slash", isHidden);
    }
  });
}

function initAdminLoginForm() {
  const form = document.getElementById("adminLoginForm");
  if (!form) return;

  const errorBox = document.getElementById("formError");

  function showError(text) {
    errorBox.textContent = text;
    errorBox.classList.toggle("show", !!text);
  }

  form.addEventListener("submit", async (e) => {
    e.preventDefault();
    showError("");

    const username = document.getElementById("adminUsername").value.trim();
    const password = document.getElementById("adminPassword").value;

    if (!username || !password) {
      showError("Please enter both username and password.");
      return;
    }

    const submitBtn = form.querySelector('button[type="submit"]');
    const originalText = submitBtn.textContent;
    submitBtn.disabled = true;
    submitBtn.textContent = "Logging In...";

    try {
      const res = await fetch("/api/admin/login", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        credentials: "include",
        body: JSON.stringify({ username, password }),
      });
      const data = await res.json();

      if (res.ok && data.success) {
        window.location.href = "admin-dashboard.html";
      } else {
        showError(data.message || "Invalid admin credentials.");
      }
    } catch (err) {
      showError("Could not reach the server. Please try again later.");
    } finally {
      submitBtn.disabled = false;
      submitBtn.textContent = originalText;
    }
  });
}

/* ============================================
   ADMIN DASHBOARD PAGE
   ============================================ */
function initAdminDashboard() {
  const dashboard = document.getElementById("adminDashboard");
  if (!dashboard) return; // not on the dashboard page

  checkAdminSession();
  initTabs();
  initLogout();
  initAddPlanForm();
  initMemberSearch();
  initPlanSearch();
  initDeleteConfirmModal();
  initAiRefresh();
}

async function checkAdminSession() {
  const loadingEl = document.getElementById("adminLoading");
  const loggedOutEl = document.getElementById("adminLoggedOut");
  const dashboardEl = document.getElementById("adminDashboard");

  try {
    const res = await fetch("/api/admin/me", { credentials: "include" });
    const data = await res.json();

    if (!res.ok || !data.success) {
      loadingEl.style.display = "none";
      loggedOutEl.style.display = "block";
      return;
    }

    document.getElementById("adminUsernameLabel").textContent =
      data.admin.username;
    loadingEl.style.display = "none";
    dashboardEl.style.display = "block";

    // ---------- Single source of truth for stats + badges ----------
    refreshDashboardData();

    // ---------- Table data (each independent, unchanged) ----------
    loadMembers();
    loadRequests();
    loadPlans();
    loadMessages();
    loadAiOverview();
  } catch (err) {
    loadingEl.textContent =
      "Could not reach the server. Please try again later.";
  }
}

function initTabs() {
  const tabButtons = document.querySelectorAll(".admin-tab-btn[data-tab]");
  const panels = document.querySelectorAll(".admin-tab-panel");

  tabButtons.forEach((btn) => {
    btn.addEventListener("click", () => {
      tabButtons.forEach((b) => b.classList.remove("active"));
      panels.forEach((p) => p.classList.remove("active"));
      btn.classList.add("active");
      document.getElementById(`tab-${btn.dataset.tab}`).classList.add("active");
    });
  });
}

function initLogout() {
  const logoutBtn = document.getElementById("adminLogoutBtn");
  if (!logoutBtn) return;

  logoutBtn.addEventListener("click", async () => {
    try {
      await fetch("/api/admin/logout", {
        method: "POST",
        credentials: "include",
      });
    } finally {
      window.location.href = "admin-login.html";
    }
  });
}

/* ============================================
   DASHBOARD STATS + NOTIFICATION BADGES
   One function, one API call, updates both the Overview
   cards and the sidebar badges together — avoids firing
   two separate requests for the same data.
   ============================================ */
async function refreshDashboardData() {
  const grid = document.getElementById("statsGrid");

  try {
    const res = await fetch("/api/admin/dashboard/stats", {
      credentials: "include",
    });
    const data = await res.json();

    if (!res.ok || !data.success) {
      if (grid)
        grid.innerHTML = '<p class="profile-status">Could not load stats.</p>';
      return;
    }

    renderOverviewCards(data.stats);
    updateSidebarBadges(data.stats);
  } catch (err) {
    if (grid)
      grid.innerHTML =
        '<p class="profile-status">Could not reach the server.</p>';
  }
}

function renderOverviewCards(stats) {
  const grid = document.getElementById("statsGrid");
  if (!grid) return;

  grid.innerHTML = `
    <div class="admin-stat-card"><h3>${stats.total_users}</h3><p>TOTAL MEMBERS</p></div>
    <div class="admin-stat-card"><h3>${stats.pending_requests}</h3><p>PENDING MEMBERSHIP REQUESTS</p></div>
    <div class="admin-stat-card"><h3>${stats.unread_messages}</h3><p>UNREAD MESSAGES</p></div>
  `;
}

function updateSidebarBadges(stats) {
  setBadge(document.getElementById("badgeRequests"), stats.pending_requests);
  setBadge(document.getElementById("badgeMessages"), stats.unread_messages);
}

function setBadge(el, count) {
  if (!el) return;
  if (!count || count <= 0) {
    el.style.display = "none";
    el.textContent = "0";
  } else {
    el.style.display = "inline-flex";
    el.textContent = count > 99 ? "99+" : count;
  }
}

/* ---------- MEMBERS ---------- */
let allMembers = [];

async function loadMembers() {
  const tbody = document.querySelector("#membersTable tbody");
  try {
    const res = await fetch("/api/admin/members", { credentials: "include" });
    const data = await res.json();
    if (!res.ok || !data.success) {
      tbody.innerHTML = '<tr><td colspan="4">Could not load members.</td></tr>';
      return;
    }
    allMembers = data.members;
    renderMembersTable(allMembers);
  } catch (err) {
    tbody.innerHTML =
      '<tr><td colspan="4">Could not reach the server.</td></tr>';
  }
}

function renderMembersTable(members) {
  const tbody = document.querySelector("#membersTable tbody");
  if (!members.length) {
    tbody.innerHTML = '<tr><td colspan="4">No members found.</td></tr>';
    return;
  }
  tbody.innerHTML = members
    .map(
      (m) => `
      <tr>
        <td>${escapeHtml(m.full_name)}</td>
        <td>${escapeHtml(m.email)}</td>
        <td>${escapeHtml(m.gender)}</td>
        <td>${new Date(m.created_at).toLocaleDateString("en-IN")}</td>
      </tr>`,
    )
    .join("");
}

function initMemberSearch() {
  const input = document.getElementById("memberSearchInput");
  if (!input) return;

  input.value = "";
  renderMembersTable(allMembers);

  input.addEventListener("input", () => {
    const term = input.value.trim().toLowerCase();
    if (!term) {
      renderMembersTable(allMembers);
      return;
    }
    const filtered = allMembers.filter((m) => {
      return (
        (m.full_name || "").toLowerCase().includes(term) ||
        (m.email || "").toLowerCase().includes(term) ||
        (m.current_plan || "").toLowerCase().includes(term)
      );
    });
    renderMembersTable(filtered);
  });
}

/* ---------- MEMBERSHIP REQUESTS ---------- */
async function loadRequests() {
  const tbody = document.querySelector("#requestsTable tbody");
  try {
    const res = await fetch("/api/admin/membership-requests", {
      credentials: "include",
    });
    const data = await res.json();
    if (!res.ok || !data.success) {
      tbody.innerHTML =
        '<tr><td colspan="6">Could not load requests.</td></tr>';
      return;
    }
    if (!data.requests.length) {
      tbody.innerHTML =
        '<tr><td colspan="6">No membership requests yet.</td></tr>';
      return;
    }
    tbody.innerHTML = data.requests
      .map((r) => {
        const statusActions =
          r.status === "pending"
            ? `<button class="admin-action-btn approve" onclick="updateRequestStatus(${r.id}, 'active')">Approve</button>
               <button class="admin-action-btn reject" onclick="updateRequestStatus(${r.id}, 'rejected')">Reject</button>`
            : "";
        return `
        <tr>
          <td>${escapeHtml(r.full_name)}<br><span style="color:var(--color-text-muted); font-size:0.8rem;">${escapeHtml(r.email)}</span></td>
          <td>${escapeHtml(r.plan_name)}</td>
          <td>₹${escapeHtml(r.price)}</td>
          <td>${new Date(r.request_date).toLocaleDateString("en-IN")}</td>
          <td><span class="status-badge ${escapeHtml(r.status)}">${escapeHtml(r.status)}</span></td>
          <td>${statusActions}
              <button class="admin-action-btn delete" onclick="deleteMembershipRequest(${r.id})">Delete</button></td>
        </tr>`;
      })
      .join("");
  } catch (err) {
    tbody.innerHTML =
      '<tr><td colspan="6">Could not reach the server.</td></tr>';
  }
}

function deleteMembershipRequest(requestId) {
  openDeleteConfirmModal("membership", requestId);
}

async function updateRequestStatus(requestId, status) {
  try {
    const res = await fetch(
      `/api/admin/membership-requests/${requestId}/status`,
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        credentials: "include",
        body: JSON.stringify({ status }),
      },
    );
    const data = await res.json();
    if (res.ok && data.success) {
      showAdminToast(
        `Request ${status === "active" ? "approved" : "rejected"}.`,
        false,
      );
      loadRequests();
      refreshDashboardData();
    } else {
      showAdminToast(data.message || "Could not update request.", true);
    }
  } catch (err) {
    showAdminToast("Could not reach the server.", true);
  }
}

/* ---------- MEMBERSHIP PLANS ---------- */
let allPlans = [];

async function loadPlans() {
  const tbody = document.querySelector("#plansTable tbody");
  try {
    const res = await fetch("/api/admin/plans", { credentials: "include" });
    const data = await res.json();
    if (!res.ok || !data.success) {
      tbody.innerHTML = '<tr><td colspan="5">Could not load plans.</td></tr>';
      return;
    }
    allPlans = data.plans;
    renderPlansTable(allPlans);
  } catch (err) {
    tbody.innerHTML =
      '<tr><td colspan="5">Could not reach the server.</td></tr>';
  }
}

function renderPlansTable(plans) {
  const tbody = document.querySelector("#plansTable tbody");
  if (!plans.length) {
    tbody.innerHTML = '<tr><td colspan="5">No plans found.</td></tr>';
    return;
  }
  tbody.innerHTML = plans
    .map(
      (p) => `
      <tr>
        <td>${escapeHtml(p.plan_name)}</td>
        <td>${escapeHtml(p.duration_months)} month(s)</td>
        <td>₹${escapeHtml(p.price)}</td>
        <td>${escapeHtml(p.features || "-")}</td>
        <td><button class="admin-action-btn delete" onclick="deletePlan(${p.id})">Delete</button></td>
      </tr>`,
    )
    .join("");
}

function initPlanSearch() {
  const input = document.getElementById("planSearchInput");
  if (!input) return;

  input.addEventListener("input", () => {
    const term = input.value.trim().toLowerCase();
    if (!term) {
      renderPlansTable(allPlans);
      return;
    }
    const filtered = allPlans.filter((p) => {
      return (
        (p.plan_name || "").toLowerCase().includes(term) ||
        String(p.duration_months || "").includes(term) ||
        String(p.price || "").includes(term)
      );
    });
    renderPlansTable(filtered);
  });
}

function initAddPlanForm() {
  const form = document.getElementById("addPlanForm");
  if (!form) return;

  form.addEventListener("submit", async (e) => {
    e.preventDefault();

    const plan_name = document.getElementById("newPlanName").value.trim();
    const duration_months = document.getElementById("newPlanDuration").value;
    const price = document.getElementById("newPlanPrice").value;
    const features = document.getElementById("newPlanFeatures").value.trim();

    if (!plan_name || !duration_months || !price) {
      showAdminToast("Plan name, duration, and price are required.", true);
      return;
    }

    try {
      const res = await fetch("/api/admin/plans", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        credentials: "include",
        body: JSON.stringify({ plan_name, duration_months, price, features }),
      });
      const data = await res.json();

      if (res.ok && data.success) {
        showAdminToast("Plan added.", false);
        form.reset();
        loadPlans();
      } else {
        showAdminToast(data.message || "Could not add plan.", true);
      }
    } catch (err) {
      showAdminToast("Could not reach the server.", true);
    }
  });
}

function deletePlan(planId) {
  openDeleteConfirmModal("plan", planId);
}

/* ---------- CONTACT MESSAGES ---------- */
async function loadMessages() {
  const tbody = document.querySelector("#messagesTable tbody");
  try {
    const res = await fetch("/api/admin/messages", { credentials: "include" });
    const data = await res.json();
    if (!res.ok || !data.success) {
      tbody.innerHTML =
        '<tr><td colspan="5">Could not load messages.</td></tr>';
      return;
    }
    if (!data.messages.length) {
      tbody.innerHTML = '<tr><td colspan="5">No messages yet.</td></tr>';
      return;
    }
    tbody.innerHTML = data.messages
      .map(
        (m) => `
        <tr>
          <td>${escapeHtml(m.name)}</td>
          <td>${escapeHtml(m.phone)}<br><span style="color:var(--color-text-muted); font-size:0.8rem;">${escapeHtml(m.email)}</span></td>
          <td>${escapeHtml(m.subject)}</td>
          <td class="message-cell">${escapeHtml(m.message)}</td>
          <td>
            <span class="status-badge ${m.is_read ? "read" : "unread"}">${m.is_read ? "Read" : "Unread"}</span>
            ${!m.is_read ? `<br><button class="admin-action-btn approve" style="margin-top:6px;" onclick="markMessageRead(${m.id})">Mark Read</button>` : ""}
          </td>
        </tr>`,
      )
      .join("");
  } catch (err) {
    tbody.innerHTML =
      '<tr><td colspan="5">Could not reach the server.</td></tr>';
  }
}

async function markMessageRead(messageId) {
  try {
    const res = await fetch(`/api/admin/messages/${messageId}/read`, {
      method: "POST",
      credentials: "include",
    });
    const data = await res.json();
    if (res.ok && data.success) {
      loadMessages();
      refreshDashboardData();
    } else {
      showAdminToast(data.message || "Could not update message.", true);
    }
  } catch (err) {
    showAdminToast("Could not reach the server.", true);
  }
}

/* ============================================
   SECURE DELETE CONFIRMATION MODAL
   Reused for Membership Plans, Membership Requests, and any future
   delete action. The password is NEVER validated here in JS -- this
   modal only enables/disables the Confirm button based on whether the
   field is non-empty. Actual verification happens server-side in
   admin_routes.py, against the logged-in admin's stored password hash.
   ============================================ */
let pendingDelete = null; // { type: 'plan' | 'membership', id }

function initDeleteConfirmModal() {
  const modal = document.getElementById("deleteConfirmModal");
  if (!modal) return;

  const overlay = modal.querySelector(".modal-overlay");
  const passwordInput = document.getElementById("deleteConfirmPassword");
  const toggleBtn = document.getElementById("toggleDeleteConfirmPassword");
  const cancelBtn = document.getElementById("deleteConfirmCancelBtn");
  const confirmBtn = document.getElementById("deleteConfirmBtn");

  // Confirm Delete stays disabled until the password field is non-empty.
  passwordInput.addEventListener("input", () => {
    confirmBtn.disabled = passwordInput.value.trim().length === 0;
  });

  // Show/Hide password toggle.
  toggleBtn.addEventListener("click", () => {
    const isHidden = passwordInput.type === "password";
    passwordInput.type = isHidden ? "text" : "password";
    const icon = toggleBtn.querySelector("i");
    if (icon) {
      icon.classList.toggle("fa-eye", !isHidden);
      icon.classList.toggle("fa-eye-slash", isHidden);
    }
  });

  // Close on Cancel, on outside click (the overlay), and on ESC.
  cancelBtn.addEventListener("click", closeDeleteConfirmModal);
  overlay.addEventListener("click", closeDeleteConfirmModal);
  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape" && modal.classList.contains("show")) {
      closeDeleteConfirmModal();
    }
  });

  confirmBtn.addEventListener("click", handleDeleteConfirm);
}

function openDeleteConfirmModal(type, id) {
  pendingDelete = { type, id };

  const modal = document.getElementById("deleteConfirmModal");
  const passwordInput = document.getElementById("deleteConfirmPassword");
  const toggleBtn = document.getElementById("toggleDeleteConfirmPassword");
  const confirmBtn = document.getElementById("deleteConfirmBtn");
  const cancelBtn = document.getElementById("deleteConfirmCancelBtn");
  if (!modal) return;

  // Reset to a clean state every time it's opened.
  passwordInput.value = "";
  passwordInput.type = "password";
  const toggleIcon = toggleBtn.querySelector("i");
  if (toggleIcon) {
    toggleIcon.classList.remove("fa-eye-slash");
    toggleIcon.classList.add("fa-eye");
  }
  confirmBtn.disabled = true;
  confirmBtn.classList.remove("loading");
  confirmBtn.innerHTML = "Confirm Delete";
  cancelBtn.disabled = false;

  modal.style.display = "flex";
  requestAnimationFrame(() => modal.classList.add("show"));
  setTimeout(() => passwordInput.focus(), 60);
}

function closeDeleteConfirmModal() {
  const modal = document.getElementById("deleteConfirmModal");
  const passwordInput = document.getElementById("deleteConfirmPassword");
  if (!modal) return;

  modal.classList.remove("show");
  passwordInput.value = ""; // never leave the password sitting in the DOM
  pendingDelete = null;

  setTimeout(() => {
    modal.style.display = "none";
  }, 250); // matches the CSS transition duration
}

async function handleDeleteConfirm() {
  if (!pendingDelete) return;

  const passwordInput = document.getElementById("deleteConfirmPassword");
  const confirmBtn = document.getElementById("deleteConfirmBtn");
  const cancelBtn = document.getElementById("deleteConfirmCancelBtn");
  const password = passwordInput.value;

  if (!password) return; // button should already be disabled; extra guard

  confirmBtn.disabled = true;
  cancelBtn.disabled = true;
  confirmBtn.classList.add("loading");
  confirmBtn.innerHTML = '<span class="btn-spinner"></span> Deleting...';

  const { type, id } = pendingDelete;
  const endpoint =
    type === "plan"
      ? `/api/admin/plans/${id}`
      : `/api/admin/membership-requests/${id}`;

  try {
    const res = await fetch(endpoint, {
      method: "DELETE",
      headers: { "Content-Type": "application/json" },
      credentials: "include",
      body: JSON.stringify({ password }),
    });
    const data = await res.json();

    // Clear the password field immediately after every response,
    // success or failure -- it's never kept around.
    passwordInput.value = "";

    if (res.ok && data.success) {
      showAdminToast(data.message || "Deleted successfully.", false);
      closeDeleteConfirmModal();

      if (type === "plan") {
        loadPlans();
      } else {
        loadRequests();
        refreshDashboardData();
      }
    } else {
      // Wrong password (401), business-rule block (400), not found (404),
      // or a server error (500) -- all surfaced via the same toast system.
      showAdminToast(
        data.message || "Could not delete. Please try again.",
        true,
      );
      resetDeleteConfirmButtons();
      passwordInput.focus();
    }
  } catch (err) {
    passwordInput.value = "";
    showAdminToast("Could not reach the server.", true);
    resetDeleteConfirmButtons();
  }
}

function resetDeleteConfirmButtons() {
  const confirmBtn = document.getElementById("deleteConfirmBtn");
  const cancelBtn = document.getElementById("deleteConfirmCancelBtn");
  confirmBtn.disabled = true; // password field is empty again, stays disabled
  cancelBtn.disabled = false;
  confirmBtn.classList.remove("loading");
  confirmBtn.innerHTML = "Confirm Delete";
}


/* ============================================
   AI MANAGEMENT (Step 10) - read-only
   Shows AI service status and saved-record counts/timestamps from
   GET /api/admin/ai/overview. All server text goes in via textContent;
   there are no edit/generate controls here.
   ============================================ */
function aiCell(tr, text) {
  const td = document.createElement("td");
  td.textContent = text;
  tr.append(td);
  return td;
}

function aiStatCard(value, label) {
  const card = document.createElement("div");
  card.className = "admin-stat-card";
  const h = document.createElement("h3");
  h.textContent = value;
  const p = document.createElement("p");
  p.textContent = label;
  card.append(h, p);
  return card;
}

function renderAiOverview(data) {
  const grid = document.getElementById("aiStatusGrid");
  const msg = document.getElementById("aiStatusMessage");
  const tbody = document.querySelector("#aiFeaturesTable tbody");

  const total = data.features.reduce((n, f) => n + (f.records || 0), 0);
  grid.replaceChildren(
    aiStatCard(data.service.configured ? "Configured" : "Not configured", "GEMINI AI SERVICE"),
    aiStatCard(data.service.model || "-", "AI MODEL"),
    aiStatCard(total, "SAVED AI RECORDS"),
  );
  msg.textContent = data.service.message;

  tbody.replaceChildren(
    ...data.features.map((f) => {
      const tr = document.createElement("tr");
      aiCell(tr, f.name);
      aiCell(tr, "Step " + f.step);
      aiCell(tr, f.available ? f.records : "Unavailable");
      aiCell(tr, f.lastGenerated || (f.available ? "Never" : "-"));
      return tr;
    }),
  );
}

async function loadAiOverview() {
  const grid = document.getElementById("aiStatusGrid");
  const tbody = document.querySelector("#aiFeaturesTable tbody");
  if (!grid || !tbody) return;
  try {
    const res = await fetch("/api/admin/ai/overview", { credentials: "include" });
    const data = await res.json();
    if (!res.ok || !data.success) {
      grid.textContent = "Could not load AI status.";
      return;
    }
    renderAiOverview(data);
  } catch (err) {
    grid.textContent = "Could not reach the server.";
  }
}

function initAiRefresh() {
  const btn = document.getElementById("aiRefreshBtn");
  if (btn) btn.addEventListener("click", loadAiOverview);
}
