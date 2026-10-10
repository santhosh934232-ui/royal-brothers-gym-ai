/* ============================================
   ROYAL BROTHERS FITNESS GYM - LOGIN PAGE
   Connects the login form to the Flask backend
   (POST /api/auth/login), handles the show/hide
   password eye icon, and the "Resend verification
   email" link.
   ============================================ */

document.addEventListener("DOMContentLoaded", () => {
  initPasswordToggle();
  initLoginForm();
  initResendVerification();
});

/* ---------- SHOW/HIDE PASSWORD (EYE ICON) ---------- */
function initPasswordToggle() {
  const toggleBtn = document.getElementById("togglePassword");
  const passwordInput = document.getElementById("loginPassword");
  if (!toggleBtn || !passwordInput) return;

  toggleBtn.addEventListener("click", () => {
    const isHidden = passwordInput.type === "password";
    passwordInput.type = isHidden ? "text" : "password";

    const icon = toggleBtn.querySelector("i");
    if (icon) {
      icon.classList.toggle("fa-eye", !isHidden);
      icon.classList.toggle("fa-eye-slash", isHidden);
    }
    toggleBtn.setAttribute(
      "aria-label",
      isHidden ? "Hide password" : "Show password",
    );
  });
}

/* ---------- LOGIN FORM SUBMISSION ---------- */
function initLoginForm() {
  const form = document.getElementById("loginForm");
  if (!form) return;

  const errorBox = document.getElementById("formError");

  function showMessage(text, isError) {
    if (!errorBox) return;
    errorBox.textContent = text;
    errorBox.style.color = isError ? "#ff5c7a" : "#00d9ff";
    if (text) {
      errorBox.classList.add("show");
    } else {
      errorBox.classList.remove("show");
    }
  }

  form.addEventListener("submit", async (e) => {
    e.preventDefault();
    showMessage("", false);

    const loginEmail = document.getElementById("loginEmail")?.value.trim();
    const loginPassword = document.getElementById("loginPassword")?.value;
    const rememberMe = document.getElementById("rememberMe")?.checked;

    if (!loginEmail || !loginPassword) {
      showMessage("Please enter both email and password.", true);
      return;
    }

    const submitBtn = form.querySelector('button[type="submit"]');
    const originalBtnText = submitBtn ? submitBtn.textContent : null;
    if (submitBtn) {
      submitBtn.disabled = true;
      submitBtn.textContent = "Logging In...";
    }

    try {
      const response = await fetch("/api/auth/login", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        credentials: "include", // sends/receives the Flask session cookie
        body: JSON.stringify({
          loginEmail,
          loginPassword,
          rememberMe,
        }),
      });

      const data = await response.json();

      if (response.ok && data.success) {
        showMessage("Login successful! Redirecting...", false);
        setTimeout(() => {
          window.location.href = "index.html";
        }, 1000);
      } else {
        // Covers: invalid credentials, locked account ("Too many failed
        // login attempts..."), and unverified account -- the backend
        // message already says exactly what happened.
        showMessage(data.message || "Invalid email or password.", true);
      }
    } catch (err) {
      showMessage("Could not reach the server. Please try again later.", true);
    } finally {
      if (submitBtn) {
        submitBtn.disabled = false;
        submitBtn.textContent = originalBtnText;
      }
    }
  });
}

/* ---------- RESEND VERIFICATION EMAIL ---------- */
function initResendVerification() {
  const link = document.getElementById("resendVerificationLink");
  const errorBox = document.getElementById("formError");
  if (!link) return;

  function showMessage(text, isError) {
    if (!errorBox) return;
    errorBox.textContent = text;
    errorBox.style.color = isError ? "#ff5c7a" : "#00d9ff";
    if (text) {
      errorBox.classList.add("show");
    } else {
      errorBox.classList.remove("show");
    }
  }

  link.addEventListener("click", async (e) => {
    e.preventDefault();

    let email = document.getElementById("loginEmail")?.value.trim();

    if (!email) {
      email = window.prompt("Enter the email address you registered with:");
      if (!email) return;
      email = email.trim();
    }

    const originalText = link.textContent;
    link.textContent = "Sending...";

    try {
      const response = await fetch("/api/auth/resend-verification", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        credentials: "include",
        body: JSON.stringify({ email }),
      });

      const data = await response.json();

      showMessage(
        data.message ||
          "If that account needs verifying, a new verification email has been sent.",
        !response.ok || !data.success,
      );
    } catch (err) {
      showMessage("Could not reach the server. Please try again later.", true);
    } finally {
      link.textContent = originalText;
    }
  });
}
