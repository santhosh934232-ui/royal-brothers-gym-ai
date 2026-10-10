/* ============================================
   ROYAL BROTHERS FITNESS GYM - MAIN SCRIPT
   ============================================ */

document.addEventListener("DOMContentLoaded", () => {
  initPreloader();
  initHeaderScroll();
  initMobileNav();
  initCounters();
  initBackToTop();
  initFooterYear();
  initAuthNav();
  loadHomeMembershipPlans();
});

/* ---------- PRELOADER ---------- */
function initPreloader() {
  const preloader = document.getElementById("preloader");
  if (!preloader) return;

  window.addEventListener("load", () => {
    preloader.classList.add("hidden");
    setTimeout(() => preloader.remove(), 600);
  });
}

/* ---------- HEADER SCROLL EFFECT ---------- */
function initHeaderScroll() {
  const header = document.getElementById("header");
  if (!header) return;

  window.addEventListener("scroll", () => {
    if (window.scrollY > 40) {
      header.classList.add("scrolled");
    } else {
      header.classList.remove("scrolled");
    }
  });
}

/* ---------- MOBILE NAV TOGGLE ---------- */
function initMobileNav() {
  const hamburger = document.getElementById("hamburger");
  const navMenu = document.getElementById("navMenu");
  if (!hamburger || !navMenu) return;

  hamburger.addEventListener("click", () => {
    hamburger.classList.toggle("active");
    navMenu.classList.toggle("active");
  });

  // Close menu when a nav link is clicked (mobile)
  navMenu.querySelectorAll(".nav-link").forEach((link) => {
    link.addEventListener("click", () => {
      hamburger.classList.remove("active");
      navMenu.classList.remove("active");
    });
  });

  // Close menu when clicking outside of it
  document.addEventListener("click", (e) => {
    const isClickInside =
      navMenu.contains(e.target) || hamburger.contains(e.target);
    if (!isClickInside && navMenu.classList.contains("active")) {
      hamburger.classList.remove("active");
      navMenu.classList.remove("active");
    }
  });
}

/* ---------- ANIMATED STAT COUNTERS ---------- */
function initCounters() {
  const counters = document.querySelectorAll(".counter");
  if (!counters.length) return;

  const animateCounter = (el) => {
    const target = parseInt(el.getAttribute("data-target"), 10) || 0;
    const duration = 1500;
    const startTime = performance.now();

    const step = (now) => {
      const progress = Math.min((now - startTime) / duration, 1);
      const eased = 1 - Math.pow(1 - progress, 3); // ease-out cubic
      const value = Math.floor(eased * target);
      el.textContent = value;

      if (progress < 1) {
        requestAnimationFrame(step);
      } else {
        el.textContent = target;
      }
    };

    requestAnimationFrame(step);
  };

  const observer = new IntersectionObserver(
    (entries, obs) => {
      entries.forEach((entry) => {
        if (entry.isIntersecting) {
          animateCounter(entry.target);
          obs.unobserve(entry.target);
        }
      });
    },
    { threshold: 0.5 },
  );

  counters.forEach((counter) => observer.observe(counter));
}

/* ---------- BACK TO TOP BUTTON ---------- */
function initBackToTop() {
  const backToTop = document.getElementById("backToTop");
  if (!backToTop) return;

  window.addEventListener("scroll", () => {
    if (window.scrollY > 400) {
      backToTop.classList.add("show");
    } else {
      backToTop.classList.remove("show");
    }
  });

  backToTop.addEventListener("click", () => {
    window.scrollTo({ top: 0, behavior: "smooth" });
  });
}

/* ---------- FOOTER YEAR ---------- */
function initFooterYear() {
  const yearEl = document.getElementById("year");
  if (!yearEl) return;
  yearEl.textContent = new Date().getFullYear();
}

/* ---------- NAVBAR LOGIN STATE ---------- */
/* Checks if a user is logged in (via the Flask session) and swaps the
   Login/Join Now buttons for a Welcome message + Logout button.
   Runs on every page that includes script.js. Updates BOTH the desktop
   .nav-actions buttons AND the mobile hamburger menu's Login link
   (#navMenu), so logged-in state is consistent everywhere.
   Skipped on profile.html which already has its own navbar.

   Uses AuthCache (see auth-cache.js) so that:
     - If a cached user is already known for this browser tab, the
       logged-in nav paints IMMEDIATELY, with no network wait and no
       flicker of the Login/Join Now buttons.
     - The real /api/auth/me call still always runs in the background
       to confirm/refresh that state (and to correct the UI if the
       session actually changed), but the page doesn't have to wait
       for it before showing something.
     - That call is shared (de-duped) with any other script on the
       same page (profile.js, membership.js) asking for the same
       thing at the same time, so only one network request fires. */
