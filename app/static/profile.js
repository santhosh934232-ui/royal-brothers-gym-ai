/* ============================================
   ROYAL BROTHERS FITNESS GYM - PROFILE PAGE
   Loads profile info + membership status, editable profile fields,
   expiry warning, and logout.

   Profile photo upload has been removed. Every user's avatar is the
   fixed official gym image (app/static/royalbrothersgym.jpg), set
   directly in profile.html -- there is no per-user image logic here.
   ============================================ */

document.addEventListener("DOMContentLoaded", () => {
  loadProfile();
  loadMembershipCard();
  initMembershipReminderSettings();
  initEditProfile();
  initLogout();
  initFitnessProfile();
  initWorkoutPlan();
  initDailyPlanner();
  initProgressTracker();
  initInsights();
  initRecommendations();
  initNutrition();
});

/* ---------- TOAST HELPER ---------- */
function showToast(message, isError) {
  const toast = document.getElementById("toast");
  if (!toast) return;
  toast.textContent = message;
  toast.classList.toggle("error", !!isError);
  toast.classList.add("show");
  clearTimeout(showToast._timer);
  showToast._timer = setTimeout(() => toast.classList.remove("show"), 4000);
}

/* ---------- SAFE FETCH HELPER ----------
   Distinguishes three outcomes so error messages are always accurate:
     1. Network/server unreachable -> fetch() itself throws (TypeError)
     2. Server reachable but sent a non-JSON body (e.g. a 404/405 HTML
        error page from a missing route) -> res.json() throws
     3. Server reachable and responded with JSON, success or failure
   Returns { ok, status, data, networkError, badResponse }.
------------------------------------------- */
async function safeFetch(url, options) {
  let res;
  try {
    res = await fetch(url, options);
  } catch (err) {
    // fetch() only throws for actual network failures (server down,
    // no internet, CORS block, DNS failure, etc.) -- this is the ONLY
    // case that should ever show "Could not reach the server."
    return {
      ok: false,
      networkError: true,
      badResponse: false,
      status: 0,
      data: null,
    };
  }

  let data = null;
  try {
    data = await res.json();
  } catch (err) {
    // Server responded, but not with JSON (e.g. a missing-route 404/405
    // HTML page). This is a server-side/routing bug, not a network issue.
    return {
      ok: false,
      networkError: false,
      badResponse: true,
      status: res.status,
      data: null,
    };
  }

  return {
    ok: res.ok,
    networkError: false,
    badResponse: false,
    status: res.status,
    data,
  };
}

/* ---------- LOAD PROFILE ----------
   Uses AuthCache (see auth-cache.js) so this shares its /api/auth/me
   call with script.js's navbar check instead of firing a second,
   separate request on the same page load -- and can paint instantly
   from cache while that shared call is still in flight. */
async function loadProfile() {
  const loadingEl = document.getElementById("profileLoading");
  const loggedOutEl = document.getElementById("profileLoggedOut");
  const contentEl = document.getElementById("profileContent");

  // ---------- Instant paint from cache (no network wait) ----------
  const cached = window.AuthCache ? window.AuthCache.getCachedUser() : null;
  if (cached && cached.ok && cached.data && cached.data.success) {
    applyProfileToUI(cached.data.user);
    loadingEl.style.display = "none";
    contentEl.style.display = "block";
  }

  const fetchUser = window.AuthCache
    ? window.AuthCache.fetchUser
    : () =>
        fetch("/api/auth/me", { credentials: "include" })
          .then((res) => res.json().then((data) => ({ ok: res.ok, data })))
          .catch(() => ({ ok: false, data: null, networkError: true }));

  const result = await fetchUser();

  if (result.networkError && !cached) {
    loadingEl.textContent =
      "Could not reach the server. Please try again later.";
    return;
  }

  if (!result.ok || !result.data || !result.data.success) {
    // Not logged in (or the cached state above was stale) -- show the
    // logged-out state, same as before.
    loadingEl.style.display = "none";
    contentEl.style.display = "none";
    loggedOutEl.style.display = "block";
    return;
  }

  const user = result.data.user;
  applyProfileToUI(user);

  loadingEl.style.display = "none";
  contentEl.style.display = "block";
}

/* ---------- APPLY PROFILE DATA TO THE UI ----------
   Single source of truth for painting profile fields, called after
   the initial load AND after a successful save, so the page never
   needs a refresh to reflect the latest data.
------------------------------------------------------ */
function applyProfileToUI(user) {
  document.getElementById("profileName").textContent = user.full_name;
  document.getElementById("profileEmail").textContent = user.email;
  document.getElementById("profileGender").textContent = user.gender;
  document.getElementById("editFullName").value = user.full_name;
  document.getElementById("editGender").value = user.gender;
}

