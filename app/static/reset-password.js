/* ============================================
   ROYAL BROTHERS FITNESS GYM - RESET PASSWORD PAGE
   Reads the reset token from the URL (?token=...), connects the
   form to the Flask backend (POST /api/auth/reset-password), and
   handles the show/hide password eye icons.
   ============================================ */

document.addEventListener("DOMContentLoaded", () => {
  initPasswordToggle("toggleNewPassword", "newPassword");
  initPasswordToggle("toggleConfirmPassword", "confirmPassword");
  initResetPasswordForm();
});

/* ---------- SHOW/HIDE PASSWORD (EYE ICON) ---------- */
function initPasswordToggle(toggleId, inputId) {
  const toggleBtn = document.getElementById(toggleId);
  const passwordInput = document.getElementById(inputId);
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

/* ---------- RESET PASSWORD FORM SUBMISSION ---------- */
function initResetPasswordForm() {
  const form = document.getElementById("resetPasswordForm");
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

  // The token comes from the link emailed to the user, e.g.
  // reset-password.html?token=xxxxxxxx
  const token = new URLSearchParams(window.location.search).get("token");

  if (!token) {
    showMessage(
      "This reset link is missing its token. Please request a new one.",
      true,
    );
    const submitBtn = form.querySelector('button[type="submit"]');
    if (submitBtn) submitBtn.disabled = true;
    return;
  }

  form.addEventListener("submit", async (e) => {
    e.preventDefault();
    showMessage("", false);

    const newPassword = document.getElementById("newPassword")?.value;
    const confirmPassword = document.getElementById("confirmPassword")?.value;

    if (!newPassword || !confirmPassword) {
      showMessage("Please fill in both password fields.", true);
      return;
    }

    if (newPassword !== confirmPassword) {
      showMessage("Passwords do not match.", true);
      return;
    }

    if (newPassword.length < 6) {
      showMessage("Password must be at least 6 characters.", true);
      return;
    }

    const submitBtn = form.querySelector('button[type="submit"]');
    const originalBtnText = submitBtn ? submitBtn.textContent : null;
    if (submitBtn) {
      submitBtn.disabled = true;
      submitBtn.textContent = "Resetting...";
    }

    try {
      const response = await fetch("/api/auth/reset-password", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        credentials: "include",
        body: JSON.stringify({
          token,
          newPassword,
          confirmPassword,
        }),
      });

      const data = await response.json();

      if (response.ok && data.success) {
        showMessage(
          "Password reset successfully! Redirecting to login...",
          false,
        );
        form.reset();
        setTimeout(() => {
          window.location.href = "login.html";
        }, 1500);
      } else {
        showMessage(
          data.message || "Could not reset your password. Please try again.",
          true,
        );
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