function initAuthNav() {
  const navActions = document.querySelector(".nav-actions");
  const navMenu = document.getElementById("navMenu");
  if (!navActions && !navMenu) return;

  // Capture the original logged-out markup once, before any mutation,
  // so the nav can be restored to it if a background revalidation
  // finds the cached "logged in" state is no longer accurate (e.g.
  // the session expired in another tab).
  const defaultNavActionsHtml = navActions ? navActions.innerHTML : null;

  function applyLoggedInNav(user) {
    const firstName = user.full_name.split(" ")[0];

    async function logout() {
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

    // ---------- Desktop nav-actions buttons ----------
    if (navActions) {
      navActions.innerHTML = `
        <a href="profile.html" class="btn btn-outline">Hi, ${firstName}</a>
        <button id="navLogoutBtn" class="btn btn-neon">Logout</button>
      `;
      const logoutBtn = document.getElementById("navLogoutBtn");
      if (logoutBtn) logoutBtn.addEventListener("click", logout);
    }

    // ---------- Mobile hamburger menu (#navMenu list) ----------
    // Repurpose the "Login" list item into a "Profile" link for logged-in
    // users, since the mobile menu has no separate area for the desktop
    // "Hi, Name" pill (which is hidden on mobile by CSS).
    if (navMenu) {
      const loginLink = Array.from(navMenu.querySelectorAll(".nav-link")).find(
        (link) => link.textContent.trim().toLowerCase() === "login",
      );

      if (loginLink) {
        loginLink.textContent = "Profile";
        loginLink.setAttribute("href", "profile.html");
      }
    }

    // ---------- Any other "Join Now" / Register links in page content ----------
    // (hero buttons, CTA sections, footer links, etc.) — anything still
    // pointing to register.html gets redirected to the profile page instead,
    // since a logged-in user shouldn't be asked to register again.
    // Excludes membership plan card buttons (.plan-card) — those are handled
    // by their own login-aware logic (see handleHomeGetStartedClick below
    // for the home page, and membership.js for the membership page).
    document.querySelectorAll('a[href="register.html"]').forEach((link) => {
      if (link.closest(".plan-card")) return;
      link.href = "profile.html";
      link.textContent = "My Profile";
    });
  }

  // ---------- Instant paint from cache (no network wait) ----------
  const cached = window.AuthCache ? window.AuthCache.getCachedUser() : null;
  if (cached && cached.ok && cached.data && cached.data.success) {
    applyLoggedInNav(cached.data.user);
  }

  // ---------- Background revalidation (always runs) ----------
  const fetchUser = window.AuthCache
    ? window.AuthCache.fetchUser
    : () =>
        fetch("/api/auth/me", { credentials: "include" }).then((res) =>
          res.json().then((data) => ({ ok: res.ok, data })),
        );

  fetchUser()
    .then(({ ok, data }) => {
      if (!ok || !data.success) {
        // Not logged in. If we'd optimistically painted a logged-in
        // nav from a stale cache, restore the original logged-out
        // markup so the UI matches reality.
        if (cached && navActions && defaultNavActionsHtml !== null) {
          navActions.innerHTML = defaultNavActionsHtml;
        }
        return;
      }

      applyLoggedInNav(data.user);
    })
    .catch(() => {
      // Silently ignore — if the check fails, just leave the nav as
      // whatever it currently shows (cached state, or the default).
    });
}

/* ============================================
   HOME PAGE MEMBERSHIP PLANS PREVIEW
   Only runs if #homePlansGrid exists on the page (i.e. only on
   index.html), so this has zero effect on any other page. Reuses
   the exact same GET /api/membership/plans API already used by
   membership.html — no new API, no hardcoded plan data.
   ============================================ */
function escapeHomeHtml(str) {
  const div = document.createElement("div");
  div.textContent = str == null ? "" : String(str);
  return div.innerHTML;
}

async function loadHomeMembershipPlans() {
  const grid = document.getElementById("homePlansGrid");
  if (!grid) return; // not on the home page

  try {
    const res = await fetch("/api/membership/plans", {
      credentials: "include",
    });
    const data = await res.json();

    if (!res.ok || !data.success || !data.plans || !data.plans.length) {
      grid.innerHTML = `<p class="plans-empty">No membership plans are currently available.</p>`;
      return;
    }
    renderHomePlanCards(data.plans, grid);
    initHomeGetStartedButtons(grid);
    // Update Membership Plans counter
    const membershipCounter = document.getElementById("membershipPlanCounter");
    if (membershipCounter) {
      membershipCounter.setAttribute("data-target", data.plans.length);
      membershipCounter.textContent = "0";
      initCounters();
    }
  } catch (err) {
    grid.innerHTML = `<p class="plans-empty">Could not load membership plans. Please try again later.</p>`;
  }
}

function renderHomePlanCards(plans, grid) {
  // Same "middle plan is Most Popular" convention used on the
  // Membership page, so the design/behaviour matches exactly.
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
                `<li><i class="fa-solid fa-check"></i> ${escapeHomeHtml(f)}</li>`,
            )
            .join("")
        : `<li><i class="fa-solid fa-check"></i> Full Gym Access</li>`;

      return `
        <div class="plan-card ${isFeatured ? "plan-featured" : ""}">
          ${isFeatured ? '<span class="plan-badge">Most Popular</span>' : ""}
          <h3 class="plan-name">${escapeHomeHtml(plan.plan_name)}</h3>
          <div class="plan-price"><span>₹</span>${plan.price}</div>
          <ul class="plan-features">
            ${featuresHtml}
          </ul>
          <a href="#" class="btn ${isFeatured ? "btn-neon" : "btn-outline"} home-get-started-btn">Get Started</a>
        </div>`;
    })
    .join("");
}

