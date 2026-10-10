/* Member-owned reminder preferences. This client never accepts a user ID. */
function initMembershipReminderSettings() {
  const form = document.getElementById("reminderPreferencesForm");
  if (!form) return Promise.resolve();

  const enabledInput = document.getElementById("reminderEnabled");
  const leadGroup = document.getElementById("reminderLeadTimeGroup");
  const leadOptions = document.getElementById("reminderLeadTimeOptions");
  const saveButton = document.getElementById("saveReminderPreferencesBtn");
  const status = document.getElementById("reminderPreferencesStatus");
  let supportedLeadDays = [];
  let leadInputs = [];

  function setStatus(message, kind) {
    status.textContent = message;
    status.classList.toggle("error", kind === "error");
    status.classList.toggle("success", kind === "success");
  }

  function setBusy(busy) {
    enabledInput.disabled = busy;
    leadGroup.disabled = busy || supportedLeadDays.length === 0;
    saveButton.disabled = busy || supportedLeadDays.length === 0;
  }

  function renderOptions(preferences, available) {
    supportedLeadDays = Array.from(new Set(available.filter((day) =>
      Number.isInteger(day) && day >= 1 && day <= 30,
    ))).sort((a, b) => b - a);
    const selected = new Set(preferences.lead_days);
    leadOptions.replaceChildren();
    leadInputs = [];

    supportedLeadDays.forEach((days) => {
      const label = document.createElement("label");
      const checkbox = document.createElement("input");
      const text = document.createElement("span");
      checkbox.type = "checkbox";
      checkbox.name = "reminderLeadDays";
      checkbox.value = String(days);
      checkbox.id = `reminderLeadDays${days}`;
      checkbox.checked = selected.has(days);
      label.htmlFor = checkbox.id;
      text.textContent = `${days} day${days === 1 ? "" : "s"} before expiry`;
      label.append(checkbox, text);
      leadOptions.append(label);
      leadInputs.push(checkbox);
    });

    enabledInput.checked = preferences.enabled === true;
    setBusy(false);
  }

  async function request(method, payload) {
    try {
      const options = { method, credentials: "same-origin", headers: {} };
      if (payload !== undefined) {
        options.headers["Content-Type"] = "application/json";
        options.body = JSON.stringify(payload);
      }
      const response = await fetch("/api/membership/reminder-preferences", options);
      let data = null;
      try {
        data = await response.json();
      } catch (_) {
        // Keep a fixed, safe UI error below for non-JSON server responses.
      }
      return { ok: response.ok, status: response.status, data };
    } catch (_) {
      return { ok: false, status: 0, data: null, networkError: true };
    }
  }

  function showRequestError(result, action) {
    if (result.networkError) {
      setStatus("Could not reach the server. Please try again later.", "error");
    } else if (result.status === 401) {
      setStatus("Your session has expired. Please log in again.", "error");
    } else if (result.status === 403) {
      setStatus("This request was not accepted. Reload the profile and try again.", "error");
    } else if (result.status === 400 || result.status === 413 || result.status === 415) {
      setStatus("Choose valid reminder settings and try again.", "error");
    } else {
      setStatus(`Reminder settings could not be ${action}. Please try again later.`, "error");
    }
  }

  async function loadPreferences() {
    setBusy(true);
    setStatus("Loading your saved reminder preferences...");
    const result = await request("GET");
    const data = result.data;
    if (!result.ok || !data || data.success !== true || !data.preferences
        || typeof data.preferences.enabled !== "boolean"
        || !Array.isArray(data.preferences.lead_days)
        || !Array.isArray(data.supported_lead_days)) {
      setBusy(true);
      showRequestError(result, "loaded");
      return;
    }
    renderOptions(data.preferences, data.supported_lead_days);
    setStatus(data.preferences.enabled
      ? "Reminders are enabled. Your saved timing choices are shown below."
      : "Reminders are currently off. Choose timing and opt in if you want email reminders.");
  }

  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    const enabled = enabledInput.checked === true;
    const leadDays = leadInputs.filter((input) => input.checked)
      .map((input) => Number(input.value));
    if (enabled && leadDays.length === 0) {
      setStatus("Select at least one reminder time before enabling reminders.", "error");
      return;
    }

    setBusy(true);
    setStatus("Saving your reminder preferences...");
    const result = await request("PUT", { enabled, lead_days: leadDays });
    const data = result.data;
    if (!result.ok || !data || data.success !== true || !data.preferences
        || typeof data.preferences.enabled !== "boolean"
        || !Array.isArray(data.preferences.lead_days)
        || !Array.isArray(data.supported_lead_days)) {
      setBusy(false);
      showRequestError(result, "saved");
      return;
    }
    renderOptions(data.preferences, data.supported_lead_days);
    setStatus("Your reminder preferences were saved.", "success");
  });

  return loadPreferences();
}
