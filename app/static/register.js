/* ============================================
   ROYAL BROTHERS FITNESS GYM - REGISTER PAGE
   Connects the registration form to the Flask backend
   (POST /api/auth/register) and handles the show/hide
   password eye icons.
   ============================================ */

document.addEventListener("DOMContentLoaded", () => {
  initPasswordToggles();
  initRegisterForm();
});

/* ---------- SHOW/HIDE PASSWORD (EYE ICON) ---------- */
function initPasswordToggles() {
  const toggleButtons = document.querySelectorAll(".toggle-password");

  toggleButtons.forEach((button) => {
    button.addEventListener("click", () => {
      const targetId = button.getAttribute("data-target");
      const input = document.getElementById(targetId);
      const icon = button.querySelector("i");
      if (!input) return;

      const isHidden = input.type === "password";
      input.type = isHidden ? "text" : "password";

      if (icon) {
        icon.classList.toggle("fa-eye", !isHidden);
        icon.classList.toggle("fa-eye-slash", isHidden);
      }
      button.setAttribute(
        "aria-label",
        isHidden ? "Hide password" : "Show password",
      );
    });
  });
}

/* ---------- REGISTRATION FORM SUBMISSION ---------- */
function initRegisterForm() {
  const form = document.getElementById("registerForm");
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

    const fullName = document.getElementById("fullName")?.value.trim();
    const registerEmail = document
      .getElementById("registerEmail")
      ?.value.trim();
    const gender = document.getElementById("gender")?.value;
    const registerPassword = document.getElementById("registerPassword")?.value;
    const confirmPassword = document.getElementById("confirmPassword")?.value;
    const agreeTerms = document.getElementById("agreeTerms")?.checked;

    // ---------- Basic client-side checks ----------
    if (
      !fullName ||
      !registerEmail ||
      !gender ||
      !registerPassword ||
      !confirmPassword
    ) {
      showMessage("Please fill in all fields.", true);
      return;
    }

    if (registerPassword !== confirmPassword) {
      showMessage("Passwords do not match.", true);
      return;
    }

    if (!agreeTerms) {
      showMessage("You must agree to the terms to continue.", true);
      return;
    }

    const submitBtn = form.querySelector('button[type="submit"]');
    const originalBtnText = submitBtn ? submitBtn.textContent : null;
    if (submitBtn) {
      submitBtn.disabled = true;
      submitBtn.textContent = "Creating Account...";
    }

    try {
      const response = await fetch("/api/auth/register", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        credentials: "include", // sends/receives the Flask session cookie
        body: JSON.stringify({
          fullName,
          registerEmail,
          gender,
          registerPassword,
          confirmPassword,
          agreeTerms,
        }),
      });

      const data = await response.json();

      if (response.ok && data.success) {
        // NOTE: registration no longer logs the user in automatically.
        // They must verify their email first, then log in.
        showMessage(
          data.message ||
            "Account created! Please check your email to verify your account before logging in.",
          false,
        );
        form.reset();
        setTimeout(() => {
          window.location.href = "login.html";
        }, 2500);
      } else {
        showMessage(
          data.message || "Registration failed. Please try again.",
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
