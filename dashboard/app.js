// Job Scout Dashboard — app.js
// Loads each tab's data file once on page load. No auto-refresh.
// Fresh data arrives after each GitHub Actions run redeploys GitHub Pages.

// Mirrors the display-relevant fields of config/tabs/{tab}.json — the dashboard
// is a static site with no build step, so it can't fetch the Python-side tab
// config directly; this is the client-side equivalent for shape + tracking.
// Must preserve the storageKey strings exactly — a derived/renamed key would
// silently unhide/unapply everything a user already marked.
const TAB_CONFIGS = {
  scouting: {
    dataUrl: "./data/scouting_jobs.json",
    display: { shape: "flat_list", tracking: { type: "apply", storageKey: "appliedJobs" } },
  },
  contracting: {
    dataUrl: "./data/contracting_jobs.json",
    display: { shape: "grouped_by_firm", tracking: { type: "hide", storageKey: "hiddenContractingJobs" } },
  },
  healthcare_it: {
    dataUrl: "./data/healthcare_it_jobs.json",
    display: {
      shape: "grouped_by_firm",
      tracking: { type: "hide", storageKey: "hiddenHealthcareItJobs" },
      // Field that marks a job unclassified when absent — a source whose seed
      // URL isn't scoped to one department (e.g. digital-health-jobs.com)
      // stamps null here instead of guessing.
      classifyDimension: "department",
    },
  },
};

// Tabs whose data is grouped by source firm, rendered by renderGroupedSection().
const GROUPED_TABS = Object.keys(TAB_CONFIGS).filter(t => TAB_CONFIGS[t].display.shape === "grouped_by_firm");

const HIGH_PRIORITY_THRESHOLD = 85;
const REVIEW_THRESHOLD = 70;
const URGENT_HOURS = 4;
const FRESH_HOURS = 12;

let allJobs = [];
let activeFilter = "all";
let groupedData = {};   // keyed by tab: contracting, healthcare_it
let showHidden = {};    // keyed by tab

function formatTimestamp(date) {
  const today = new Date();
  const yesterday = new Date(today);
  yesterday.setDate(yesterday.getDate() - 1);

  const dateStr = date.toLocaleDateString("en-US", { month: "numeric", day: "numeric", year: "numeric" });
  const todayStr = today.toLocaleDateString("en-US", { month: "numeric", day: "numeric", year: "numeric" });
  const yesterdayStr = yesterday.toLocaleDateString("en-US", { month: "numeric", day: "numeric", year: "numeric" });

  let label = "";
  if (dateStr === todayStr) {
    label = "Today";
  } else if (dateStr === yesterdayStr) {
    label = "Yesterday";
  } else {
    label = dateStr;
  }

  const time = date.toLocaleTimeString("en-US", { hour: "numeric", minute: "2-digit", hour12: true });
  return `${label} at ${time}`;
}

// ─── Bootstrap ──────────────────────────────────────────────────────────────

async function init() {
  let metadata = null;
  try {
    const res = await fetch(TAB_CONFIGS.scouting.dataUrl + "?t=" + Date.now());
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const data = await res.json();

    if (data._metadata) {
      metadata = data._metadata;
      allJobs = data.jobs || [];
    } else {
      allJobs = Array.isArray(data) ? data : [];
    }
  } catch (err) {
    document.getElementById("loading").innerHTML =
      `<div class="empty-state"><h3>No jobs data yet</h3><p>Run the scraper + scorer to generate scouting_jobs.json</p></div>`;
    return;
  }

  document.getElementById("loading").style.display = "none";
  document.getElementById("content").style.display = "block";

  const jobsLastRun = document.getElementById("jobs-last-run");
  if (jobsLastRun) {
    if (metadata?.last_run) {
      const lastRunDate = new Date(metadata.last_run);
      const isRecent = (Date.now() - lastRunDate.getTime()) < 12 * 60 * 60 * 1000;
      const statusDot = isRecent ? "🟢" : "🔴";
      jobsLastRun.textContent = `${statusDot} Last run: ${formatTimestamp(lastRunDate)}`;
    } else {
      jobsLastRun.textContent = "Last run: Unknown";
    }
  }

  renderTab("scouting", allJobs);

  // Load each grouped-by-firm tab's data then render (contracting is the default tab)
  for (const tab of GROUPED_TABS) {
    let data = null;
    try {
      const res = await fetch(TAB_CONFIGS[tab].dataUrl + "?t=" + Date.now());
      if (res.ok) data = await res.json();
    } catch (_) {}
    renderTab(tab, data);
  }

  // Request browser notification permission for future use
  if ("Notification" in window && Notification.permission === "default") {
    Notification.requestPermission();
  }
}