/* ---------- EDIT PROFILE (name + gender) ---------- */
function initEditProfile() {
  const viewMode = document.getElementById("profileViewMode");
  const editForm = document.getElementById("editProfileForm");
  const editBtn = document.getElementById("editProfileBtn");
  const cancelBtn = document.getElementById("cancelEditBtn");
  const errorBox = document.getElementById("editProfileError");

  if (!editForm) return;

  function showError(text) {
    errorBox.textContent = text;
    errorBox.classList.toggle("show", !!text);
  }

  editBtn.addEventListener("click", () => {
    viewMode.style.display = "none";
    editForm.style.display = "block";
    showError("");
  });

  cancelBtn.addEventListener("click", () => {
    editForm.style.display = "none";
    viewMode.style.display = "block";
    showError("");
  });

  editForm.addEventListener("submit", async (e) => {
    e.preventDefault();
    showError("");

    const fullName = document.getElementById("editFullName").value.trim();
    const gender = document.getElementById("editGender").value;

    // ---------- Client-side validation ----------
    if (!fullName) {
      showError("Name cannot be empty.");
      return;
    }

    if (fullName.length > 100) {
      showError("Name must be 100 characters or fewer.");
      return;
    }

    if (!["male", "female", "other"].includes(gender)) {
      showError("Please select a valid gender.");
      return;
    }

    const saveBtn = document.getElementById("saveProfileBtn");
    const originalText = saveBtn.textContent;
    saveBtn.disabled = true;
    saveBtn.textContent = "Saving...";

    const result = await safeFetch("/api/auth/profile", {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      credentials: "include",
      body: JSON.stringify({ fullName, gender }),
    });

    saveBtn.disabled = false;
    saveBtn.textContent = originalText;

    if (result.networkError) {
      showError("Could not reach the server. Please try again later.");
      return;
    }

    if (result.badResponse) {
      // Server responded but not with JSON -- a real server-side
      // problem, not a network issue. Report it accurately instead of
      // calling it a network error.
      showError(
        `Server error (status ${result.status}). Please try again, or contact support if this continues.`,
      );
      return;
    }

    if (result.ok && result.data && result.data.success) {
      // Update the UI immediately from the server's confirmed data --
      // no page refresh needed.
      applyProfileToUI(result.data.user);
      if (window.AuthCache) window.AuthCache.setCachedUser(result.data.user);
      editForm.style.display = "none";
      viewMode.style.display = "block";
      showToast(result.data.message || "Profile updated successfully.", false);
      return;
    }

    // Server responded with valid JSON but reported a failure
    // (validation error, not logged in, etc.) -- show its message.
    showError(
      (result.data && result.data.message) || "Could not update profile.",
    );

    if (result.status === 401) {
      // Session expired/not logged in -- send them to log back in.
      showToast("Your session has expired. Please log in again.", true);
      setTimeout(() => {
        window.location.href = "login.html";
      }, 1500);
    }
  });
}

/* ---------- MEMBERSHIP CARD + EXPIRY WARNING ---------- */
function membershipDateText(value) {
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) return "Not available";
  return parsed.toLocaleDateString("en-IN", {
    day: "2-digit",
    month: "short",
    year: "numeric",
  });
}

function appendMembershipRow(card, label, value) {
  const row = document.createElement("div");
  row.className = "membership-card-row";
  const labelEl = document.createElement("span");
  const valueEl = document.createElement("span");
  labelEl.textContent = label;
  valueEl.textContent = value;
  row.append(labelEl, valueEl);
  card.append(row);
}

async function loadMembershipCard() {
  const wrap = document.getElementById("membershipCardWrap");
  const warningBox = document.getElementById("expiryWarning");
  const warningText = document.getElementById("expiryWarningText");

  const result = await safeFetch("/api/membership/my-request", {
    credentials: "include",
  });

  if (result.networkError) {
    wrap.innerHTML =
      '<p class="profile-status">Could not reach the server.</p>';
    return;
  }

  if (
    result.badResponse ||
    !result.ok ||
    !result.data ||
    !result.data.success
  ) {
    wrap.innerHTML =
      '<p class="profile-status">Could not load membership info.</p>';
    return;
  }

  const req = result.data.request;

  if (!req) {
    wrap.innerHTML = `
      <div class="membership-card-empty">
        You don't have a membership yet.<br />
        <a href="membership.html">View plans and get started</a>
      </div>`;
    return;
  }

  const card = document.createElement("div");
  card.className = "membership-card";
  const header = document.createElement("div");
  header.className = "membership-card-header";
  const title = document.createElement("h3");
  title.textContent = "Royal Brothers Fitness Gym";
  const status = document.createElement("span");
  const knownStatuses = ["pending", "active", "rejected"];
  const safeStatus = knownStatuses.includes(req.status) ? req.status : "unknown";
  status.className = `status-badge ${safeStatus}`;
  status.textContent = typeof req.status === "string" ? req.status : "Unknown";
  header.append(title, status);
  card.append(header);
  appendMembershipRow(card, "Plan", typeof req.plan_name === "string" ? req.plan_name : "Not available");
  appendMembershipRow(card, "Request Date", membershipDateText(req.request_date));
  if (req.start_date) appendMembershipRow(card, "Start Date", membershipDateText(req.start_date));
  if (req.end_date) appendMembershipRow(card, "Expiry Date", membershipDateText(req.end_date));
  wrap.replaceChildren(card);

  // ---------- Expiry warning (Bug 7) ----------
  if (req.status === "active" && req.end_date) {
    const today = new Date();
    const expiry = new Date(req.end_date);
    const daysLeft = Math.ceil((expiry - today) / (1000 * 60 * 60 * 24));

    if (daysLeft <= 7 && daysLeft >= 0) {
      warningText.textContent = `Your membership expires in ${daysLeft} day${daysLeft === 1 ? "" : "s"}.`;
      warningBox.style.display = "flex";
    } else if (daysLeft < 0) {
      warningText.textContent =
        "Your membership has expired. Please renew at Royal Brothers Fitness Gym.";
      warningBox.style.display = "flex";
    }
  }
}

/* ---------- LOGOUT ----------
   Handles both the navbar logout button (#logoutBtn, unchanged
   behavior) and the new profile-page bottom logout button
   (#logoutBtnProfile), which asks for confirmation first. Both share
   the same performLogout() call to the existing logout API so there
   is only one place that talks to the server / clears the cache. */
