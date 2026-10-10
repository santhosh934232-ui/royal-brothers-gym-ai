/* ============================================
   ROYAL BROTHERS FITNESS GYM - MEMBER AI DASHBOARD (Step 9)
   Reads the logged-in member's own summaries from GET /api/dashboard
   (read-only; no AI call) and links to the detailed sections on the
   Profile page. Server text is inserted with textContent only.
   ============================================ */

const GOAL_LABELS = {
  weight_loss: "Weight loss",
  muscle_gain: "Muscle gain",
  strength: "Build strength",
  endurance: "Endurance",
  general_fitness: "General fitness",
};

function el(tag, cls, text) {
  const n = document.createElement(tag);
  if (cls) n.className = cls;
  if (text !== undefined && text !== null) n.textContent = text;
  return n;
}

function card(title, cls) {
  const c = el("section", "dash-card" + (cls ? " " + cls : ""));
  c.append(el("h2", "", title));
  return c;
}

function link(c, href, label) {
  const a = el("a", "btn btn-outline", label);
  a.href = href;
  c.append(a);
}

function empty(c, text, href, label) {
  c.append(el("p", "dash-empty", text));
  link(c, href, label);
  return c;
}

function stats(items) {
  const row = el("div", "dash-stats");
  items.filter(Boolean).forEach((t) => row.append(el("span", "", t)));
  return row;
}

function signed(n) {
  return (n > 0 ? "+" : "") + n;
}

function buildCards(d) {
  const out = [];

  // Fitness profile
  let c = card("Fitness Profile");
  if (d.profile) {
    const p = d.profile;
    c.append(
      el("p", "dash-big", GOAL_LABELS[p.goal] || p.goal),
      stats([
        p.heightCm + " cm",
        p.weightKg + " kg",
        "Experience: " + p.experience,
        p.availableMinutes + " min/workout",
      ]),
    );
    link(c, "profile.html#fitnessView", "View / edit profile");
  } else {
    empty(c, "Set up your Fitness Profile to unlock your AI features.", "profile.html#fitnessView", "Set up profile");
  }
  out.push(c);

  // Today
  c = card("Today");
  if (d.workout) {
    const t = d.workout.today;
    c.append(
      el("p", "dash-big", t.isRest ? "Rest day" : t.focus),
      stats([
        t.day,
        t.isRest ? "Recover and stretch" : t.durationMinutes + " min, " + t.exerciseCount + (t.exerciseCount === 1 ? " exercise" : " exercises"),
        d.workout.trainingDays + " training / " + d.workout.restDays + " rest days a week",
      ]),
    );
    if (d.daily) {
      c.append(el("p", "", d.daily.matchesToday
        ? "Your daily plan for today is ready (" + d.daily.itemCount + " items)."
        : "Your saved daily plan is for Day " + d.daily.planDay + ". Generate one for today."));
    } else {
      c.append(el("p", "dash-empty", "No daily plan yet."));
    }
    link(c, "profile.html#dailyPlanSection", "Open daily plan");
  } else {
    empty(c, "Generate your weekly workout plan to see today's workout.", "profile.html#workoutPlanSection", "Workout plan");
  }
  out.push(c);

  // Progress
  c = card("Progress");
  if (d.progress) {
    const g = d.progress;
    c.append(
      el("p", "dash-big", g.latestWeightKg + " kg"),
      stats([
        g.totalChangeKg !== undefined && g.count > 1 ? "Change " + signed(g.totalChangeKg) + " kg" : null,
        g.changeSincePreviousKg !== null && g.changeSincePreviousKg !== undefined
          ? "Last entry " + signed(g.changeSincePreviousKg) + " kg" : null,
        g.bmi ? "BMI " + g.bmi : null,
        g.count + " entries",
      ]),
    );
    const w = el("div", "dash-weights");
    g.recentWeights.forEach((r) => w.append(el("span", "", r.date.slice(5) + ": " + r.weightKg)));
    c.append(w);
    link(c, "profile.html#progressSection", "Log / view progress");
  } else {
    empty(c, "Log your weight to see your trend.", "profile.html#progressSection", "Log progress");
  }
  out.push(c);

  // Nutrition
  c = card("Nutrition");
  if (d.nutrition) {
    const n = d.nutrition;
    c.append(
      el("p", "dash-big", n.calories.min + " - " + n.calories.max + " kcal"),
      stats([
        "Protein " + n.protein.min_g + " - " + n.protein.max_g + " g",
        "Water " + n.hydration.liters_min + " - " + n.hydration.liters_max + " L",
      ]),
      el("p", "", n.summary),
    );
    link(c, "profile.html#nutritionSection", "Full nutrition plan");
  } else {
    empty(c, "No nutrition plan yet.", "profile.html#nutritionSection", "Get nutrition plan");
  }
  out.push(c);

  // Key AI recommendation
  c = card("Key Workout Recommendation");
  if (d.recommendation) {
    c.append(el("p", "", d.recommendation.summary));
    if (d.recommendation.keyRecommendation)
      c.append(el("p", "dash-big", d.recommendation.keyRecommendation));
    link(c, "profile.html#recommendSection", "All recommendations");
  } else {
    empty(c, "No workout recommendations yet.", "profile.html#recommendSection", "Get recommendations");
  }
  out.push(c);

  // AI insight
  c = card("AI Fitness Insight");
  if (d.insight) {
    c.append(el("p", "", d.insight.summary));
    if (d.insight.nextStep) c.append(el("p", "dash-big", "Next: " + d.insight.nextStep));
    link(c, "profile.html#insightsSection", "Full insight");
  } else {
    empty(c, "No AI insight yet.", "profile.html#insightsSection", "Get insight");
  }
  out.push(c);

  return out;
}

document.addEventListener("DOMContentLoaded", async () => {
  const status = document.getElementById("dashStatus");
  const loggedOut = document.getElementById("dashLoggedOut");
  const content = document.getElementById("dashContent");
  const disclaimer = document.getElementById("dashDisclaimer");

  let res, data = null;
  try {
    res = await fetch("/api/dashboard", { credentials: "include" });
    data = await res.json();
  } catch (err) {
    status.textContent = res ? "Could not load your dashboard." : "Could not reach the server.";
    return;
  }

  if (res.status === 401) {
    status.style.display = "none";
    loggedOut.style.display = "block";
    return;
  }
  if (!res.ok || !data || !data.success) {
    status.textContent = "Could not load your dashboard.";
    return;
  }

  status.style.display = "none";
  content.replaceChildren(...buildCards(data));
  content.style.display = "grid";
  disclaimer.style.display = "block";
});