// ─── Stats Bar ──────────────────────────────────────────────────────────────

function renderStats() {
  const applied = getTrackedIds("scouting", "apply");
  const jobs = Array.isArray(allJobs) ? allJobs : [];
  const highPriority = jobs.filter(j => j.score >= HIGH_PRIORITY_THRESHOLD && !applied.has(j._hash));
  const reviewNeeded = jobs.filter(j => j.score >= REVIEW_THRESHOLD && j.score < HIGH_PRIORITY_THRESHOLD && !applied.has(j._hash));
  const newToday = jobs.filter(j => (j.metadata?.age_hours ?? 999) < 24 && !applied.has(j._hash));
  const appliedToday = getAppliedToday();

  set("stat-total",    jobs.length);
  set("stat-high",     highPriority.length);
  set("stat-review",   reviewNeeded.length);
  set("stat-new",      newToday.length);
  set("stat-applied",  appliedToday);

  // Resume usage breakdown
  const usageCounts = {};
  jobs.forEach(j => {
    const name = j.primary_resume_name;
    if (name) usageCounts[name] = (usageCounts[name] || 0) + 1;
  });
  const sorted = Object.entries(usageCounts).sort((a, b) => b[1] - a[1]);
  const usageEl = document.getElementById("resume-usage");
  if (usageEl) {
    usageEl.innerHTML = sorted
      .map(([name, count]) => `<span class="badge badge-domain">${name}: ${count}</span>`)
      .join(" ");
  }
}

function set(id, val) {
  const el = document.getElementById(id);
  if (el) el.textContent = val;
}

// ─── Rendering ──────────────────────────────────────────────────────────────

// Single entry point for both tabs — dispatches on the tab's declared display
// shape rather than the caller knowing which concrete renderer to call.
function renderTab(tabKey, data) {
  const shape = TAB_CONFIGS[tabKey]?.display?.shape;
  if (shape === "flat_list") {
    if (data !== undefined) allJobs = data;
    renderStats();
    renderJobs(allJobs);
  } else if (shape === "grouped_by_firm") {
    if (data !== undefined) groupedData[tabKey] = data;
    renderGroupedSection(tabKey);
  }
}

function renderJobs(jobs) {
  const applied = getTrackedIds("scouting", "apply");
  const filtered = filterJobs(jobs, activeFilter, applied);
  const highPriority = filtered.filter(j => j.score >= HIGH_PRIORITY_THRESHOLD);
  const reviewNeeded = filtered.filter(j => j.score >= REVIEW_THRESHOLD && j.score < HIGH_PRIORITY_THRESHOLD);
  const maybe        = filtered.filter(j => j.score < REVIEW_THRESHOLD);

  renderSection("section-high",   "high-list",   highPriority, applied);
  renderSection("section-review", "review-list", reviewNeeded, applied);
  renderSection("section-maybe",  "maybe-list",  maybe,        applied);

  // Update section badge counts
  document.getElementById("count-high").textContent   = highPriority.length;
  document.getElementById("count-review").textContent = reviewNeeded.length;
  document.getElementById("count-maybe").textContent  = maybe.length;

  // Hide empty sections
  document.getElementById("section-high").style.display   = highPriority.length ? "" : "none";
  document.getElementById("section-review").style.display = reviewNeeded.length ? "" : "none";
  document.getElementById("section-maybe").style.display  = maybe.length        ? "" : "none";
}

function renderSection(sectionId, listId, jobs, applied) {
  const list = document.getElementById(listId);
  if (!list) return;
  list.innerHTML = jobs.map(j => buildCard(j, applied.has(j._hash))).join("");
}