function initLogout() {
  const logoutBtn = document.getElementById("logoutBtn");
  const logoutBtnProfile = document.getElementById("logoutBtnProfile");

  async function performLogout() {
    try {
      await fetch("/api/auth/logout", {
        method: "POST",
        credentials: "include",
      });
    } finally {
      if (window.AuthCache) window.AuthCache.clearCache();
      window.location.href = "login.html";
    }
  }

  if (logoutBtn) {
    logoutBtn.addEventListener("click", performLogout);
  }

  if (logoutBtnProfile) {
    logoutBtnProfile.addEventListener("click", () => {
      const confirmed = window.confirm("Are you sure you want to logout?");
      if (confirmed) {
        performLogout();
      }
    });
  }
}


/* ---------- FITNESS PROFILE (Step 2) ----------
   Reads/writes only the logged-in member's own profile via
   /api/fitness-profile. Nothing is sent to any AI service. */
const FITNESS_LABELS = {
  weight_loss: "Weight Loss",
  muscle_gain: "Muscle Gain",
  strength: "Strength",
  endurance: "Endurance",
  general_fitness: "General Fitness",
  beginner: "Beginner",
  intermediate: "Intermediate",
  advanced: "Advanced",
};

function initFitnessProfile() {
  const form = document.getElementById("fitnessForm");
  if (!form) return;
  const view = document.getElementById("fitnessView");
  const summary = document.getElementById("fitnessSummary");
  const emptyMsg = document.getElementById("fitnessEmpty");
  const editBtn = document.getElementById("editFitnessBtn");
  const editBtnText = document.getElementById("editFitnessBtnText");
  const cancelBtn = document.getElementById("cancelFitnessBtn");
  const errorBox = document.getElementById("fitnessError");
  let current = null;

  function showError(text) {
    errorBox.textContent = text;
    errorBox.classList.toggle("show", !!text);
  }

  function setText(el, text) {
    el.textContent = text;
  }

  function row(label, value) {
    const div = document.createElement("div");
    div.className = "membership-card-row";
    const a = document.createElement("span");
    const b = document.createElement("span");
    setText(a, label);
    setText(b, value);
    div.append(a, b);
    return div;
  }

  function render(profile) {
    current = profile;
    summary.replaceChildren();
    if (!profile) {
      emptyMsg.style.display = "block";
      summary.style.display = "none";
      setText(editBtnText, "Set Up Fitness Profile");
      return;
    }
    emptyMsg.style.display = "none";
    summary.style.display = "block";
    summary.append(
      row("Goal", FITNESS_LABELS[profile.fitnessGoal] || profile.fitnessGoal),
      row("Height", profile.heightCm + " cm"),
      row("Weight", profile.weightKg + " kg"),
      row("Experience", FITNESS_LABELS[profile.workoutExperience] || profile.workoutExperience),
      row("Workout Time", profile.availableMinutes + " min"),
      row("College/Work", profile.collegeWorkTiming || "-"),
    );
    setText(editBtnText, "Edit Fitness Profile");
  }

  function fillForm(p) {
    document.getElementById("fitGoal").value = p ? p.fitnessGoal : "";
    document.getElementById("fitHeight").value = p ? p.heightCm : "";
    document.getElementById("fitWeight").value = p ? p.weightKg : "";
    document.getElementById("fitExperience").value = p ? p.workoutExperience : "";
    document.getElementById("fitMinutes").value = p ? p.availableMinutes : "";
    document.getElementById("fitTiming").value = p ? p.collegeWorkTiming : "";
  }

  editBtn.addEventListener("click", () => {
    fillForm(current);
    showError("");
    view.style.display = "none";
    form.style.display = "block";
  });

  cancelBtn.addEventListener("click", () => {
    form.style.display = "none";
    view.style.display = "block";
    showError("");
  });

  form.addEventListener("submit", async (e) => {
    e.preventDefault();
    showError("");

    const payload = {
      fitnessGoal: document.getElementById("fitGoal").value,
      heightCm: document.getElementById("fitHeight").value.trim(),
      weightKg: document.getElementById("fitWeight").value.trim(),
      workoutExperience: document.getElementById("fitExperience").value,
      availableMinutes: document.getElementById("fitMinutes").value.trim(),
      collegeWorkTiming: document.getElementById("fitTiming").value.trim(),
    };

    // Client-side checks (the server re-validates everything)
    const h = Number(payload.heightCm);
    const w = Number(payload.weightKg);
    const m = Number(payload.availableMinutes);
    if (!payload.fitnessGoal) return showError("Please select a fitness goal.");
    if (!payload.heightCm || !(h >= 100 && h <= 250))
      return showError("Height must be between 100 and 250 cm.");
    if (!payload.weightKg || !(w >= 30 && w <= 300))
      return showError("Weight must be between 30 and 300 kg.");
    if (!payload.workoutExperience)
      return showError("Please select your workout experience.");
    if (!payload.availableMinutes || !Number.isInteger(m) || m < 15 || m > 240)
      return showError("Workout time must be a whole number between 15 and 240 minutes.");
    if (payload.collegeWorkTiming.length > 100)
      return showError("College/work timing must be 100 characters or fewer.");

    const saveBtn = document.getElementById("saveFitnessBtn");
    const originalText = saveBtn.textContent;
    saveBtn.disabled = true;
    saveBtn.textContent = "Saving...";

    const result = await safeFetch("/api/fitness-profile", {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      credentials: "include",
      body: JSON.stringify(payload),
    });

    saveBtn.disabled = false;
    saveBtn.textContent = originalText;

    if (result.networkError)
      return showError("Could not reach the server. Please try again later.");
    if (result.badResponse)
      return showError(`Server error (status ${result.status}). Please try again.`);

    if (result.ok && result.data && result.data.success) {
      render(result.data.profile);
      form.style.display = "none";
      view.style.display = "block";
      showToast(result.data.message || "Fitness profile saved.", false);
      return;
    }

    showError((result.data && result.data.message) || "Could not save fitness profile.");
    if (result.status === 401) {
      setTimeout(() => (window.location.href = "login.html"), 1500);
    }
  });

  // Initial load
  safeFetch("/api/fitness-profile", { credentials: "include" }).then((result) => {
    if (result.ok && result.data && result.data.success) {
      render(result.data.profile);
    } else if (!result.networkError && !result.badResponse && result.status !== 401) {
      emptyMsg.textContent = "Could not load your fitness profile.";
    }
  });
}


