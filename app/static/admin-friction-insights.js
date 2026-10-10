/* ============================================
   ROYAL BROTHERS FITNESS GYM - FRICTION INSIGHTS PAGE (Phase 3)
   Read-only admin page. Talks only to:
     GET  /api/admin/friction-insights            verified metrics (no AI call)
     POST /api/admin/friction-insights/generate   validated AI insights
   SECURITY RULE: every server string (including AI-written text) is placed into
   the page with textContent. This file never builds HTML from strings and never
   evaluates text as code.
   ============================================ */

(function () {
  "use strict";

  var NOT_AVAILABLE = "Not available";
  var busy = false;

  function $(id) { return document.getElementById(id); }

  function el(tag, className, text) {
    var node = document.createElement(tag);
    if (className) node.className = className;
    if (text !== undefined && text !== null) node.textContent = String(text);
    return node;
  }

  function show(node, visible) { if (node) node.hidden = !visible; }

  function numberOrNA(v) {
    return typeof v === "number" && isFinite(v) ? String(v) : NOT_AVAILABLE;
  }

  function periodText(tp) {
    if (!tp || !tp.supported || !tp.first_seen) return "No dates available";
    return tp.first_seen === tp.last_seen ? tp.first_seen : tp.first_seen + " to " + tp.last_seen;
  }

  function setStatus(text, isError) {
    var s = $("fiStatus");
    s.textContent = text;
    s.classList.toggle("fi-status-error", !!isError);
  }

  function clear(node) { while (node && node.firstChild) node.removeChild(node.firstChild); }

  function fillList(listId, items) {
    var ul = $(listId);
    clear(ul);
    (items || []).forEach(function (t) { ul.appendChild(el("li", null, t)); });
    show(ul, !!(items && items.length));
  }

  function statCard(value, label) {
    var card = el("div", "admin-stat-card");
    card.appendChild(el("h3", null, value));
    card.appendChild(el("p", null, label));
    return card;
  }

  function badge(text, kind) {
    return el("span", "fi-badge fi-badge-" + kind, text);
  }

  /* ---------- fetch helper: never throws, never shows server internals ---------- */
  async function api(url, options) {
    try {
      var res = await fetch(url, Object.assign({ credentials: "include" }, options || {}));
      var body = null;
      try { body = await res.json(); } catch (e) { body = null; }
      return { status: res.status, body: body };
    } catch (e) {
      return { status: 0, body: null };
    }
  }

  function selectedWindow() {
    var v = $("fiSince").value;
    return v === "all" ? null : parseInt(v, 10);
  }

  /* ---------- verified data ---------- */
  function renderVerified(facts) {
    var stats = $("fiStats");
    clear(stats);
    var tbody = document.querySelector("#fiTopicsTable tbody");
    clear(tbody);
    if (!facts) { show($("fiVerified"), false); return; }

    var cm = facts.contact_messages || {};
    stats.appendChild(statCard(numberOrNA(cm.examined), "CONTACT MESSAGES EXAMINED"));
    stats.appendChild(statCard(numberOrNA(cm.classified), "ASSIGNED A TOPIC"));
    stats.appendChild(statCard(numberOrNA(cm.unclassified), "NOT ASSIGNED A TOPIC"));
    var mr = facts.membership_requests;
    if (mr) {
      stats.appendChild(statCard(numberOrNA(mr.records_examined), "MEMBERSHIP REQUESTS"));
      stats.appendChild(statCard(numberOrNA(mr.by_status && mr.by_status.pending), "PENDING"));
      stats.appendChild(statCard(numberOrNA(mr.by_status && mr.by_status.rejected), "REJECTED"));
      var older = mr.pending_older_than_days || {};
      stats.appendChild(statCard(numberOrNA(older.count),
        "PENDING OLDER THAN " + numberOrNA(older.threshold_days) + " DAYS"));
      stats.appendChild(statCard(numberOrNA(mr.users_who_requested_again_after_rejection),
        "REQUESTED AGAIN AFTER REJECTION"));
    }
    var mp = facts.membership_plans;
    if (mp) {
      stats.appendChild(statCard(numberOrNA(mp.plans_without_features_text), "PLANS WITHOUT FEATURES TEXT"));
    }

    var topics = facts.topics || [];
    if (!topics.length) {
      var tr = el("tr");
      var td = el("td", null, "No topic was counted in this period.");
      td.colSpan = 6;
      tr.appendChild(td);
      tbody.appendChild(tr);
    }
    topics.forEach(function (t) {
      var row = el("tr");
      row.appendChild(el("td", null, t.label || NOT_AVAILABLE));
      row.appendChild(el("td", null, numberOrNA(t.record_count)));
      row.appendChild(el("td", null, numberOrNA(t.distinct_senders)));
      row.appendChild(el("td", null, t.evidence_strength || NOT_AVAILABLE));
      row.appendChild(el("td", null, (t.time_period && t.time_period.first_seen) || "-"));
      row.appendChild(el("td", null, (t.time_period && t.time_period.last_seen) || "-"));
      tbody.appendChild(row);
    });
    show($("fiVerified"), true);
  }

  function renderFindings(findings, emptyMessage) {
    var box = $("fiFindings");
    clear(box);
    if (!findings || !findings.length) {
      box.appendChild(el("p", "fi-note", emptyMessage || "No finding met the evidence threshold."));
      return;
    }
    findings.forEach(function (f) {
      var card = el("article", "fi-card");
      var head = el("div", "fi-card-head");
      head.appendChild(el("h5", "fi-card-title", f.title || "Finding"));
      head.appendChild(badge("Evidence: " + (f.evidence_strength || "unknown"), "strength"));
      card.appendChild(head);
      card.appendChild(el("p", "fi-fact",
        numberOrNA(f.record_count) + " record(s); " +
        (f.distinct_senders === null || f.distinct_senders === undefined
          ? "senders not applicable"
          : numberOrNA(f.distinct_senders) + " distinct sender(s)") +
        "; " + periodText(f.time_period)));
      if (f.evidence_summary) card.appendChild(el("p", null, f.evidence_summary));
      appendBullets(card, "The data supports", f.what_data_supports);
      appendBullets(card, "Still uncertain", f.what_remains_uncertain);
      box.appendChild(card);
    });
  }

  function appendBullets(parent, title, items) {
    if (!items || !items.length) return;
    parent.appendChild(el("p", "fi-mini-title", title));
    var ul = el("ul", "fi-list");
    items.forEach(function (t) { ul.appendChild(el("li", null, t)); });
    parent.appendChild(ul);
  }

  /* ---------- AI interpretation ---------- */
  function renderInsights(insights, general) {
    var box = $("fiInsights");
    clear(box);
    (insights || []).forEach(function (i) {
      var card = el("article", "fi-card fi-card-ai");
      var head = el("div", "fi-card-head");
      head.appendChild(el("h5", "fi-card-title", i.title || "Insight"));
      head.appendChild(badge("Priority: " + i.priority, "priority-" + i.priority));
      card.appendChild(head);

      var facts = i.facts || {};
      card.appendChild(el("p", "fi-mini-title", "Verified facts"));
      card.appendChild(el("p", "fi-fact",
        numberOrNA(facts.record_count) + " record(s); " +
        (facts.distinct_senders === null || facts.distinct_senders === undefined
          ? "senders not applicable"
          : numberOrNA(facts.distinct_senders) + " distinct sender(s)") +
        "; " + periodText(facts.time_period) + "; evidence strength: " + (i.evidence_strength || "unknown")));
      if (facts.evidence_summary) card.appendChild(el("p", null, facts.evidence_summary));

      var interp = i.interpretation || {};
      card.appendChild(el("p", "fi-mini-title fi-ai-label", interp.label || "AI interpretation - possible, not proven"));
      card.appendChild(el("p", null, interp.friction_hypothesis));
      if (interp.why_it_may_matter) card.appendChild(el("p", null, interp.why_it_may_matter));
      card.appendChild(el("p", "fi-recommendation", "Suggestion: " + interp.recommendation));
      appendBullets(card, "AI-cited evidence", interp.supporting_evidence);
      appendBullets(card, "Information that would help", i.information_needed);
      appendBullets(card, "Limitations", i.limitations);
      if (i.priority_basis) card.appendChild(el("p", "fi-note", i.priority_basis));
      box.appendChild(card);
    });
    var tips = (general || []).map(function (g) { return g.text; });
    fillList("fiGeneral", tips.map(function (t) { return t; }));
    show($("fiAi"), !!(insights && insights.length));
  }

  function renderMeta(data) {
    var any = false;
    if (data.priority_rule) { $("fiPriorityRule").textContent = data.priority_rule; any = true; }
    var warnings = (data.warnings || []).map(function (w) { return w.message; });
    fillList("fiWarnings", warnings);
    fillList("fiLimitations", data.limitations || []);
    $("fiDisclaimer").textContent = data.disclaimer || "";
    $("fiGeneratedAt").textContent = data.generated_at ? "Generated (UTC): " + data.generated_at : "";
    show($("fiMeta"), any || warnings.length > 0 || !!data.disclaimer);
  }

  function renderNeeds(data) {
    var needs = data.additional_data_needed || [];
    var tips = (data.general_suggestions || []).map(function (g) { return g.text; });
    fillList("fiNeedsList", needs);
    // general tips are shown here only for the insufficient-data state
    if (data.state === "insufficient_data") fillList("fiTipsList", tips); else fillList("fiTipsList", []);
    show($("fiNeeds"), needs.length > 0 || (data.state === "insufficient_data" && tips.length > 0));
  }

  function resetAi() {
    clear($("fiInsights"));
    fillList("fiGeneral", []);
    show($("fiAi"), false);
  }

  function handleDenied(status) {
    if (status === 401) {
      setStatus("Your admin session has ended or is not valid. Please log in as an admin again.", true);
      var a = el("a", "auth-link", " Go to admin login");
      a.href = "/admin-login.html";
      $("fiStatus").appendChild(a);
      return true;
    }
    return false;
  }

  /* ---------- load verified metrics ---------- */
  async function loadMetrics() {
    if (busy) return;
    setBusy(true);
    setStatus("Loading verified metrics...");
    resetAi();
    var win = selectedWindow();
    var r = await api("/api/admin/friction-insights" + (win ? "?since_days=" + win : ""));
    setBusy(false);

    if (handleDenied(r.status)) { disableGenerate(); return; }
    var data = r.body;
    if (!data || typeof data !== "object" || !data.state) {
      setStatus(r.status === 0 ? "Could not reach the server. Please try again."
                               : "The metrics could not be loaded. Please try again.", true);
      show($("fiVerified"), false); show($("fiNeeds"), false); show($("fiMeta"), false);
      disableGenerate();
      return;
    }

    if (data.state === "error") {
      setStatus((data.error && data.error.message) || "The metrics could not be loaded.", true);
      show($("fiVerified"), false); show($("fiNeeds"), false);
      renderMeta(data);
      disableGenerate();
      return;
    }

    renderVerified(data.verified_facts);
    renderNeeds(data);
    renderMeta(data);

    var note = $("fiAiNote");
    var aiOk = !!(data.ai && data.ai.configured);

    if (data.state === "insufficient_data") {
      renderFindings([], "No findings are shown because there is not enough data to support any.");
      setStatus("Not enough data yet to draw reliable conclusions. Counts below are exact; nothing has been inferred.");
      note.hidden = true;
      disableGenerate();
    } else if (data.state === "no_findings") {
      renderFindings([]);
      setStatus("Enough data was analysed, but no repeated pattern met the evidence threshold. No AI call is needed.");
      note.hidden = true;
      disableGenerate();
    } else {
      renderFindings(data.findings);
      setStatus("Verified metrics loaded. You can optionally generate AI interpretations of the findings below.");
      if (aiOk) {
        note.hidden = true;
        $("fiGenerateBtn").disabled = false;
      } else {
        note.textContent = "The AI service is not configured, so AI interpretations are unavailable. The verified metrics above are still accurate.";
        note.hidden = false;
        disableGenerate();
      }
    }
  }

  function disableGenerate() { $("fiGenerateBtn").disabled = true; }

  function setBusy(v) {
    busy = v;
    $("fiRefreshBtn").disabled = v;
    $("fiSince").disabled = v;
    if (v) $("fiGenerateBtn").disabled = true;
  }

  /* ---------- generate AI insights ---------- */
  async function generate() {
    if (busy) return;
    setBusy(true);
    setStatus("Generating AI insights... this can take up to a minute.");
    resetAi();
    var win = selectedWindow();
    var r = await api("/api/admin/friction-insights/generate", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ since_days: win })
    });
    setBusy(false);

    if (handleDenied(r.status)) { disableGenerate(); return; }
    var data = r.body;
    if (!data || typeof data !== "object") {
      setStatus(r.status === 0 ? "Could not reach the server. Please try again."
                               : "The insights could not be generated. Please try again.", true);
      $("fiGenerateBtn").disabled = false;
      return;
    }
    if (r.status === 429) {
      setStatus(data.message || "Please wait a moment before generating again.", true);
      $("fiGenerateBtn").disabled = false;
      return;
    }
    if (r.status === 400 || r.status === 403 || r.status === 415) {
      setStatus(data.message || "The request was not accepted.", true);
      $("fiGenerateBtn").disabled = false;
      return;
    }

    if (data.state === "error") {
      setStatus((data.error && data.error.message) || "The insights could not be generated.", true);
      renderMeta(data);
      $("fiGenerateBtn").disabled = false;
      return;
    }
    if (data.state === "insufficient_data") {
      renderNeeds(data);
      renderMeta(data);
      setStatus("Not enough data for AI insights. No AI call was made.");
      return;
    }
    if (data.state === "no_findings") {
      renderMeta(data);
      setStatus("No repeated pattern met the evidence threshold, so no AI insights were produced.");
      return;
    }
    renderInsights(data.insights, data.general_suggestions);
    renderMeta(data);
    setStatus("AI interpretations generated. They are possible explanations, not proven facts.");
    $("fiGenerateBtn").disabled = false;
  }

  document.addEventListener("DOMContentLoaded", function () {
    if (!$("fiStatus")) return;
    $("fiRefreshBtn").addEventListener("click", loadMetrics);
    $("fiGenerateBtn").addEventListener("click", generate);
    $("fiSince").addEventListener("change", loadMetrics);
    loadMetrics();
  });
})();