function buildCard(job, isApplied) {
  const ageHours = job.metadata?.age_hours ?? 999;
  const isNew    = job.metadata?.is_new_since_last_run;
  const urgency  = ageHours < URGENT_HOURS ? "urgent" : ageHours < FRESH_HOURS ? "fresh" : "";

  const scoreClass = job.score >= HIGH_PRIORITY_THRESHOLD ? "high" : job.score >= REVIEW_THRESHOLD ? "medium" : "low";

  const newBadge    = isNew    ? `<span class="badge badge-new">NEW</span>` : "";
  const sourceBadge = job.source ? `<span class="badge badge-source">${job.source}</span>` : "";
  const ageBadge    = ageHours < 999 ? `<span class="badge badge-source">Posted ${formatAge(ageHours)}</span>` : "";

  const primaryFile = job.primary_resume_file || "";
  const backupFile  = job.backup_resume_file  || "";

  const highlights = (job.highlights || []).slice(0, 3)
    .map(h => `<li>${escHtml(h)}</li>`).join("");
  const redFlags = (job.red_flags || []).slice(0, 2)
    .map(r => `<li>${escHtml(r)}</li>`).join("");

  const breakdown = job.breakdown ? `
    <div class="breakdown">
      <div class="breakdown-item">Title <span>${job.breakdown.title_match ?? "?"}/40</span></div>
      <div class="breakdown-item">Seniority <span>${job.breakdown.seniority_match ?? "?"}/20</span></div>
      <div class="breakdown-item">Domain <span>${job.breakdown.domain_match ?? "?"}/20</span></div>
      <div class="breakdown-item">Experience <span>${job.breakdown.experience_match ?? "?"}/20</span></div>
    </div>` : "";

  const applyBtnHtml = isApplied
    ? `<button class="btn btn-primary applied-state">✓ Applied</button>`
    : `<button class="btn btn-primary" onclick="applyWithResume('${escAttr(job._hash)}', '${escAttr(primaryFile)}', '${escAttr(job.url || "")}')">Apply with Primary</button>`;

  const backupBtnHtml = backupFile
    ? `<button class="btn btn-backup" onclick="applyWithResume('${escAttr(job._hash)}', '${escAttr(backupFile)}', '${escAttr(job.url || "")}')">Use Backup: ${escHtml(job.backup_resume_name || "Backup")}</button>`
    : "";

  const markAppliedHtml = !isApplied
    ? `<button class="btn btn-applied" onclick="markAsApplied('${escAttr(job._hash)}')">Mark Applied</button>`
    : "";

  return `
<div class="job-card ${urgency}" id="job-${escAttr(job._hash || "")}">
  <div class="card-top">
    <div class="card-left">
      <div class="card-title">${escHtml(job.title || "")}</div>
      <div class="card-meta">
        <strong>${escHtml(job.company || "")}</strong>
        ${job.location ? ` · ${escHtml(job.location)}` : ""}
      </div>
    </div>
    <div class="score-badge ${scoreClass}">${job.score}</div>
  </div>

  <div class="badges">${newBadge}${sourceBadge}${ageBadge}</div>

  <div class="resume-section">
    <div class="resume-primary">
      <div class="label">Primary Resume</div>
      <div class="name">${escHtml(job.primary_resume_name || "")}</div>
      <div class="file">${escHtml(primaryFile)}</div>
    </div>
    ${backupFile ? `
    <div class="resume-backup">
      <div class="label">Backup Option</div>
      <div class="name">${escHtml(job.backup_resume_name || "")} · ${escHtml(job.backup_reasoning || "")}</div>
    </div>` : ""}
  </div>

  ${job.reasoning ? `<div class="reasoning">${escHtml(job.reasoning)}</div>` : ""}
  ${breakdown}

  ${highlights ? `
  <div class="highlights-section">
    <h4>Highlights</h4>
    <ul class="highlight-list">${highlights}</ul>
  </div>` : ""}

  ${redFlags ? `
  <div class="highlights-section">
    <h4>Red Flags</h4>
    <ul class="highlight-list redflag-list">${redFlags}</ul>
  </div>` : ""}

  <div class="card-actions">
    ${applyBtnHtml}
    ${backupBtnHtml}
    ${markAppliedHtml}
    <button class="btn btn-ghost" onclick="window.open('${escAttr(job.url || "")}', '_blank')">View Job</button>
  </div>
</div>`;
}

// ─── Actions ────────────────────────────────────────────────────────────────