/* ---------- AI WORKOUT PLAN (Step 3) ----------
   Generates/views the logged-in member's own 7-day plan. All text from
   the server is inserted with textContent (never innerHTML). */
function initWorkoutPlan() {
  const out = document.getElementById("planOutput");
  const btn = document.getElementById("generatePlanBtn");
  if (!out || !btn) return;
  const btnText = document.getElementById("generatePlanBtnText");
  const status = document.getElementById("planStatus");
  const errBox = document.getElementById("planError");

  function showError(text) {
    errBox.textContent = text;
    errBox.classList.toggle("show", !!text);
  }

  function el(tag, cls, text) {
    const n = document.createElement(tag);
    if (cls) n.className = cls;
    if (text !== undefined) n.textContent = text;
    return n;
  }

  function render(plan) {
    out.replaceChildren();
    if (!plan) {
      status.textContent = "You don't have a workout plan yet.";
      status.style.display = "block";
      out.style.display = "none";
      btnText.textContent = "Generate My Plan";
      return;
    }
    status.style.display = "none";
    out.style.display = "block";
    btnText.textContent = "Regenerate Plan";

    out.append(el("p", "plan-summary", plan.summary));
    plan.days.forEach((d) => {
      const card = el("div", "plan-day" + (d.is_rest ? " rest" : ""));
      const head = el("div", "plan-day-head");
      head.append(el("strong", "", d.day), el("span", "", d.focus));
      if (!d.is_rest) head.append(el("em", "", d.duration_minutes + " min"));
      card.append(head);
      if (d.is_rest) {
        card.append(el("p", "plan-rest", "Rest / recovery day"));
      } else {
        const list = el("ul", "plan-exercises");
        d.exercises.forEach((ex) => {
          const li = el("li");
          li.append(el("span", "plan-ex-name", ex.name));
          li.append(el("span", "plan-ex-sets", ex.sets + " x " + ex.reps));
          if (ex.notes) li.append(el("small", "", ex.notes));
          list.append(li);
        });
        card.append(list);
      }
      out.append(card);
    });
    if (plan.tips && plan.tips.length) {
      const tips = el("ul", "plan-tips");
      plan.tips.forEach((t) => tips.append(el("li", "", t)));
      out.append(el("h3", "plan-tips-title", "Tips"), tips);
    }
  }

  btn.addEventListener("click", async () => {
    showError("");
    btn.disabled = true;
    const original = btnText.textContent;
    btnText.textContent = "Generating... this can take up to 30 seconds";

    const result = await safeFetch("/api/workout-plan/generate", {
      method: "POST",
      credentials: "include",
    });

    btn.disabled = false;
    btnText.textContent = original;

    if (result.networkError)
      return showError("Could not reach the server. Please try again later.");
    if (result.badResponse)
      return showError(`Server error (status ${result.status}). Please try again.`);

    if (result.ok && result.data && result.data.success) {
      render(result.data.plan);
      showToast(result.data.message || "Your workout plan is ready.", false);
      return;
    }
    showError((result.data && result.data.message) || "Could not generate your plan.");
    if (result.status === 401) {
      setTimeout(() => (window.location.href = "login.html"), 1500);
    }
  });

  safeFetch("/api/workout-plan", { credentials: "include" }).then((result) => {
    if (result.ok && result.data && result.data.success) {
      render(result.data.plan);
    } else if (!result.networkError && result.status !== 401) {
      status.textContent = "Could not load your workout plan.";
    } else if (result.networkError) {
      status.textContent = "Could not reach the server.";
    }
  });
}


/* ---------- AI DAILY PLANNER (Step 4) ----------
   Generates/views the logged-in member's own one-day schedule. All server
   text is inserted with textContent (never as HTML). */
