const $ = (selector) => document.querySelector(selector);
const $$ = (selector) => [...document.querySelectorAll(selector)];
const esc = (value = "") => String(value).replace(/[&<>'"]/g, (char) => ({ "&":"&amp;", "<":"&lt;", ">":"&gt;", "'":"&#39;", '"':"&quot;" })[char]);
const formatDate = (value) => new Intl.DateTimeFormat(undefined, { dateStyle: "medium", timeStyle: "short" }).format(new Date(value));

async function api(path, options = {}) {
  const response = await fetch(`/api/v1${path}`, options);
  if (!response.ok) throw new Error((await response.json().catch(() => ({}))).detail || "Atlas could not load dashboard data.");
  return response.json();
}

function selectTab(name) {
  $$(".tab").forEach((tab) => tab.classList.toggle("active", tab.dataset.tab === name));
  $$(".tab-panel").forEach((panel) => panel.classList.toggle("active", panel.id === `tab-${name}`));
}

function renderDecisions(items) {
  $("#decision-count").textContent = `${items.length} shown`;
  $("#decisions").innerHTML = items.length ? items.map((item) => `
    <article class="decision">
      <h2>${esc(item.decision)}</h2>
      <p>${esc(item.reason)}</p>
      <div class="meta">
        <span class="tag">${formatDate(item.created_at)}</span>
        ${item.affected_files.map((file) => `<span class="tag">${esc(file)}</span>`).join("")}
      </div>
      <button class="remove-memory" type="button" data-decision-id="${esc(item.id)}">Remove memory</button>
    </article>`).join("")
    : `<div class="empty compact"><strong>No decisions in this range.</strong><span>Adjust the dates or log the first material decision.</span></div>`;
}

function renderConflicts(items) {
  $("#conflict-count").textContent = `${items.length} caught`;
  $("#conflicts").innerHTML = items.length ? items.map((item) => `
    <article class="conflict">
      <span class="status ${esc(item.status)}">${esc(item.status)}</span>
      <h3>${esc(item.prior_decision || "Prior decision unavailable")}</h3>
      <p>${esc(item.explanation)}</p>
      ${item.override_reason ? `<p class="meta"><span class="tag">Override: ${esc(item.override_reason)}</span></p>` : ""}
      <div class="meta"><span class="tag">${formatDate(item.created_at)}</span></div>
    </article>`).join("")
    : `<div class="empty compact"><strong>No conflicts caught.</strong><span>Contradictions will appear here with the earlier decision and reason.</span></div>`;
}

function renderDesign(items) {
  $("#design-context").innerHTML = items.length ? items.map((item) => `
    <article class="design">
      <pre>${esc(JSON.stringify(item.context, null, 2))}</pre>
      <div class="meta">${item.file_paths.map((path) => `<span class="tag">${esc(path)}</span>`).join("")}</div>
    </article>`).join("")
    : `<div class="empty compact"><strong>No structured design context yet.</strong><span>UI decisions with JSON context appear here.</span></div>`;
}

function renderRunFlow(data) {
  const storage = data.system.storage;
  const dependency = storage === "sqlite"
    ? "No database process to start."
    : "Make sure the configured PostgreSQL database is reachable before opening a fresh Codex task.";
  const storageLabel = storage === "sqlite" ? "SQLite file" : "PostgreSQL database";
  $("#run-flow").innerHTML = `
    <div class="flow-strip">
      <article><strong>1</strong><span>${esc(storageLabel)}</span><p>${esc(dependency)}</p></article>
      <article><strong>2</strong><span>Codex task</span><p>Codex reads this project's .codex/config.toml and starts the Atlas MCP server.</p></article>
      <article><strong>3</strong><span>Atlas MCP</span><p>The MCP server starts the local FastAPI service when an Atlas tool is used.</p></article>
      <article><strong>4</strong><span>Memory tools</span><p>get_context, log_decision, search, conflict override, and memory removal use the same project memory.</p></article>
    </div>
    <dl class="system-list">
      <div><dt>Storage</dt><dd>${esc(data.system.storage)} - ${esc(data.system.storage_detail)}</dd></div>
      <div><dt>Intelligence</dt><dd>${esc(data.system.intelligence)} mode</dd></div>
      <div><dt>Current project</dt><dd>${esc(data.project.name)}</dd></div>
      <div><dt>Visible range</dt><dd>${esc(data.filters.start || "beginning")} to ${esc(data.filters.end || "now")}</dd></div>
    </dl>`;
}

function render(data) {
  $("#content").hidden = false;
  $("#empty").hidden = true;
  $("#summary").textContent = data.project.summary;
  $("#system-state").textContent = `${data.system.storage.toUpperCase()} / ${data.system.intelligence.toUpperCase()} INTELLIGENCE - ${data.system.storage_detail}`;
  $("#fresh-tokens").textContent = data.token_estimate.fresh_session_avoided.toLocaleString();
  $("#focused-tokens").textContent = data.token_estimate.focused_context_budget.toLocaleString();
  $("#focused-detail").textContent = `${data.token_estimate.focused_context_avoided.toLocaleString()} avoided vs. full history`;
  $("#token-method").textContent = data.token_estimate.method;
  renderDecisions(data.decisions);
  renderConflicts(data.conflicts);
  renderDesign(data.design_context);
  renderRunFlow(data);
}

async function refresh() {
  const projectId = $("#project-select").value;
  if (!projectId) return;
  const params = new URLSearchParams({ project_id: projectId });
  if ($("#start-date").value) params.set("start", $("#start-date").value);
  if ($("#end-date").value) params.set("end", $("#end-date").value);
  $("#error").hidden = true;
  try {
    render(await api(`/dashboard?${params}`));
  } catch (error) {
    $("#content").hidden = true;
    $("#error").textContent = error.message;
    $("#error").hidden = false;
  }
}

async function boot() {
  try {
    const data = await api("/projects");
    if (!data.projects.length) {
      $("#empty").innerHTML = "<strong>No Atlas project yet.</strong><span>Use Atlas in Codex once; the first MCP call creates your project.</span>";
      $("#empty").hidden = false;
      return;
    }
    $("#project-select").innerHTML = data.projects.map((project) => `<option value="${esc(project.id)}">${esc(project.name)}</option>`).join("");
    await refresh();
  } catch (error) {
    $("#error").textContent = error.message;
    $("#error").hidden = false;
  }
}

$("#refresh").addEventListener("click", refresh);
$("#project-select").addEventListener("change", refresh);
$(".tabs").addEventListener("click", (event) => {
  const tab = event.target.closest(".tab");
  if (tab) selectTab(tab.dataset.tab);
});

async function removeScope(payload, confirmationPhrase, promptText) {
  const confirmation = prompt(`${promptText}\n\nType ${confirmationPhrase} to continue.`);
  if (confirmation !== confirmationPhrase) return;
  await api("/memory", {
    method: "DELETE",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ project_id: $("#project-select").value, ...payload, confirmation }),
  });
  await refresh();
}