function applyWithResume(hash, resumeFile, jobUrl) {
  if (jobUrl) window.open(jobUrl, "_blank");
  if (resumeFile && navigator.clipboard) {
    navigator.clipboard.writeText(resumeFile)
      .then(() => showToast(`📋 Copied: ${resumeFile}`, "success"))
      .catch(() => showToast(`Resume: ${resumeFile}`, "info"));
  } else if (resumeFile) {
    showToast(`Resume to use: ${resumeFile}`, "info");
  }
}

function markAsApplied(hash) {
  const applied = getTrackedIds("scouting", "apply");
  applied.add(hash);
  saveTrackedIds("scouting", "apply", applied);

  const card = document.getElementById(`job-${hash}`);
  if (card) {
    const applyBtn = card.querySelector(".btn-primary");
    if (applyBtn) { applyBtn.textContent = "✓ Applied"; applyBtn.classList.add("applied-state"); }
    const markBtn = card.querySelector(".btn-applied");
    if (markBtn) markBtn.remove();
  }

  renderStats();
  showToast("Marked as applied ✓", "success");
}

// ─── Filtering ──────────────────────────────────────────────────────────────

function switchTab(tab) {
  document.querySelectorAll(".tab-btn").forEach(b => {
    b.classList.toggle("active", b.dataset.tab === tab);
  });
  Object.keys(TAB_CONFIGS).forEach(t => {
    const panel = document.getElementById(`tab-${t}`);
    if (panel) panel.style.display = t === tab ? "" : "none";
  });
  if (GROUPED_TABS.includes(tab)) renderTab(tab);
}

function setFilter(filter) {
  activeFilter = filter;
  document.querySelectorAll(".filter-btn").forEach(b => {
    b.classList.toggle("active", b.dataset.filter === filter);
  });
  renderJobs(allJobs);
}

function filterJobs(jobs, filter, applied) {
  const now = Date.now();
  switch (filter) {
    case "new":         return jobs.filter(j => j.metadata?.is_new_since_last_run && !applied.has(j._hash));
    case "today":       return jobs.filter(j => (j.metadata?.age_hours ?? 999) < 24 && !applied.has(j._hash));
    case "urgent":      return jobs.filter(j => (j.metadata?.age_hours ?? 999) < URGENT_HOURS && !applied.has(j._hash));
    case "high":        return jobs.filter(j => j.score >= HIGH_PRIORITY_THRESHOLD && !applied.has(j._hash));
    case "not-applied": return jobs.filter(j => !applied.has(j._hash));
    case "applied":     return jobs.filter(j => applied.has(j._hash));
    default:            return jobs.filter(j => !applied.has(j._hash));
  }
}

// ─── Tracking (localStorage) ─────────────────────────────────────────────────

// One pair for both tabs' tracking (scouting "apply", contracting "hide") —
// the storage key comes from TAB_CONFIGS so it stays exactly "appliedJobs" /
// "hiddenContractingJobs" no matter how this is called.
function getTrackedIds(tab, action) {
  const key = TAB_CONFIGS[tab]?.display?.tracking?.storageKey;
  if (!key) return new Set();
  try { return new Set(JSON.parse(localStorage.getItem(key) || "[]")); }
  catch { return new Set(); }
}

function saveTrackedIds(tab, action, set) {
  const key = TAB_CONFIGS[tab]?.display?.tracking?.storageKey;
  if (!key) return;
  localStorage.setItem(key, JSON.stringify([...set]));
}

function getAppliedToday() {
  const applied = getTrackedIds("scouting", "apply");
  // We only store hashes, not timestamps — just return total for simplicity
  return applied.size;
}

// ─── Utilities ───────────────────────────────────────────────────────────────

function formatAge(hours) {
  if (hours < 1)   return `${Math.round(hours * 60)}m ago`;
  if (hours < 24)  return `${Math.round(hours)}h ago`;
  return `${Math.round(hours / 24)}d ago`;
}

