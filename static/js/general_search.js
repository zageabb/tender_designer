const researchWorkspace = document.getElementById("computer-finder-workspace");
const researchConversation = document.getElementById("computer-finder-conversation");
const researchForm = document.getElementById("computer-finder-form");
const researchInput = document.getElementById("computer-finder-instruction");
const researchModel = document.getElementById("research-model");
const researchAllowedOnly = document.getElementById("general-use-allowed-websites");
const researchHistoryList = document.getElementById("research-history-list");
const researchSaveActions = document.getElementById("computer-finder-save-actions");
const researchSaveStatus = document.getElementById("computer-finder-save-status");
const researchSettingsForm = document.getElementById("computer-finder-settings-form");
const researchPromptsForm = document.getElementById("computer-finder-prompts-form");

let researchChats = [];
let activeResearchChatId = null;
const researchPollTimers = new Map();

function researchId() {
  return `research-${Date.now()}-${Math.random().toString(16).slice(2)}`;
}

function activeResearchChat() {
  return researchChats.find((chat) => chat.id === activeResearchChatId) || null;
}

function newResearchChat(initialQuery = "") {
  const now = new Date().toISOString();
  const chat = {
    id: researchId(),
    title: initialQuery ? initialQuery.slice(0, 52) : "New research",
    createdAt: now,
    updatedAt: now,
    model: researchWorkspace.dataset.defaultModel || "",
    useAllowedWebsites: false,
    messages: [],
    latest: null,
    activeJobId: null,
  };
  researchChats.unshift(chat);
  activeResearchChatId = chat.id;
  saveResearchChats();
  renderResearchWorkspace();
  if (initialQuery) researchInput.value = initialQuery;
  researchInput.focus();
  return chat;
}

function saveResearchChats() {
  try {
    localStorage.setItem(researchWorkspace.dataset.storageKey, JSON.stringify({
      activeId: activeResearchChatId,
      chats: researchChats.slice(0, 40),
    }));
  } catch (_error) {
    researchChats = researchChats.slice(0, 20);
    localStorage.setItem(researchWorkspace.dataset.storageKey, JSON.stringify({ activeId: activeResearchChatId, chats: researchChats }));
  }
}

function loadResearchChats() {
  try {
    const stored = JSON.parse(localStorage.getItem(researchWorkspace.dataset.storageKey) || "{}");
    researchChats = Array.isArray(stored.chats) ? stored.chats : [];
    activeResearchChatId = stored.activeId || researchChats[0]?.id || null;
  } catch (_error) {
    researchChats = [];
  }
  if (!activeResearchChat()) newResearchChat(researchWorkspace.dataset.initialQuery || "");
}

function renderResearchHistory() {
  researchHistoryList.innerHTML = researchChats.map((chat) => `
    <div class="research-history-item${chat.id === activeResearchChatId ? " active" : ""}">
      <button type="button" class="research-history-open" data-chat-id="${escapeHtml(chat.id)}">
        <strong>${escapeHtml(chat.title || "New research")}</strong>
        <span>${chat.messages?.length || 0} messages</span>
      </button>
      <button type="button" class="research-history-delete" data-delete-chat-id="${escapeHtml(chat.id)}" aria-label="Delete conversation">×</button>
    </div>
  `).join("");
}