function initDailyPlanner() {
  const out = document.getElementById("dailyOutput");
  const btn = document.getElementById("generateDailyBtn");
  if (!out || !btn) return;
  const btnText = document.getElementById("generateDailyBtnText");
  const status = document.getElementById("dailyStatus");
  const errBox = document.getElementById("dailyError");
  const daySelect = document.getElementById("dailyDay");

  function showError(text) {
    errBox.textContent = text;
    errBox.classList.toggle("show", !!text);
  }

  function el(tag, cls, text) {
    const n = document.createElement(tag);
    if (cls) n.className = cls;
    if (text !== undefined) n.textContent = text;
    return n;
  }

  function to12h(t) {
    const [h, m] = t.split(":").map(Number);
    return ((h + 11) % 12 + 1) + ":" + String(m).padStart(2, "0") + (h < 12 ? " AM" : " PM");
  }

  function render(plan) {
    out.replaceChildren();
    if (!plan) {
      status.style.display = "block";
      out.style.display = "none";
      btnText.textContent = "Generate Daily Plan";
      return;
    }
    status.style.display = "none";
    out.style.display = "block";
    btnText.textContent = "Regenerate Daily Plan";

    out.append(el("h3", "plan-tips-title", plan.plan_day + " - " + plan.focus));
    out.append(el("p", "plan-summary", plan.summary));
    const list = el("ul", "plan-exercises");
    plan.schedule.forEach((it) => {
      const li = el("li", "daily-" + it.type);
      li.append(el("span", "daily-time", to12h(it.time)));
      li.append(el("span", "plan-ex-name", it.activity));
      li.append(el("span", "plan-ex-sets", it.duration_minutes + " min"));
      if (it.notes) li.append(el("small", "", it.notes));
      list.append(li);
    });
    out.append(list);
    if (plan.tasks && plan.tasks.length) {
      const tasks = el("ul", "plan-tips");
      plan.tasks.forEach((t) => tasks.append(el("li", "", t)));
      out.append(el("h3", "plan-tips-title", "Today's fitness tasks"), tasks);
    }
  }

  btn.addEventListener("click", async () => {
    showError("");
    btn.disabled = true;
    const original = btnText.textContent;
    btnText.textContent = "Generating... this can take up to 30 seconds";

    const result = await safeFetch("/api/daily-plan/generate", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      credentials: "include",
      body: JSON.stringify({ planDay: daySelect.value }),
    });

    btn.disabled = false;
    btnText.textContent = original;

    if (result.networkError)
      return showError("Could not reach the server. Please try again later.");
    if (result.badResponse)
      return showError(`Server error (status ${result.status}). Please try again.`);

    if (result.ok && result.data && result.data.success) {
      render(result.data.plan);
      showToast(result.data.message || "Your daily plan is ready.", false);
      return;
    }
    showError((result.data && result.data.message) || "Could not generate your daily plan.");
    if (result.status === 401) {
      setTimeout(() => (window.location.href = "login.html"), 1500);
    }
  });

  safeFetch("/api/daily-plan", { credentials: "include" }).then((result) => {
    if (result.ok && result.data && result.data.success) {
      if (!result.data.hasWorkoutPlan)
        status.textContent = "Generate your AI Workout Plan first, then plan your day here.";
      else if (!result.data.plan)
        status.textContent = "You don't have a daily plan yet.";
      render(result.data.plan);
    } else if (result.networkError) {
      status.textContent = "Could not reach the server.";
    } else if (result.status !== 401) {
      status.textContent = "Could not load your daily plan.";
    }
  });
}


/* ---------- FITNESS PROGRESS (Step 5) ----------
   Logs/views/edits/deletes the logged-in member's own weight entries via
   /api/progress. No AI service is used. All server text is inserted with
   textContent (never as HTML). */
