/* ============================================
   ROYAL BROTHERS FITNESS GYM - FORGOT PASSWORD PAGE
   Connects the forgot-password form to the Flask backend
   (POST /api/auth/forgot-password).
   ============================================ */

document.addEventListener("DOMContentLoaded", () => {
  initForgotPasswordForm();
});

function initForgotPasswordForm() {
  const form = document.getElementById("forgotPasswordForm");
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

    const email = document.getElementById("forgotEmail")?.value.trim();

    if (!email) {
      showMessage("Please enter your email.", true);
      return;
    }

    const submitBtn = form.querySelector('button[type="submit"]');
    const originalBtnText = submitBtn ? submitBtn.textContent : null;
    if (submitBtn) {
      submitBtn.disabled = true;
      submitBtn.textContent = "Sending...";
    }

    try {
      const response = await fetch("/api/auth/forgot-password", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        credentials: "include",
        body: JSON.stringify({ email }),
      });

      const data = await response.json();

      if (response.ok && data.success) {
        showMessage(
          data.message ||
            "If an account exists for that email, a reset link has been sent.",
          false,
        );
        form.reset();
      } else {
        showMessage(
          data.message || "Something went wrong. Please try again.",
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
