/* ============================================
   ROYAL BROTHERS FITNESS GYM - CONTACT FORM SCRIPT
   Connects the contact form to the Flask backend
   (POST /api/contact/send) instead of the fake
   client-side-only success message.
   ============================================ */

document.addEventListener("DOMContentLoaded", () => {
  const form = document.getElementById("contactForm");
  const status = document.getElementById("formStatus");
  if (!form || !status) return;

  function showStatus(text, type) {
    status.textContent = text;
    status.className = "form-status " + type;
  }

  function isValidEmail(value) {
    return /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(value);
  }

  function isValidPhone(value) {
    return /^[0-9+\-\s]{7,15}$/.test(value);
  }

  form.addEventListener("submit", async (e) => {
    e.preventDefault();

    const name = form.name.value.trim();
    const phone = form.phone.value.trim();
    const email = form.email.value.trim();
    const subject = form.subject.value;
    const message = form.message.value.trim();

    if (!name || !phone || !email || !subject || !message) {
      showStatus("Please fill in all fields before sending.", "error");
      return;
    }

    if (!isValidEmail(email)) {
      showStatus("Please enter a valid email address.", "error");
      return;
    }

    if (!isValidPhone(phone)) {
      showStatus("Please enter a valid phone number.", "error");
      return;
    }

    const submitBtn = form.querySelector('button[type="submit"]');
    const originalBtnText = submitBtn ? submitBtn.textContent : null;
    if (submitBtn) {
      submitBtn.disabled = true;
      submitBtn.textContent = "Sending...";
    }

    try {
      const response = await fetch("/api/contact/send", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        credentials: "include",
        body: JSON.stringify({ name, phone, email, subject, message }),
      });

      const data = await response.json();

      if (response.ok && data.success) {
        showStatus(
          data.message || "Message sent! We'll get back to you soon.",
          "success",
        );
        form.reset();
      } else {
        showStatus(
          data.message || "Something went wrong. Please try again.",
          "error",
        );
      }
    } catch (err) {
      showStatus(
        "Could not reach the server. Please call us instead.",
        "error",
      );
    } finally {
      if (submitBtn) {
        submitBtn.disabled = false;
        submitBtn.textContent = originalBtnText;
      }
    }
  });
});