function initProgressTracker() {
  const form = document.getElementById("progressForm");
  if (!form) return;
  const status = document.getElementById("progressStatus");
  const summaryBox = document.getElementById("progressSummary");
  const chartWrap = document.getElementById("progressChartWrap");
  const list = document.getElementById("progressList");
  const errBox = document.getElementById("progressError");
  const dateInput = document.getElementById("progDate");
  const weightInput = document.getElementById("progWeight");
  const notesInput = document.getElementById("progNotes");
  const saveBtn = document.getElementById("saveProgressBtn");
  const cancelBtn = document.getElementById("cancelProgressBtn");
  const formTitle = document.getElementById("progressFormTitle");
  let entries = [];
  let editingId = null;

  function showError(text) {
    errBox.textContent = text;
    errBox.classList.toggle("show", !!text);
  }

  function el(tag, cls, text) {
    const n = document.createElement(tag);
    if (cls) n.className = cls;
    if (text !== undefined) n.textContent = text;
    return n;
  }

  function todayStr() {
    const d = new Date();
    return d.getFullYear() + "-" + String(d.getMonth() + 1).padStart(2, "0") +
      "-" + String(d.getDate()).padStart(2, "0");
  }

  function fmtDate(iso) {
    const [y, m, d] = iso.split("-").map(Number);
    return new Date(y, m - 1, d).toLocaleDateString(undefined,
      { day: "numeric", month: "short", year: "numeric" });
  }

  function signed(n) {
    return (n > 0 ? "+" : "") + n.toFixed(1) + " kg";
  }

  function row(label, value) {
    const div = el("div", "membership-card-row");
    div.append(el("span", "", label), el("span", "", value));
    return div;
  }

  function renderSummary(s, goal) {
    summaryBox.replaceChildren();
    if (!s || !s.count) {
      summaryBox.style.display = "none";
      return;
    }
    summaryBox.style.display = "block";
    summaryBox.append(
      row("Latest Weight", s.latestWeightKg + " kg (" + fmtDate(s.latestDate) + ")"),
      row("Starting Weight", s.startWeightKg + " kg"),
    );
    if (s.count > 1) {
      const arrow = { up: " ↑", down: " ↓", steady: " →" }[s.trend] || "";
      summaryBox.append(
        row("Total Change", signed(s.totalChangeKg) + arrow),
        row("Since Previous Entry", signed(s.changeSincePreviousKg)),
        row("Lowest / Highest", s.lowestKg + " / " + s.highestKg + " kg"),
        row("Average", s.averageKg + " kg"),
      );
    }
    if (s.bmi) summaryBox.append(row("BMI (from your profile height)", String(s.bmi)));
    if (s.count > 1 && s.trend && goal === "weight_loss")
      summaryBox.append(row("Goal Check", s.trend === "down" ? "Moving toward your goal" : "Not trending down yet"));
    if (s.count > 1 && s.trend && goal === "muscle_gain")
      summaryBox.append(row("Goal Check", s.trend === "up" ? "Moving toward your goal" : "Not trending up yet"));
  }

  function renderChart() {
    chartWrap.replaceChildren();
    if (entries.length < 2) {
      chartWrap.style.display = "none";
      return;
    }
    chartWrap.style.display = "block";
    const NS = "http://www.w3.org/2000/svg";
    const W = 300, H = 120, PAD = 14;
    const ws = entries.map((e) => e.weightKg);
    let min = Math.min(...ws), max = Math.max(...ws);
    if (max - min < 1) { min -= 0.5; max += 0.5; }
    const x = (i) => PAD + (i * (W - 2 * PAD)) / (entries.length - 1);
    const y = (w) => H - PAD - ((w - min) / (max - min)) * (H - 2 * PAD);

    const svg = document.createElementNS(NS, "svg");
    svg.setAttribute("viewBox", "0 0 " + W + " " + H);
    svg.setAttribute("class", "progress-chart");
    svg.setAttribute("role", "img");
    svg.setAttribute("aria-label", "Weight trend from " + ws[0] + " kg to " + ws[ws.length - 1] + " kg");
    const line = document.createElementNS(NS, "polyline");
    line.setAttribute("points", ws.map((w, i) => x(i).toFixed(1) + "," + y(w).toFixed(1)).join(" "));
    line.setAttribute("class", "progress-chart-line");
    svg.append(line);
    ws.forEach((w, i) => {
      const dot = document.createElementNS(NS, "circle");
      dot.setAttribute("cx", x(i).toFixed(1));
      dot.setAttribute("cy", y(w).toFixed(1));
      dot.setAttribute("r", "3");
      dot.setAttribute("class", "progress-chart-dot");
      const t = document.createElementNS(NS, "title");
      t.textContent = fmtDate(entries[i].entryDate) + ": " + w + " kg";
      dot.append(t);
      svg.append(dot);
    });
    chartWrap.append(svg, el("p", "plan-disclaimer",
      "Weight over time (" + min.toFixed(1) + " - " + max.toFixed(1) + " kg)"));
  }

  function renderList() {
    list.replaceChildren();
    entries.slice().reverse().forEach((e) => {
      const li = el("li", "progress-item");
      li.append(el("span", "daily-time", fmtDate(e.entryDate)));
      li.append(el("span", "plan-ex-name", e.weightKg + " kg"));
      const actions = el("span", "progress-actions");
      const editBtn = el("button", "progress-link-btn", "Edit");
      editBtn.type = "button";
      editBtn.addEventListener("click", () => startEdit(e));
      const delBtn = el("button", "progress-link-btn danger", "Delete");
      delBtn.type = "button";
      delBtn.addEventListener("click", () => removeEntry(e));
      actions.append(editBtn, delBtn);
      li.append(actions);
      if (e.notes) li.append(el("small", "", e.notes));
      list.append(li);
    });
  }

  function renderAll(data) {
    entries = data.entries || [];
    renderSummary(data.summary, data.goal);
    renderChart();
    renderList();
    status.style.display = entries.length ? "none" : "block";
    if (!entries.length) status.textContent = "No progress entries yet. Add your first one below.";
  }

  function resetForm() {
    editingId = null;
    dateInput.value = todayStr();
    dateInput.max = todayStr();
    weightInput.value = "";
    notesInput.value = "";
    formTitle.textContent = "Add Progress Entry";
    saveBtn.textContent = "Add Entry";
    cancelBtn.style.display = "none";
    showError("");
  }

  function startEdit(e) {
    editingId = e.id;
    dateInput.value = e.entryDate;
    weightInput.value = e.weightKg;
    notesInput.value = e.notes;
    formTitle.textContent = "Edit Progress Entry";
    saveBtn.textContent = "Save Changes";
    cancelBtn.style.display = "";
    showError("");
    form.scrollIntoView({ behavior: "smooth", block: "center" });
  }

  async function reload() {
    const result = await safeFetch("/api/progress", { credentials: "include" });
    if (result.ok && result.data && result.data.success) {
      renderAll(result.data);
    } else if (result.networkError) {
      status.textContent = "Could not reach the server.";
    } else if (result.status !== 401) {
      status.textContent = "Could not load your progress.";
    }
  }

  async function removeEntry(e) {
    if (!window.confirm("Delete the entry for " + fmtDate(e.entryDate) + "?")) return;
    const result = await safeFetch("/api/progress/" + encodeURIComponent(e.id), {
      method: "DELETE",
      credentials: "include",
    });
    if (result.networkError)
      return showToast("Could not reach the server. Please try again later.", true);
    if (result.ok && result.data && result.data.success) {
      if (editingId === e.id) resetForm();
      showToast(result.data.message || "Progress entry deleted.", false);
      return reload();
    }
    showToast((result.data && result.data.message) || "Could not delete the entry.", true);
  }

  cancelBtn.addEventListener("click", resetForm);

  form.addEventListener("submit", async (ev) => {
    ev.preventDefault();
    showError("");
    const payload = {
      entryDate: dateInput.value,
      weightKg: weightInput.value.trim(),
      notes: notesInput.value.trim(),
    };
    const w = Number(payload.weightKg);
    if (!payload.entryDate) return showError("Please choose the date of this entry.");
    if (!payload.weightKg || !(w >= 30 && w <= 300))
      return showError("Weight must be between 30 and 300 kg.");
    if (payload.notes.length > 300)
      return showError("Notes must be 300 characters or fewer.");

    const original = saveBtn.textContent;
    saveBtn.disabled = true;
    saveBtn.textContent = "Saving...";
    const url = editingId ? "/api/progress/" + encodeURIComponent(editingId) : "/api/progress";
    const result = await safeFetch(url, {
      method: editingId ? "PUT" : "POST",
      headers: { "Content-Type": "application/json" },
      credentials: "include",
      body: JSON.stringify(payload),
    });
    saveBtn.disabled = false;
    saveBtn.textContent = original;

    if (result.networkError)
      return showError("Could not reach the server. Please try again later.");
    if (result.badResponse)
      return showError(`Server error (status ${result.status}). Please try again.`);
    if (result.ok && result.data && result.data.success) {
      showToast(result.data.message || "Progress saved.", false);
      resetForm();
      return reload();
    }
    showError((result.data && result.data.message) || "Could not save your progress entry.");
    if (result.status === 401) {
      setTimeout(() => (window.location.href = "login.html"), 1500);
    }
  });

  resetForm();
  reload();
}


