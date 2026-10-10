/* ============================================
   ROYAL BROTHERS FITNESS GYM - MEMBERSHIP PAGE SCRIPT
   Handles the FAQ accordion, dynamic plan loading from
   the database, and the full "Get Started" membership
   request workflow:
     - Plans are fetched from /api/membership/plans and
       rendered into #plansGrid — no hardcoded cards.
     - Not logged in -> redirect to login
     - Logged in, no active/pending request -> show confirm popup
     - Logged in, already active/pending -> disable button, show status
   ============================================ */

document.addEventListener("DOMContentLoaded", () => {
  initFaqAccordion();
  loadMembershipPlans();
});

/* ---------- FAQ ACCORDION (existing, unchanged) ---------- */
function initFaqAccordion() {
  const faqItems = document.querySelectorAll(".faq-item");

  faqItems.forEach((item) => {
    const question = item.querySelector(".faq-question");
    if (!question) return;

    question.addEventListener("click", () => {
      const isActive = item.classList.contains("active");
      faqItems.forEach((el) => el.classList.remove("active"));
      if (!isActive) {
        item.classList.add("active");
      }
    });
  });
}

/* ---------- TOAST NOTIFICATION HELPER ---------- */
function showToast(message, isError) {
  const toast = document.getElementById("toast");
  if (!toast) return;

  toast.textContent = message;
  toast.classList.toggle("error", !!isError);
  toast.classList.add("show");

  clearTimeout(showToast._timer);
  showToast._timer = setTimeout(() => {
    toast.classList.remove("show");
  }, 4000);
}

/* ---------- HTML ESCAPE HELPER (safety for plan text from DB) ---------- */
function escapeHtml(str) {
  const div = document.createElement("div");
  div.textContent = str == null ? "" : String(str);
  return div.innerHTML;
}

/* ============================================
   DYNAMIC MEMBERSHIP PLANS
   Fetches plans from the existing /api/membership/plans
   API and renders them into #plansGrid. Reuses the exact
   same card markup/classes the page used to have hardcoded,
   so the UI design, colors, and animations are unchanged.
   ============================================ */
async function loadMembershipPlans() {
  const grid = document.getElementById("plansGrid");
  if (!grid) return;

  try {
    const res = await fetch("/api/membership/plans", {
      credentials: "include",
    });
    const data = await res.json();

    if (!res.ok || !data.success || !data.plans || !data.plans.length) {
      grid.innerHTML = `<p class="plans-empty">No membership plans are currently available.</p>`;
      return;
    }

    renderPlanCards(data.plans, grid);

    // Immediately prevent default navigation on every Get Started button
    // the instant they're rendered, so a click during the brief window
    // before initMembershipRequests()'s async login/status check resolves
    // can never fall through to the raw href="register.html" link.
    document.querySelectorAll(".get-started-btn").forEach((btn) => {
      btn.addEventListener("click", (e) => e.preventDefault());
    });

    // Buttons only exist now that cards are rendered, so wire them up here.
    initMembershipRequests();
  } catch (err) {
    grid.innerHTML = `<p class="plans-empty">Could not load membership plans. Please try again later.</p>`;
  }
}

function renderPlanCards(plans, grid) {
  // No "featured" flag exists in the database, so the middle plan
  // (when there are 3 or more) is marked "Most Popular" the same way
  // the old hardcoded 3-month plan was — keeps the visual design intact.
  const featuredIndex = plans.length >= 3 ? Math.floor(plans.length / 2) : -1;

  grid.innerHTML = plans
    .map((plan, index) => {
      const isFeatured = index === featuredIndex;

      const featuresList = (plan.features || "")
        .split(",")
        .map((f) => f.trim())
        .filter(Boolean);

      const featuresHtml = featuresList.length
        ? featuresList
            .map(
              (f) =>
                `<li><i class="fa-solid fa-check"></i> ${escapeHtml(f)}</li>`,
            )
            .join("")
        : `<li><i class="fa-solid fa-check"></i> Full Gym Access</li>`;

      const durationLabel = `${plan.duration_months} Month${plan.duration_months > 1 ? "s" : ""} Plan`;

      return `
<div class="plan-card ${isFeatured ? "plan-featured" : ""}">
    ${isFeatured ? '<span class="plan-badge">Most Popular</span>' : ""}
    <h3 class="plan-name">${escapeHtml(plan.plan_name)}</h3>
    <p class="plan-tagline">${durationLabel}</p>

    <div class="plan-price">
        <span>₹</span>${plan.price}
    </div>

    <ul class="plan-features">
        ${featuresHtml}
    </ul>

    <a
        href="register.html"
        class="btn ${isFeatured ? "btn-neon" : "btn-outline"} btn-full get-started-btn"
        data-plan-id="${plan.id}"
        data-plan-name="${escapeHtml(plan.plan_name)}"
        data-duration="${plan.duration_months}"
        data-price="${plan.price}"
    >
        Get Started
    </a>
</div>`;
    })
    .join("");
}