function researchMessageMarkup(message) {
  const sources = Array.isArray(message.sources) && message.sources.length
    ? `<div class="computer-finder-sources mt-3"><strong>Sources</strong><ol>${message.sources.map((source, index) =>
        `<li><a href="${escapeHtml(source.url || "#")}" target="_blank" rel="noopener noreferrer">[${index + 1}] ${escapeHtml(source.title || source.url || "Source")}</a></li>`
      ).join("")}</ol></div>`
    : "";
  const diagnostics = Array.isArray(message.steps) && message.steps.length
    ? `<details class="mt-3"><summary>Research diagnostics</summary><div class="chat-steps mt-2">${renderMarkdown(message.steps.map((step) => `- ${step}`).join("\n"))}</div></details>`
    : "";
  return `<article class="finder-message finder-message-${message.role}">
    <div class="finder-message-label">${message.role === "user" ? "You" : "General Search"}</div>
    <div class="markdown-rendered">${renderMarkdown(message.content || "")}</div>${sources}${diagnostics}
  </article>`;
}

function renderResearchConversation() {
  const chat = activeResearchChat();
  if (!chat) return;
  document.getElementById("research-active-title").textContent = chat.title || "New research";
  researchModel.value = chat.model || researchWorkspace.dataset.defaultModel || "";
  researchAllowedOnly.checked = Boolean(chat.useAllowedWebsites);
  const messages = Array.isArray(chat.messages) ? chat.messages : [];
  researchConversation.innerHTML = messages.length
    ? messages.map(researchMessageMarkup).join("")
    : `<div class="research-empty-state"><span class="brand-mark">GS</span><h2>What would you like to research?</h2><p>Ask a question, compare options, investigate a topic, or request a sourced table.</p></div>`;
  document.getElementById("research-context-summary").textContent = `${messages.length} message${messages.length === 1 ? "" : "s"} in context`;
  researchSaveActions.classList.toggle("d-none", !chat.latest);
  researchConversation.scrollTop = researchConversation.scrollHeight;
}

function renderResearchWorkspace() {
  renderResearchHistory();
  renderResearchConversation();
}

function setResearchRunning(running, chatId = activeResearchChatId) {
  if (chatId !== activeResearchChatId) return;
  const button = document.getElementById("computer-finder-submit");
  button.disabled = running;
  button.textContent = running ? "Researching…" : "Search";
}

function renderResearchRuntime(job, chatId) {
  if (chatId !== activeResearchChatId) return;
  const events = Array.isArray(job.events) ? job.events : [];
  const sites = new Map();
  events.filter((event) => event.kind === "site").forEach((event) => sites.set(event.url || event.label, event));
  const states = Array.from(sites.values());
  const returned = states.filter((event) => event.status === "returned").length;
  const failed = states.filter((event) => ["failed", "unreadable"].includes(event.status)).length;
  document.getElementById("computer-finder-runtime-phase").textContent = job.phase || "Working";
  document.getElementById("computer-finder-count-initiated").textContent = String(states.length);
  document.getElementById("computer-finder-count-returned").textContent = String(returned);
  document.getElementById("computer-finder-count-failed").textContent = String(failed);
  const started = job.started_at ? new Date(job.started_at).getTime() : Date.now();
  const ended = job.completed_at ? new Date(job.completed_at).getTime() : Date.now();
  const seconds = Math.max(0, Math.floor((ended - started) / 1000));
  document.getElementById("computer-finder-runtime-elapsed").textContent = `${Math.floor(seconds / 60)}:${String(seconds % 60).padStart(2, "0")}`;
  document.getElementById("computer-finder-runtime-events").innerHTML = events.length
    ? events.slice(-80).reverse().map((event) => `<div class="computer-finder-runtime-event kind-${escapeHtml(event.kind)} status-${escapeHtml(event.status)}"><span class="computer-finder-runtime-dot"></span><div><strong>${event.url ? `<a href="${escapeHtml(event.url)}" target="_blank" rel="noopener noreferrer">${escapeHtml(event.label)}</a>` : escapeHtml(event.label)}</strong>${event.detail ? `<small>${escapeHtml(event.detail)}</small>` : ""}</div><span class="computer-finder-runtime-status">${escapeHtml(event.status)}</span></div>`).join("")
    : '<p class="small text-muted mb-0">Waiting for research activity…</p>';
}

async function researchJson(response) {
  const text = await response.text();
  try { return text ? JSON.parse(text) : {}; } catch (_error) { return { message: text }; }
}

async function pollResearchJob(jobId, chatId) {
  try {
    const response = await fetch(researchWorkspace.dataset.searchStatusUrl.replace("JOB_ID", encodeURIComponent(jobId)));
    const payload = await researchJson(response);
    if (!response.ok || !payload.ok) throw new Error(payload.message || "Could not read search progress.");
    const job = payload.job;
    renderResearchRuntime(job, chatId);
    if (["completed", "failed"].includes(job.status)) {
      researchPollTimers.delete(chatId);
      const chat = researchChats.find((item) => item.id === chatId);
      if (!chat) return;
      chat.activeJobId = null;
      const content = job.status === "completed" ? job.message || "" : `Search could not be completed: ${job.error || "Unknown error"}`;
      chat.messages.push({ role: "assistant", content, sources: job.sources || [], steps: job.steps || [] });
      if (job.status === "completed") chat.latest = { spec: chat.messages.filter((item) => item.role === "user").map((item) => item.content).join("\n\n"), message: content, sources: job.sources || [], mode: "general" };
      chat.updatedAt = new Date().toISOString();
      saveResearchChats();
      renderResearchWorkspace();
      setResearchRunning(false, chatId);
      return;
    }
    researchPollTimers.set(chatId, setTimeout(() => pollResearchJob(jobId, chatId), 1000));
  } catch (error) {
    if (chatId === activeResearchChatId) document.getElementById("computer-finder-runtime-phase").textContent = `Progress unavailable: ${error.message}`;
    researchPollTimers.set(chatId, setTimeout(() => pollResearchJob(jobId, chatId), 2500));
  }
}

researchForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  const query = researchInput.value.trim();
  const chat = activeResearchChat();
  if (!query || !chat || chat.activeJobId) return;
  const history = chat.messages.map(({ role, content }) => ({ role, content }));
  chat.messages.push({ role: "user", content: query });
  if (chat.messages.length === 1) chat.title = query.slice(0, 52);
  chat.model = researchModel.value;
  chat.useAllowedWebsites = researchAllowedOnly.checked;
  chat.updatedAt = new Date().toISOString();
  researchInput.value = "";
  saveResearchChats();
  renderResearchWorkspace();
  setResearchRunning(true);
  try {
    const response = await fetch(researchWorkspace.dataset.searchUrl, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ base_spec: query, history, mode: "general", use_allowed_websites: chat.useAllowedWebsites, model: chat.model }),
    });
    const payload = await researchJson(response);
    if (!response.ok || !payload.ok) throw new Error(payload.message || "Search could not be started.");
    chat.activeJobId = payload.job.id;
    saveResearchChats();
    pollResearchJob(chat.activeJobId, chat.id);
  } catch (error) {
    chat.messages.push({ role: "assistant", content: `Search could not be completed: ${error.message}` });
    saveResearchChats();
    renderResearchWorkspace();
    setResearchRunning(false);
  }
});

researchHistoryList.addEventListener("click", (event) => {
  const open = event.target.closest("[data-chat-id]");
  const remove = event.target.closest("[data-delete-chat-id]");
  if (open) activeResearchChatId = open.dataset.chatId;
  if (remove) {
    const id = remove.dataset.deleteChatId;
    clearTimeout(researchPollTimers.get(id));
    researchPollTimers.delete(id);
    researchChats = researchChats.filter((chat) => chat.id !== id);
    if (activeResearchChatId === id) activeResearchChatId = researchChats[0]?.id || null;
    if (!activeResearchChat()) return newResearchChat();
  }
  saveResearchChats();
  renderResearchWorkspace();
  setResearchRunning(Boolean(activeResearchChat()?.activeJobId));
});

document.getElementById("research-new-chat").addEventListener("click", () => newResearchChat());
researchModel.addEventListener("change", () => { const chat = activeResearchChat(); if (chat) { chat.model = researchModel.value; saveResearchChats(); } });
researchAllowedOnly.addEventListener("change", () => { const chat = activeResearchChat(); if (chat) { chat.useAllowedWebsites = researchAllowedOnly.checked; saveResearchChats(); } });

async function loadResearchModels() {
  try {
    const response = await fetch(researchWorkspace.dataset.modelsUrl);
    const payload = await researchJson(response);
    if (!payload.ok || !payload.models?.length) return;
    const selected = activeResearchChat()?.model || researchWorkspace.dataset.defaultModel;
    researchModel.innerHTML = payload.models.map((model) => `<option value="${escapeHtml(model)}">${escapeHtml(model)}</option>`).join("");
    if (payload.models.includes(selected)) researchModel.value = selected;
  } catch (_error) { /* Keep configured fallback model. */ }
}

document.getElementById("computer-finder-download")?.addEventListener("click", async () => {
  const latest = activeResearchChat()?.latest;
  if (!latest) return;
  const response = await fetch(researchSaveActions.dataset.exportUrl, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(latest) });
  if (!response.ok) return;
  const blob = await response.blob();
  const link = document.createElement("a");
  link.href = URL.createObjectURL(blob);
  link.download = "general_search_result.md";
  link.click();
  URL.revokeObjectURL(link.href);
});

document.getElementById("computer-finder-attach")?.addEventListener("click", async () => {
  const latest = activeResearchChat()?.latest;
  const tenderId = document.getElementById("computer-finder-tender")?.value;
  if (!latest || !tenderId) return;
  const response = await fetch(researchSaveActions.dataset.attachUrl, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ ...latest, tender_id: tenderId }) });
  const payload = await researchJson(response);
  researchSaveStatus.textContent = payload.message || (response.ok ? "Saved." : "Could not save result.");
  researchSaveStatus.className = `small mt-2 text-${response.ok ? "success" : "danger"}`;
});

researchSettingsForm?.addEventListener("submit", async (event) => {
  event.preventDefault();
  const button = document.getElementById("computer-finder-settings-submit");
  button.disabled = true;
  const response = await fetch(researchSettingsForm.dataset.settingsUrl, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(Object.fromEntries(new FormData(researchSettingsForm).entries())) });
  const payload = await researchJson(response);
  document.getElementById("computer-finder-domain-summary").textContent = payload.message || "Settings saved.";
  button.disabled = false;
});

researchPromptsForm?.addEventListener("submit", async (event) => {
  event.preventDefault();
  const status = document.getElementById("computer-finder-prompts-status");
  const response = await fetch(researchPromptsForm.dataset.promptsUrl, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ prompts: Object.fromEntries(new FormData(researchPromptsForm).entries()) }) });
  const payload = await researchJson(response);
  status.textContent = payload.message || "Search instructions saved.";
  status.className = `small ms-2 text-${response.ok ? "success" : "danger"}`;
});

loadResearchChats();
renderResearchWorkspace();
loadResearchModels();
researchChats.filter((chat) => chat.activeJobId).forEach((chat) => pollResearchJob(chat.activeJobId, chat.id));