/* ---------- AI FITNESS INSIGHTS (Step 6) ----------
   Generates/views the logged-in member's own insights via /api/insights.
   Advice only: nothing here changes progress or plans. All server text is
   inserted with textContent (never as HTML). */
function initInsights() {
  const out = document.getElementById("insightOutput");
  const btn = document.getElementById("generateInsightBtn");
  if (!out || !btn) return;
  const btnText = document.getElementById("generateInsightBtnText");
  const status = document.getElementById("insightStatus");
  const errBox = document.getElementById("insightError");

  function showError(text) {
    errBox.textContent = text;
    errBox.classList.toggle("show", !!text);
  }

  function el(tag, cls, text) {
    const n = document.createElement(tag);
    if (cls) n.className = cls;
    if (text !== undefined) n.textContent = text;
    return n;
  }

  function addList(title, items) {
    if (!items || !items.length) return;
    const ul = el("ul", "plan-tips");
    items.forEach((t) => ul.append(el("li", "", t)));
    out.append(el("h3", "plan-tips-title", title), ul);
  }

  function addText(title, text) {
    if (!text) return;
    out.append(el("h3", "plan-tips-title", title), el("p", "plan-summary", text));
  }

  function render(insight) {
    out.replaceChildren();
    if (!insight) {
      status.style.display = "block";
      out.style.display = "none";
      btnText.textContent = "Generate My Insights";
      return;
    }
    status.style.display = "none";
    out.style.display = "block";
    btnText.textContent = "Refresh Insights";
    out.append(el("p", "plan-summary", insight.summary));
    addText("Weight trend", insight.weight_trend);
    addText("Consistency", insight.consistency);
    addList("Workout recommendations", insight.workout_recommendations);
    addList("Areas to improve", insight.areas_to_improve);
    addList("Next steps", insight.next_steps);
    const used = insight.data_used || {};
    out.append(el("p", "plan-disclaimer",
      "Based on " + (used.progressEntries || 0) + " progress entr" +
      (used.progressEntries === 1 ? "y" : "ies") +
      (used.hasWorkoutPlan ? ", your workout plan" : "") +
      (used.hasDailyPlan ? ", your daily plan" : "") + "."));
  }

  btn.addEventListener("click", async () => {
    showError("");
    btn.disabled = true;
    const original = btnText.textContent;
    btnText.textContent = "Generating... this can take up to 30 seconds";

    const result = await safeFetch("/api/insights/generate", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      credentials: "include",
      body: "{}",
    });

    btn.disabled = false;
    btnText.textContent = original;

    if (result.networkError)
      return showError("Could not reach the server. Please try again later.");
    if (result.badResponse)
      return showError(`Server error (status ${result.status}). Please try again.`);

    if (result.ok && result.data && result.data.success) {
      render(result.data.insight);
      showToast(result.data.message || "Your fitness insights are ready.", false);
      return;
    }
    showError((result.data && result.data.message) || "Could not generate your insights.");
    if (result.status === 401) {
      setTimeout(() => (window.location.href = "login.html"), 1500);
    }
  });

  safeFetch("/api/insights", { credentials: "include" }).then((result) => {
    if (result.ok && result.data && result.data.success) {
      if (!result.data.hasProfile)
        status.textContent = "Set up your Fitness Profile first, then generate insights here.";
      else if (!result.data.insight)
        status.textContent = "You don't have any insights yet.";
      render(result.data.insight);
    } else if (result.networkError) {
      status.textContent = "Could not reach the server.";
    } else if (result.status !== 401) {
      status.textContent = "Could not load your insights.";
    }
  });
}


/* ---------- SMART WORKOUT RECOMMENDATIONS (Step 7) ----------
   Generates/views the logged-in member's own suggestions via
   /api/workout-recommendations. Suggestions only: nothing here changes the
   workout plan or progress. Server text is inserted with textContent. */
function initRecommendations() {
  const out = document.getElementById("recommendOutput");
  const btn = document.getElementById("generateRecommendBtn");
  if (!out || !btn) return;
  const btnText = document.getElementById("generateRecommendBtnText");
  const status = document.getElementById("recommendStatus");
  const errBox = document.getElementById("recommendError");

  function showError(text) {
    errBox.textContent = text;
    errBox.classList.toggle("show", !!text);
  }

  function el(tag, cls, text) {
    const n = document.createElement(tag);
    if (cls) n.className = cls;
    if (text !== undefined) n.textContent = text;
    return n;
  }

  function addList(title, items) {
    if (!items || !items.length) return;
    const ul = el("ul", "plan-tips");
    items.forEach((t) => ul.append(el("li", "", t)));
    out.append(el("h3", "plan-tips-title", title), ul);
  }

  function render(rec) {
    out.replaceChildren();
    if (!rec) {
      status.style.display = "block";
      out.style.display = "none";
      btnText.textContent = "Get Recommendations";
      return;
    }
    status.style.display = "none";
    out.style.display = "block";
    btnText.textContent = "Refresh Recommendations";
    out.append(el("p", "plan-summary", rec.summary));
    addList("Exercises to focus on", rec.exercises_to_focus);
    addList("Intensity & volume", rec.intensity_volume);
    addList("Recovery", rec.recovery);
    addList("Needs more attention", rec.areas_needing_attention);
    addList("Progression", rec.progression);
    const used = rec.data_used || {};
    out.append(el("p", "plan-disclaimer",
      "Based on your Fitness Profile" +
      (used.hasWorkoutPlan ? ", workout plan" : "") +
      (used.progressEntries ? ", " + used.progressEntries + " progress entr" + (used.progressEntries === 1 ? "y" : "ies") : "") +
      (used.hasInsight ? " and AI insights" : "") + "."));
  }

  btn.addEventListener("click", async () => {
    showError("");
    btn.disabled = true;
    const original = btnText.textContent;
    btnText.textContent = "Generating... this can take up to 30 seconds";

    const result = await safeFetch("/api/workout-recommendations/generate", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      credentials: "include",
      body: "{}",
    });

    btn.disabled = false;
    btnText.textContent = original;

    if (result.networkError)
      return showError("Could not reach the server. Please try again later.");
    if (result.badResponse)
      return showError(`Server error (status ${result.status}). Please try again.`);

    if (result.ok && result.data && result.data.success) {
      render(result.data.recommendation);
      showToast(result.data.message || "Your workout recommendations are ready.", false);
      return;
    }
    showError((result.data && result.data.message) || "Could not generate your recommendations.");
    if (result.status === 401) {
      setTimeout(() => (window.location.href = "login.html"), 1500);
    }
  });

  safeFetch("/api/workout-recommendations", { credentials: "include" }).then((result) => {
    if (result.ok && result.data && result.data.success) {
      if (!result.data.hasProfile)
        status.textContent = "Set up your Fitness Profile first, then get recommendations here.";
      else if (!result.data.recommendation)
        status.textContent = "You don't have any recommendations yet.";
      render(result.data.recommendation);
    } else if (result.networkError) {
      status.textContent = "Could not reach the server.";
    } else if (result.status !== 401) {
      status.textContent = "Could not load your recommendations.";
    }
  });
}


