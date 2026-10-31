/* Training dashboard front-end: Chart.js rendering + AI panel. */
const COLORS = {
  ctl: "#3b82f6",
  atl: "#ec4899",
  tsb: "#10b981",
  load: "rgba(148, 163, 184, 0.45)",
  km: "#fc4c02",
  hours: "#6366f1",
  sleep: "#6366f1",
  deep: "#1e3a8a",
  rem: "#a78bfa",
  hr: "#ef4444",
  steps: "#14b8a6",
};

Chart.defaults.font.family = getComputedStyle(document.body).fontFamily;
Chart.defaults.color = "#64748b";
Chart.defaults.maintainAspectRatio = false;

const shortDate = (iso) => iso.slice(5);
const fmtPace = (s) => (s ? `${Math.floor(s / 60)}:${String(Math.round(s % 60)).padStart(2, "0")}` : "—");
const escapeHtml = (s) => String(s).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

async function getJSON(url, options) {
  const resp = await fetch(url, options);
  const data = await resp.json().catch(() => ({ error: `HTTP ${resp.status}` }));
  if (!resp.ok || data.error) throw new Error(data.error || `HTTP ${resp.status}`);
  return data;
}

function card(label, value, sub, cls = "") {
  return `<div class="card ${cls}"><div class="label">${label}</div><div class="value">${value}</div>${sub ? `<div class="sub">${sub}</div>` : ""}</div>`;
}

function formClass(tsb) {
  if (tsb > 10) return "fresh";
  if (tsb >= -10) return "optimal";
  return "fatigued";
}

function renderCards(summary) {
  const c = summary.load.current;
  const w = summary.last7;
  const m = summary.last28;
  document.getElementById("cards").innerHTML = [
    card("Form (TSB)", (c.tsb > 0 ? "+" : "") + c.tsb, escapeHtml(c.interpretation), `form ${formClass(c.tsb)}`),
    card("Fitness (CTL)", `${c.ctl} <small>min/day</small>`, "42-day average"),
    card("Fatigue (ATL)", `${c.atl} <small>min/day</small>`, "7-day average"),
    card("Last 7 days", `${w.km} <small>km</small>`, `${w.hours} h · ${w.count} activities · ${w.elevation_m} m ↑`),
    card("Last 28 days", `${m.km} <small>km</small>`, `${m.hours} h · ${m.count} activities · ${m.elevation_m} m ↑`),
  ].join("");
}

function renderLoadChart(load) {
  new Chart(document.getElementById("loadChart"), {
    data: {
      labels: load.labels.map(shortDate),
      datasets: [
        { type: "bar", label: "Daily minutes", data: load.minutes, backgroundColor: COLORS.load, yAxisID: "y", order: 3 },
        { type: "line", label: "Fitness (CTL)", data: load.ctl, borderColor: COLORS.ctl, pointRadius: 0, tension: 0.3, yAxisID: "y", order: 1 },
        { type: "line", label: "Fatigue (ATL)", data: load.atl, borderColor: COLORS.atl, pointRadius: 0, tension: 0.3, yAxisID: "y", order: 1 },
        { type: "line", label: "Form (TSB)", data: load.tsb, borderColor: COLORS.tsb, borderDash: [4, 3], pointRadius: 0, tension: 0.3, yAxisID: "y1", order: 2 },
      ],
    },
    options: {
      interaction: { mode: "index", intersect: false },
      scales: {
        x: { ticks: { maxTicksLimit: 10 }, grid: { display: false } },
        y: { title: { display: true, text: "min/day" }, beginAtZero: true },
        y1: { position: "right", title: { display: true, text: "TSB" }, grid: { drawOnChartArea: false } },
      },
      plugins: { legend: { position: "bottom" } },
    },
  });
}

function renderWeeklyChart(weekly) {
  new Chart(document.getElementById("weeklyChart"), {
    data: {
      labels: weekly.labels.map(shortDate),
      datasets: [
        { type: "bar", label: "Distance (km)", data: weekly.km, backgroundColor: COLORS.km, borderRadius: 4, yAxisID: "y" },
        { type: "line", label: "Time (h)", data: weekly.hours, borderColor: COLORS.hours, backgroundColor: COLORS.hours, tension: 0.3, yAxisID: "y1" },
      ],
    },
    options: {
      interaction: { mode: "index", intersect: false },
      scales: {
        x: { title: { display: true, text: "Week starting" }, grid: { display: false } },
        y: { beginAtZero: true, title: { display: true, text: "km" } },
        y1: { position: "right", beginAtZero: true, title: { display: true, text: "hours" }, grid: { drawOnChartArea: false } },
      },
      plugins: { legend: { position: "bottom" } },
    },
  });
}