/* ---------- MEMBERSHIP REQUEST WORKFLOW (existing, unchanged) ---------- */
function initMembershipRequests() {
  const buttons = document.querySelectorAll(".get-started-btn");
  if (!buttons.length) return;

  const modal = document.getElementById("membershipModal");
  const modalPlanName = document.getElementById("modalPlanName");
  const modalDuration = document.getElementById("modalDuration");
  const modalPrice = document.getElementById("modalPrice");
  const modalCancelBtn = document.getElementById("modalCancelBtn");
  const modalConfirmBtn = document.getElementById("modalConfirmBtn");

  let selectedPlanId = null;

  function openModal(btn) {
    selectedPlanId = btn.dataset.planId;
    modalPlanName.textContent = btn.dataset.planName;
    modalDuration.textContent = `${btn.dataset.duration} Month${btn.dataset.duration > 1 ? "s" : ""}`;
    modalPrice.textContent = `₹${btn.dataset.price}`;
    modal.classList.add("show");
  }

  function closeModal() {
    modal.classList.remove("show");
    selectedPlanId = null;
  }

  function disableButton(btn, label) {
    btn.classList.add("btn-disabled");
    btn.textContent = label;
  }

  // ---------- Check login + existing request status first ----------
  // Uses AuthCache (see auth-cache.js) so this shares its /api/auth/me
  // call with script.js's navbar check on this same page instead of
  // firing a second, separate request.
  const fetchUser = window.AuthCache
    ? window.AuthCache.fetchUser
    : () =>
        fetch("/api/auth/me", { credentials: "include" }).then((res) =>
          res.json().then((data) => ({ ok: res.ok, data })),
        );

  fetchUser()
    .then(({ ok, data }) => {
      if (!ok || !data.success) {
        // Not logged in -> clicking Get Started sends them to login
        buttons.forEach((btn) => {
          btn.addEventListener("click", (e) => {
            e.preventDefault();
            window.location.href = "login.html";
          });
        });
        return;
      }

      // Logged in -> check for an existing active/pending request
      fetch("/api/membership/my-request", { credentials: "include" })
        .then((res) => res.json())
        .then((reqData) => {
          const existing = reqData.request;

          if (existing && existing.status === "active") {
            buttons.forEach((btn) => disableButton(btn, "Membership Active"));
            return;
          }

          if (existing && existing.status === "pending") {
            buttons.forEach((btn) =>
              disableButton(btn, "Membership Request Pending"),
            );
            return;
          }

          // No active/pending request -> wire up the confirm popup
          buttons.forEach((btn) => {
            btn.addEventListener("click", (e) => {
              e.preventDefault();
              openModal(btn);
            });
          });
        });
    })
    .catch(() => {
      // If the check itself fails, fall back to sending clicks to login
      buttons.forEach((btn) => {
        btn.addEventListener("click", (e) => {
          e.preventDefault();
          window.location.href = "login.html";
        });
      });
    });

  // ---------- Modal button handlers ----------
  if (modalCancelBtn) {
    modalCancelBtn.addEventListener("click", closeModal);
  }

  if (modal) {
    modal.addEventListener("click", (e) => {
      if (e.target === modal) closeModal(); // click outside the box
    });
  }

  if (modalConfirmBtn) {
    modalConfirmBtn.addEventListener("click", async () => {
      if (!selectedPlanId) return;

      const originalText = modalConfirmBtn.textContent;
      modalConfirmBtn.disabled = true;
      modalConfirmBtn.textContent = "Submitting...";

      try {
        const res = await fetch("/api/membership/request", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          credentials: "include",
          body: JSON.stringify({ plan_id: selectedPlanId }),
        });
        const data = await res.json();

        closeModal();

        if (res.ok && data.success) {
          showToast(data.message, false);
          // Disable all buttons now that a request is pending
          buttons.forEach((btn) => {
            btn.replaceWith(btn.cloneNode(true)); // strip old click listener
          });
          document.querySelectorAll(".get-started-btn").forEach((btn) => {
            btn.classList.add("btn-disabled");
            btn.textContent = "Membership Request Pending";
          });
        } else {
          showToast(
            data.message || "Could not submit your request. Please try again.",
            true,
          );
        }
      } catch (err) {
        closeModal();
        showToast("Could not reach the server. Please try again later.", true);
      } finally {
        modalConfirmBtn.disabled = false;
        modalConfirmBtn.textContent = originalText;
      }
    });
  }
}