/* ---------- AI NUTRITION PLANNER (Step 8) ----------
   Generates/views the logged-in member's own nutrition plan via
   /api/nutrition-plan. Guidance only: nothing here changes the profile,
   workout plan or progress. Server text is inserted with textContent. */
function initNutrition() {
  const out = document.getElementById("nutritionOutput");
  const btn = document.getElementById("generateNutritionBtn");
  if (!out || !btn) return;
  const btnText = document.getElementById("generateNutritionBtnText");
  const status = document.getElementById("nutritionStatus");
  const errBox = document.getElementById("nutritionError");

  function showError(text) {
    errBox.textContent = text;
    errBox.classList.toggle("show", !!text);
  }

  function el(tag, cls, text) {
    const n = document.createElement(tag);
    if (cls) n.className = cls;
    if (text !== undefined) n.textContent = text;
    return n;
  }

  function addList(title, items) {
    if (!items || !items.length) return;
    const ul = el("ul", "plan-tips");
    items.forEach((t) => ul.append(el("li", "", t)));
    out.append(el("h3", "plan-tips-title", title), ul);
  }

  function render(plan) {
    out.replaceChildren();
    if (!plan) {
      status.style.display = "block";
      out.style.display = "none";
      btnText.textContent = "Generate Nutrition Plan";
      return;
    }
    status.style.display = "none";
    out.style.display = "block";
    btnText.textContent = "Refresh Nutrition Plan";
    out.append(el("p", "plan-summary", plan.summary));

    const cal = plan.calories || {};
    const pro = plan.protein || {};
    const hyd = plan.hydration || {};
    addList("Daily targets", [
      "Calories: " + cal.min + " - " + cal.max + " kcal" + (cal.note ? ". " + cal.note : ""),
      "Protein: " + pro.min_g + " - " + pro.max_g + " g" + (pro.note ? ". " + pro.note : ""),
      "Water: " + hyd.liters_min + " - " + hyd.liters_max + " litres",
    ]);
    addList("Hydration tips", hyd.tips);
    (plan.meals || []).forEach((m) => addList(m.name, m.options));
    addList("Before your workout", plan.pre_workout);
    addList("After your workout", plan.post_workout);
    addList("Good food choices", plan.food_choices);
    addList("Limit these", plan.foods_to_limit);
    addList("Tips", plan.tips);

    const used = plan.data_used || {};
    out.append(el("p", "plan-disclaimer",
      "Based on your Fitness Profile" +
      (used.hasWorkoutPlan ? ", workout plan" : "") +
      (used.progressEntries ? ", " + used.progressEntries + " progress entr" + (used.progressEntries === 1 ? "y" : "ies") : "") +
      (used.hasRecommendation ? " and workout recommendations" : "") +
      ". General guidance, not medical advice."));
  }

  btn.addEventListener("click", async () => {
    showError("");
    btn.disabled = true;
    const original = btnText.textContent;
    btnText.textContent = "Generating... this can take up to 30 seconds";

    const result = await safeFetch("/api/nutrition-plan/generate", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      credentials: "include",
      body: "{}",
    });

    btn.disabled = false;
    btnText.textContent = original;

    if (result.networkError)
      return showError("Could not reach the server. Please try again later.");
    if (result.badResponse)
      return showError(`Server error (status ${result.status}). Please try again.`);

    if (result.ok && result.data && result.data.success) {
      render(result.data.plan);
      showToast(result.data.message || "Your nutrition plan is ready.", false);
      return;
    }
    showError((result.data && result.data.message) || "Could not generate your nutrition plan.");
    if (result.status === 401) {
      setTimeout(() => (window.location.href = "login.html"), 1500);
    }
  });

  safeFetch("/api/nutrition-plan", { credentials: "include" }).then((result) => {
    if (result.ok && result.data && result.data.success) {
      if (!result.data.hasProfile)
        status.textContent = "Set up your Fitness Profile first, then generate your nutrition plan here.";
      else if (!result.data.plan)
        status.textContent = "You don't have a nutrition plan yet.";
      render(result.data.plan);
    } else if (result.networkError) {
      status.textContent = "Could not reach the server.";
    } else if (result.status !== 401) {
      status.textContent = "Could not load your nutrition plan.";
    }
  });
}
