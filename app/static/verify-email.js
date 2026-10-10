/* ============================================
   ROYAL BROTHERS FITNESS GYM - VERIFY EMAIL PAGE
   Reads ?token= from the URL, calls the backend
   (GET /api/auth/verify-email), and shows the result.
   ============================================ */

document.addEventListener("DOMContentLoaded", () => {
  verifyEmailToken();
  initResendForm();
});

function getElements() {
  return {
    title: document.getElementById("verifyTitle"),
    subtitle: document.getElementById("verifySubtitle"),
    icon: document.getElementById("verifyIcon"),
    errorBox: document.getElementById("formError"),
    resendSection: document.getElementById("resendSection"),
  };
}

function showMessage(errorBox, text, isError) {
  if (!errorBox) return;
  errorBox.textContent = text;
  errorBox.style.color = isError ? "#ff5c7a" : "#00d9ff";
  if (text) {
    errorBox.classList.add("show");
  } else {
    errorBox.classList.remove("show");
  }
}

async function verifyEmailToken() {
  const { title, subtitle, icon, errorBox, resendSection } = getElements();

  const params = new URLSearchParams(window.location.search);
  const token = params.get("token");

  if (!token) {
    if (title) title.textContent = "Invalid Verification Link";
    if (subtitle)
      subtitle.textContent = "This link is missing its verification token.";
    if (icon) icon.innerHTML = '<i class="fa-solid fa-circle-xmark"></i>';
    if (resendSection) resendSection.style.display = "block";
    return;
  }

  try {
    const response = await fetch(
      `/api/auth/verify-email?token=${encodeURIComponent(token)}`,
      { method: "GET", credentials: "include" },
    );
    const data = await response.json();

    if (response.ok && data.success) {
      if (title) title.textContent = "Email Verified!";
      if (subtitle)
        subtitle.textContent = "Your account is ready. You can now log in.";
      if (icon) icon.innerHTML = '<i class="fa-solid fa-circle-check"></i>';
      showMessage(
        errorBox,
        data.message || "Your email has been verified successfully.",
        false,
      );

      setTimeout(() => {
        window.location.href = "login.html";
      }, 2000);
    } else {
      // Covers both "invalid/already used" and "expired" cases -- the
      // backend message text tells us which one it was.
      if (title) title.textContent = "Verification Failed";
      if (subtitle) subtitle.textContent = "This link is no longer valid.";
      if (icon) icon.innerHTML = '<i class="fa-solid fa-circle-xmark"></i>';
      showMessage(
        errorBox,
        data.message || "This verification link is invalid or has expired.",
        true,
      );
      if (resendSection) resendSection.style.display = "block";
    }
  } catch (err) {
    if (title) title.textContent = "Something Went Wrong";
    if (subtitle) subtitle.textContent = "Could not reach the server.";
    if (icon) icon.innerHTML = '<i class="fa-solid fa-circle-xmark"></i>';
    showMessage(
      errorBox,
      "Could not reach the server. Please try again later.",
      true,
    );
    if (resendSection) resendSection.style.display = "block";
  }
}

/* ---------- RESEND VERIFICATION EMAIL (from this page) ---------- */
function initResendForm() {
  const resendBtn = document.getElementById("resendBtn");
  const resendEmailInput = document.getElementById("resendEmail");
  const { errorBox } = getElements();
  if (!resendBtn) return;

  resendBtn.addEventListener("click", async () => {
    const email = resendEmailInput?.value.trim();

    if (!email) {
      showMessage(errorBox, "Please enter your email address.", true);
      return;
    }

    const originalText = resendBtn.textContent;
    resendBtn.disabled = true;
    resendBtn.textContent = "Sending...";

    try {
      const response = await fetch("/api/auth/resend-verification", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        credentials: "include",
        body: JSON.stringify({ email }),
      });

      const data = await response.json();

      showMessage(
        errorBox,
        data.message ||
          "If that account needs verifying, a new verification email has been sent.",
        !response.ok || !data.success,
      );
    } catch (err) {
      showMessage(
        errorBox,
        "Could not reach the server. Please try again later.",
        true,
      );
    } finally {
      resendBtn.disabled = false;
      resendBtn.textContent = originalText;
    }
  });
}