function escHtml(str) {
  return String(str)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

function escAttr(str) {
  return String(str).replace(/'/g, "\\'").replace(/"/g, "&quot;");
}

function showToast(msg, type = "info") {
  const container = document.getElementById("toast-container");
  const toast = document.createElement("div");
  toast.className = `toast ${type}`;
  toast.textContent = msg;
  container.appendChild(toast);
  setTimeout(() => toast.remove(), 3500);
}

// ─── Grouped-by-firm tabs (Contracting, Healthcare IT) ────────────────────────

function hideGroupedJob(tab, hash) {
  const hidden = getTrackedIds(tab, "hide");
  hidden.add(hash);
  saveTrackedIds(tab, "hide", hidden);
  renderGroupedSection(tab);
  showToast("Job hidden", "info");
}

function unhideGroupedJob(tab, hash) {
  const hidden = getTrackedIds(tab, "hide");
  hidden.delete(hash);
  saveTrackedIds(tab, "hide", hidden);
  renderGroupedSection(tab);
}

function toggleShowHidden(tab) {
  showHidden[tab] = document.getElementById(`${tab}-show-hidden-toggle`).checked;
  renderGroupedSection(tab);
}

function renderGroupedSection(tabKey) {
  const firmsList = document.getElementById(`${tabKey}-firms-list`);
  if (!firmsList) return;

  const data = groupedData[tabKey];
  const classifyDimension = TAB_CONFIGS[tabKey]?.display?.classifyDimension;

  const lastRunEl = document.getElementById(`${tabKey}-last-run`);
  if (lastRunEl) {
    if (data?.last_run) {
      const d = new Date(data.last_run);
      const isRecent = (Date.now() - d.getTime()) < 26 * 60 * 60 * 1000;
      const dot = isRecent ? "🟢" : "🔴";
      lastRunEl.textContent = `${dot} Last scouted: ${formatTimestamp(d)}`;
    } else {
      lastRunEl.textContent = "Last scouted: Never";
    }
  }

  if (!data || !data.firms || !data.firms.length) {
    firmsList.innerHTML = `<div class="empty-state"><h3>No jobs yet</h3><p>Run the scraper to populate this section.</p></div>`;
    return;
  }

  const hidden = getTrackedIds(tabKey, "hide");
  const showAll = !!showHidden[tabKey];

  firmsList.innerHTML = data.firms.map(firm => {
    const allJobs = [...(firm.jobs || [])].sort((a, b) =>
      new Date(b.discovered_at || 0) - new Date(a.discovered_at || 0)
    );
    const visibleJobs = showAll ? allJobs : allJobs.filter(j => !hidden.has(j._hash));

    const jobsHtml = visibleJobs.length ? visibleJobs.map(j => {
      const isHidden = hidden.has(j._hash);
      const isUnclassified = classifyDimension && !j[classifyDimension];
      const newBadge = j.is_new ? `<span class="badge badge-new">NEW</span>` : "";
      const unclassifiedBadge = isUnclassified ? `<span class="badge badge-source">Unclassified</span>` : "";
      const hiddenIndicator = isHidden ? `<span class="contracting-hidden-label">Hidden</span>` : "";
      const hideBtn = !isHidden
        ? `<button class="btn btn-hide" onclick="hideGroupedJob('${escAttr(tabKey)}', '${escAttr(j._hash)}')">Hide</button>`
        : `<button class="btn btn-hide" onclick="unhideGroupedJob('${escAttr(tabKey)}', '${escAttr(j._hash)}')">Unhide</button>`;
      const viewBtn = j.url
        ? `<button class="btn btn-ghost" onclick="window.open('${escAttr(j.url)}', '_blank')">View</button>`
        : "";

      return `
<div class="contracting-job${isHidden ? " is-hidden" : ""}${isUnclassified ? " is-unclassified" : ""}">
  <div class="contracting-job-left">
    <div class="contracting-job-title">${escHtml(j.title)}</div>
    ${j.location ? `<div class="contracting-job-meta">${escHtml(j.location)}</div>` : ""}
  </div>
  <div class="contracting-job-actions">
    ${newBadge}${unclassifiedBadge}${hiddenIndicator}${viewBtn}${hideBtn}
  </div>
</div>`;
    }).join("") : `<div class="firm-empty">No matching jobs found</div>`;

    const visibleCount = allJobs.filter(j => !hidden.has(j._hash)).length;
    return `
<div class="firm-group">
  <div class="firm-header">
    <h3><a href="${escAttr(firm.url)}" target="_blank" class="firm-link">${escHtml(firm.name)}</a></h3>
    <span class="section-badge">${visibleCount}</span>
  </div>
  <div class="firm-jobs">${jobsHtml}</div>
</div>`;
  }).join("");
}

// ─── Start ───────────────────────────────────────────────────────────────────
document.addEventListener("DOMContentLoaded", init);