$("#remove-filtered").addEventListener("click", async () => {
  const start = $("#start-date").value;
  const end = $("#end-date").value;
  if (!start || !end) {
    $("#error").textContent = "Choose both UTC date-and-time filters before removing a range.";
    $("#error").hidden = false;
    return;
  }
  try { await removeScope({ start, end }, "REMOVE FILTERED MEMORY", "Remove every memory within this UTC range?"); }
  catch (error) { $("#error").textContent = error.message; $("#error").hidden = false; }
});

$("#remove-project").addEventListener("click", async () => {
  try { await removeScope({ delete_all: true }, "DELETE ALL PROJECT MEMORY", "Permanently remove every memory in this project?"); }
  catch (error) { $("#error").textContent = error.message; $("#error").hidden = false; }
});

$("#decisions").addEventListener("click", async (event) => {
  const button = event.target.closest(".remove-memory");
  if (!button) return;
  if (!confirm("Remove this saved memory and its related UI context/conflict evidence? This cannot be undone.")) return;
  button.disabled = true;
  try {
    await api(`/decisions/${button.dataset.decisionId}`, {
      method: "DELETE",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ project_id: $("#project-select").value }),
    });
    await refresh();
  } catch (error) {
    $("#error").textContent = error.message;
    $("#error").hidden = false;
    button.disabled = false;
  }
});

selectTab("overview");
boot();