/* ---------- HOME "GET STARTED" LOGIN-AWARE REDIRECT ----------
   Does NOT duplicate any membership request logic — it only decides
   where to send the user:
     - Logged in  -> membership.html (existing membership.js takes over
                     from there: plan selection, confirm modal, submit)
     - Not logged in -> friendly message, then redirect to login.html
   Reuses the same /api/auth/me session-check endpoint already used
   by initAuthNav() and membership.js, via AuthCache so a click here
   shares any in-flight request instead of firing an extra one. */
function initHomeGetStartedButtons(grid) {
  grid.querySelectorAll(".home-get-started-btn").forEach((btn) => {
    btn.addEventListener("click", handleHomeGetStartedClick);
  });
}

async function handleHomeGetStartedClick(e) {
  e.preventDefault();

  const fetchUser = window.AuthCache
    ? window.AuthCache.fetchUser
    : () =>
        fetch("/api/auth/me", { credentials: "include" }).then((res) =>
          res.json().then((data) => ({ ok: res.ok, data })),
        );

  try {
    const { ok, data } = await fetchUser();

    if (ok && data && data.success) {
      // Logged in -> hand off to the existing Membership page workflow
      window.location.href = "membership.html";
    } else {
      showHomeToast("Please log in to continue.");
      setTimeout(() => {
        window.location.href = "login.html";
      }, 1200);
    }
  } catch (err) {
    showHomeToast("Please log in to continue.");
    setTimeout(() => {
      window.location.href = "login.html";
    }, 1200);
  }
}

/* ---------- LIGHTWEIGHT TOAST (home page only) ----------
   index.html doesn't load membership.css, so this creates its own
   small toast element on the fly using the same CSS variables already
   defined globally in style.css — no new CSS file, no design change. */
function showHomeToast(message) {
  let toast = document.getElementById("homeToast");

  if (!toast) {
    toast = document.createElement("div");
    toast.id = "homeToast";
    toast.style.position = "fixed";
    toast.style.bottom = "30px";
    toast.style.left = "50%";
    toast.style.transform = "translateX(-50%) translateY(20px)";
    toast.style.background = "var(--color-bg-card)";
    toast.style.border = "1px solid var(--color-neon-blue)";
    toast.style.color = "var(--color-text-primary)";
    toast.style.padding = "16px 28px";
    toast.style.borderRadius = "12px";
    toast.style.fontSize = "0.92rem";
    toast.style.maxWidth = "90%";
    toast.style.textAlign = "center";
    toast.style.boxShadow = "0 0 30px rgba(0, 217, 255, 0.2)";
    toast.style.opacity = "0";
    toast.style.visibility = "hidden";
    toast.style.transition = "all 0.3s ease";
    toast.style.zIndex = "3000";
    document.body.appendChild(toast);
  }

  toast.textContent = message;

  requestAnimationFrame(() => {
    toast.style.opacity = "1";
    toast.style.visibility = "visible";
    toast.style.transform = "translateX(-50%) translateY(0)";
  });

  clearTimeout(showHomeToast._timer);
  showHomeToast._timer = setTimeout(() => {
    toast.style.opacity = "0";
    toast.style.visibility = "hidden";
    toast.style.transform = "translateX(-50%) translateY(20px)";
  }, 3500);
}