function renderWellness(w) {
  const labels = w.labels.map(shortDate);
  const small = { plugins: { legend: { display: false } }, scales: { x: { grid: { display: false }, ticks: { maxTicksLimit: 7 } } } };
  if (w.sleep_hours.every((v) => v == null)) {
    document.getElementById("sleepChart").parentElement.innerHTML = '<p class="muted small">No sleep data — wear your watch at night to track sleep.</p>';
  } else new Chart(document.getElementById("sleepChart"), {
    type: "bar",
    data: {
      labels,
      datasets: [
        { label: "Deep", data: w.deep_hours, backgroundColor: COLORS.deep, stack: "s" },
        { label: "REM", data: w.rem_hours, backgroundColor: COLORS.rem, stack: "s" },
        {
          label: "Other",
          data: w.sleep_hours.map((t, i) => (t == null ? null : Math.max(0, +(t - (w.deep_hours[i] || 0) - (w.rem_hours[i] || 0)).toFixed(1)))),
          backgroundColor: "#c7d2fe",
          stack: "s",
        },
      ],
    },
    options: {
      ...small,
      plugins: {
        legend: { display: true, position: "bottom", labels: { boxWidth: 10 } },
        tooltip: { callbacks: { footer: (items) => { const s = w.sleep_score[items[0].dataIndex]; return `Total ${w.sleep_hours[items[0].dataIndex]} h${s ? ` · score ${s}` : ""}`; } } },
      },
      scales: { ...small.scales, x: { ...small.scales.x, stacked: true }, y: { stacked: true, title: { display: true, text: "hours" } } },
    },
  });
  new Chart(document.getElementById("hrChart"), {
    type: "line",
    data: { labels, datasets: [{ label: "Resting HR", data: w.resting_hr, borderColor: COLORS.hr, backgroundColor: COLORS.hr, tension: 0.3, spanGaps: true }] },
    options: { ...small, scales: { ...small.scales, y: { title: { display: true, text: "bpm" } } } },
  });
  new Chart(document.getElementById("stepsChart"), {
    type: "bar",
    data: { labels, datasets: [{ label: "Steps", data: w.steps, backgroundColor: COLORS.steps, borderRadius: 4 }] },
    options: { ...small, scales: { ...small.scales, y: { beginAtZero: true } } },
  });
}

function showError(el, message) {
  el.innerHTML = `<div class="flash error">${escapeHtml(message)}</div>`;
}

function initAI() {
  const form = document.getElementById("aiForm");
  if (!form) return;
  const question = document.getElementById("aiQuestion");
  const output = document.getElementById("aiOutput");
  const button = document.getElementById("aiButton");

  document.querySelectorAll(".chip[data-q]").forEach((chip) =>
    chip.addEventListener("click", () => {
      question.value = chip.dataset.q;
      form.requestSubmit();
    })
  );

  form.addEventListener("submit", async (e) => {
    e.preventDefault();
    button.disabled = true;
    output.innerHTML = '<p class="muted"><span class="spinner"></span> Analysing your training… this can take up to a minute.</p>';
    try {
      const data = await getJSON("/api/ai/analyze", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ question: question.value }),
      });
      output.innerHTML = DOMPurify.sanitize(marked.parse(data.text));
    } catch (err) {
      showError(output, err.message);
    } finally {
      button.disabled = false;
    }
  });
}

async function initDashboard() {
  const root = document.getElementById("dashboard");
  const source = root.dataset.source;
  initAI();

  getJSON(`/api/summary?source=${encodeURIComponent(source)}`)
    .then((summary) => {
      renderCards(summary);
      renderLoadChart(summary.load);
      renderWeeklyChart(summary.weekly);
    })
    .catch((err) => showError(document.getElementById("cards"), `Could not load ${source} data: ${err.message}`));

  if (root.dataset.garmin === "true") {
    getJSON("/api/wellness?days=14")
      .then(renderWellness)
      .catch((err) => showError(document.getElementById("wellnessError"), `Could not load Garmin data: ${err.message}`));
  }
}

function renderSplits(splits) {
  new Chart(document.getElementById("splitsChart"), {
    data: {
      labels: splits.map((s) => `km ${s.km}`),
      datasets: [
        { type: "bar", label: "Pace (min/km)", data: splits.map((s) => s.pace_s_per_km), backgroundColor: COLORS.km, borderRadius: 4, yAxisID: "y" },
        { type: "line", label: "Avg HR", data: splits.map((s) => s.avg_hr), borderColor: COLORS.hr, backgroundColor: COLORS.hr, tension: 0.3, yAxisID: "y1", spanGaps: true },
      ],
    },
    options: {
      interaction: { mode: "index", intersect: false },
      scales: {
        x: { grid: { display: false } },
        y: { title: { display: true, text: "pace" }, ticks: { callback: fmtPace } },
        y1: { position: "right", title: { display: true, text: "bpm" }, grid: { drawOnChartArea: false } },
      },
      plugins: {
        legend: { position: "bottom" },
        tooltip: { callbacks: { label: (ctx) => (ctx.dataset.yAxisID === "y" ? `Pace ${fmtPace(ctx.raw)} /km` : `HR ${ctx.raw ?? "—"}`) } },
      },
    },
  });
}

function initSettings() {
  const provider = document.getElementById("llmProvider");
  const model = document.getElementById("llmModel");
  if (!provider || !model) return;
  const defaults = JSON.parse(model.dataset.defaults);
  provider.addEventListener("change", () => (model.placeholder = defaults[provider.value] || ""));
}
