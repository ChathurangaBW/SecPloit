const state = { selected: null, timer: null };
const $ = (id) => document.getElementById(id);
const terminal = new Set(["completed", "failed", "cancelled"]);

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;");
}

async function request(url, options = {}) {
  const response = await fetch(url, options);
  const body = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(body.detail || `HTTP ${response.status}`);
  return body;
}

async function loadHealth() {
  try {
    const body = await request("/health");
    $("health").textContent = `online · ${body.model}`;
  } catch {
    $("health").textContent = "offline";
  }
}

async function loadJobs() {
  const body = await request("/api/jobs");
  $("job-list").innerHTML = body.jobs.map(job => `
    <div class="job-card ${job.id === state.selected ? "active" : ""}" data-id="${job.id}">
      <h3>${escapeHtml(job.target)}</h3>
      <p>${escapeHtml(job.objective.slice(0, 110))}</p>
      <p>${escapeHtml(job.status)} · step ${job.current_step}/${job.max_steps}</p>
    </div>
  `).join("") || `<p class="muted">No engagements yet.</p>`;

  document.querySelectorAll(".job-card").forEach(card => {
    card.addEventListener("click", () => selectJob(card.dataset.id));
  });
}

function renderEvent(event) {
  const data = Object.keys(event.data || {}).length
    ? `<pre>${escapeHtml(JSON.stringify(event.data, null, 2))}</pre>`
    : "";
  return `
    <div class="event">
      <div class="event-head">
        <strong>${escapeHtml(event.kind)} · step ${event.step}</strong>
        <span>${escapeHtml(event.created_at)}</span>
      </div>
      <p>${escapeHtml(event.message)}</p>
      ${data}
    </div>`;
}

async function selectJob(jobId) {
  state.selected = jobId;
  const body = await request(`/api/jobs/${jobId}`);
  const job = body.job;

  $("job-summary").innerHTML = `
    <strong>${escapeHtml(job.target)}</strong><br>
    ${escapeHtml(job.objective)}<br>
    <span class="status">${escapeHtml(job.status)}</span>
    step ${job.current_step}/${job.max_steps}
  `;

  $("findings").innerHTML = body.findings.map(finding => `
    <div class="finding">
      <strong>${escapeHtml(finding.severity.toUpperCase())}: ${escapeHtml(finding.title)}</strong>
      <p>${escapeHtml(finding.claim)}</p>
      <small>confidence ${(finding.confidence * 100).toFixed(0)}%</small>
    </div>
  `).join("");

  $("events").innerHTML = body.events.map(renderEvent).join("");
  $("report").textContent = job.report || "";
  $("cancel").disabled = terminal.has(job.status);
  await loadJobs();

  clearTimeout(state.timer);
  if (!terminal.has(job.status)) {
    state.timer = setTimeout(() => selectJob(jobId), 2000);
  }
}

$("job-form").addEventListener("submit", async event => {
  event.preventDefault();
  $("form-error").textContent = "";
  try {
    const body = await request("/api/jobs", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({
        target: $("target").value,
        objective: $("objective").value,
        max_steps: Number($("steps").value),
      }),
    });
    await loadJobs();
    await selectJob(body.job.id);
  } catch (error) {
    $("form-error").textContent = error.message;
  }
});

$("refresh").addEventListener("click", loadJobs);
$("cancel").addEventListener("click", async () => {
  if (!state.selected) return;
  await request(`/api/jobs/${state.selected}/cancel`, { method: "POST" });
  await selectJob(state.selected);
});

loadHealth();
loadJobs();
