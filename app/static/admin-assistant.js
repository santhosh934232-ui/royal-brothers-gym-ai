/*
 * Phase 4D Admin Assistant UI.
 * Uses the existing authenticated admin session and Phase 4C API. Questions and
 * answers stay in this page's DOM only and are inserted with textContent.
 */
(() => {
  "use strict";

  const API_URL = "/api/admin/assistant/ask";
  const MAX_QUESTION_CHARS = 1200;
  let initialized = false;

  document.addEventListener("DOMContentLoaded", initAdminAssistantChat);

  function initAdminAssistantChat() {
    if (initialized) return;
    const form = document.getElementById("adminAssistantForm");
    const input = document.getElementById("assistantQuestion");
    const sendButton = document.getElementById("assistantSendButton");
    const conversation = document.getElementById("assistantConversation");
    const loading = document.getElementById("assistantLoading");
    const validation = document.getElementById("assistantValidationError");
    const characterCount = document.getElementById("assistantCharacterCount");
    if (!form || !input || !sendButton || !conversation || !loading || !validation || !characterCount) return;

    initialized = true;
    let requestInProgress = false;

    function showValidation(message) {
      validation.textContent = message;
      validation.hidden = !message;
      input.setAttribute("aria-invalid", message ? "true" : "false");
    }

    function updateCharacterCount() {
      characterCount.textContent = `${input.value.length} / ${MAX_QUESTION_CHARS}`;
    }

    function appendMessage(kind, label, text) {
      const article = document.createElement("article");
      article.className = `assistant-message assistant-message-${kind}`;
      const heading = document.createElement("p");
      heading.className = "assistant-message-label";
      heading.textContent = label;
      const content = document.createElement("p");
      content.className = "assistant-message-text";
      content.textContent = String(text);
      article.append(heading, content);
      conversation.append(article);
      conversation.scrollTop = conversation.scrollHeight;
    }

    function setBusy(busy) {
      requestInProgress = busy;
      sendButton.disabled = busy;
      input.disabled = busy;
      loading.hidden = !busy;
      form.setAttribute("aria-busy", busy ? "true" : "false");
    }

    function cooldownMessage(response) {
      const value = response.headers && response.headers.get
        ? response.headers.get("Retry-After")
        : null;
      if (value && /^\d+$/.test(value.trim())) {
        const seconds = Number(value.trim());
        if (seconds > 0 && Number.isFinite(seconds)) {
          return `Please wait ${seconds} second${seconds === 1 ? "" : "s"} before sending another question.`;
        }
      }
      if (value) {
        const retryAt = Date.parse(value);
        if (Number.isFinite(retryAt)) {
          const seconds = Math.ceil((retryAt - Date.now()) / 1000);
          if (seconds > 0) {
            return `Please wait about ${seconds} second${seconds === 1 ? "" : "s"} before sending another question.`;
          }
        }
      }
      return "The assistant is busy or has reached its request limit. Please wait before trying again.";
    }

    function messageForHttpStatus(response, data) {
      const code = data && data.error && typeof data.error.code === "string"
        ? data.error.code
        : "";
      switch (response.status) {
        case 400:
          return "The question could not be accepted. Check that it is not empty and is within the 1,200-character limit.";
        case 401:
          return "Your admin session may have expired. Sign in as an administrator again, then reload this dashboard.";
        case 403:
          return "This request was blocked. Make sure you are using the authenticated admin dashboard.";
        case 413:
          return "The request was too large. Shorten your question and try again.";
        case 415:
          return "The request format was not accepted. Reload the dashboard and try again.";
        case 429:
          return cooldownMessage(response);
        case 500:
          return "The assistant could not complete this request. Your conversation is still here; please try again later.";
        case 502:
          if (code === "invalid_key") return "The AI service is not authorized. Contact the administrator.";
          if (code === "model_unavailable") return "The configured AI model is unavailable. Contact the administrator.";
          return "The AI service could not provide an answer. Please try again later.";
        case 503:
          if (code === "not_configured") return "The assistant is not configured yet. Contact the administrator.";
          if (code === "data_unavailable") return "Approved gym data is temporarily unavailable. Please try again later.";
          return "The assistant is temporarily unavailable. Please try again later.";
        case 504:
          return "The assistant took too long to respond. Please try again later.";
        default:
          return "The assistant request could not be completed. Please try again later.";
      }
    }

    input.addEventListener("input", () => {
      updateCharacterCount();
      if (validation.textContent) showValidation("");
    });

    form.addEventListener("submit", async (event) => {
      event.preventDefault();
      if (requestInProgress) return;

      const question = input.value.trim();
      if (!question) {
        showValidation("Enter a question before sending.");
        input.focus();
        return;
      }
      if (question.length > MAX_QUESTION_CHARS) {
        showValidation("Questions must be no longer than 1,200 characters.");
        input.focus();
        return;
      }
      showValidation("");
      appendMessage("user", "You", question);
      input.value = "";
      updateCharacterCount();
      setBusy(true);

      try {
        const response = await fetch(API_URL, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          credentials: "include",
          body: JSON.stringify({ question }),
        });

        let data = null;
        try {
          data = await response.json();
        } catch (_parseError) {
          data = null;
        }

        if (!response.ok) {
          appendMessage("error", "Assistant", messageForHttpStatus(response, data));
          return;
        }

        if (!data || data.success !== true || typeof data.status !== "string") {
          appendMessage("error", "Assistant", "The server returned an unexpected response. No answer was displayed.");
          return;
        }
        if ((data.status === "ok" || data.status === "insufficient_data") &&
            typeof data.answer === "string" && data.answer.trim()) {
          const kind = data.status === "insufficient_data" ? "insufficient" : "assistant";
          appendMessage(kind, data.status === "insufficient_data" ? "Not enough data" : "Assistant", data.answer);
          return;
        }

        appendMessage("error", "Assistant", "The server returned an unexpected response. No answer was displayed.");
      } catch (_networkError) {
        appendMessage("error", "Assistant", "Could not reach the assistant service. Your question remains in the conversation; check your connection and try again.");
      } finally {
        setBusy(false);
        input.focus();
      }
    });

    updateCharacterCount();
  }
})();
