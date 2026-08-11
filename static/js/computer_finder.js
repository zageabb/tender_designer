const computerFinderWorkspace = document.getElementById("computer-finder-workspace");
const computerFinderForm = document.getElementById("computer-finder-form");
const computerFinderConversation = document.getElementById("computer-finder-conversation");
const computerFinderBaseSpec = document.getElementById("computer-finder-base-spec");
const computerFinderInstruction = document.getElementById("computer-finder-instruction");
const computerFinderSettingsForm = document.getElementById("computer-finder-settings-form");
const computerFinderPromptsForm = document.getElementById("computer-finder-prompts-form");
const computerFinderSaveActions = document.getElementById("computer-finder-save-actions");
const computerFinderSaveStatus = document.getElementById("computer-finder-save-status");
const researchMode = document.getElementById("research-mode");
const generalUseAllowedWebsites = document.getElementById("general-use-allowed-websites");
let computerFinderHistory = [];
let latestComputerFinderResult = null;
let activeComputerFinderJobId = null;
let activeComputerFinderSpec = "";
let computerFinderPollTimer = null;
let computerFinderWorkingMessage = null;
let generateSpecAfterSearch = false;

function currentResearchMode() {
  return researchMode?.value === "general" ? "general" : "computer";
}

function researchModeLabel() {
  return currentResearchMode() === "general" ? "General Search" : "Computer Finder";
}

function conversationStorageKey() {
  return `${computerFinderWorkspace.dataset.storageKey}:${currentResearchMode()}`;
}

function updateResearchModeUi() {
  const general = currentResearchMode() === "general";
  document.getElementById("research-page-title").textContent = general ? "General Search" : "Computer Finder";
  document.getElementById("research-page-description").textContent = general
    ? "Research any topic across the web, then refine the sourced answer through follow-up questions."
    : "Research selected tender items, then refine the recommendation with follow-up requirements.";
  document.getElementById("general-domain-toggle-wrap")?.classList.toggle("d-none", !general);
  document.getElementById("research-request-label").textContent = general ? "Research question" : "Starting requirements";
  computerFinderBaseSpec.placeholder = general
    ? "Ask a question or describe the topic, scope, timeframe, and output you need."
    : "Describe the products, quantities, technical requirements, warranty and budget.";
  computerFinderInstruction.placeholder = general
    ? "Example: Focus on UK sources published in the last two years and compare the main viewpoints."
    : "Example: Prioritise models under £900 with a three-year onsite warranty.";
  const submitButton = document.getElementById("computer-finder-submit");
  if (submitButton && !submitButton.disabled) submitButton.textContent = general ? "Search The Web" : "Search Selected Items";
  document.getElementById("computer-finder-spec-auto")?.classList.toggle("d-none", general);
  document.getElementById("computer-finder-spec-download")?.classList.toggle("d-none", general);
  document.getElementById("computer-finder-spec-attach")?.classList.toggle("d-none", general);
}

function renderComputerFinderMarkdown(text) {
  if (typeof renderMarkdown === "function") return renderMarkdown(text);
  return escapeHtml(text).replaceAll("\n", "<br>");
}

function setComputerFinderSaveStatus(message, kind = "muted") {
  if (!computerFinderSaveStatus) return;
  computerFinderSaveStatus.className = `small mt-2 text-${kind}`;
  computerFinderSaveStatus.textContent = message;
}

function appendFinderMessage(role, content, sources = [], steps = []) {
  if (!computerFinderConversation) return;
  const message = document.createElement("article");
  message.className = `finder-message finder-message-${role}`;
  const label = role === "user" ? "You" : researchModeLabel();
  const sourcesMarkup = sources.length
    ? `<div class="computer-finder-sources mt-3"><strong>Sources</strong><ol>${sources
        .map((source, index) => `<li><a href="${escapeHtml(source.url || "#")}" target="_blank" rel="noopener noreferrer">[${index + 1}] ${escapeHtml(source.title || source.url || "Source")}</a></li>`)
        .join("")}</ol></div>`
    : "";
  const stepsMarkup = steps.length
    ? `<details class="mt-3"><summary>Research diagnostics</summary><div class="chat-steps mt-2">${renderComputerFinderMarkdown(steps.map((step) => `- ${step}`).join("\n"))}</div></details>`
    : "";
  message.innerHTML = `<div class="finder-message-label">${label}</div><div class="markdown-rendered">${renderComputerFinderMarkdown(content)}</div>${sourcesMarkup}${stepsMarkup}`;
  computerFinderConversation.appendChild(message);
  computerFinderConversation.scrollTop = computerFinderConversation.scrollHeight;
}

function saveConversationState() {
  if (!computerFinderWorkspace) return;
  const state = {
    baseSpec: computerFinderBaseSpec?.value || "",
    history: computerFinderHistory.slice(-8),
    latest: latestComputerFinderResult,
    activeJobId: activeComputerFinderJobId,
    activeJobSpec: activeComputerFinderSpec,
  };
  sessionStorage.setItem(conversationStorageKey(), JSON.stringify(state));
}

function restoreConversationState() {
  if (!computerFinderWorkspace) return;
  try {
    const raw = sessionStorage.getItem(conversationStorageKey());
    if (!raw) return;
    const state = JSON.parse(raw);
    if (state.baseSpec && computerFinderBaseSpec && !computerFinderBaseSpec.value.trim()) {
      computerFinderBaseSpec.value = state.baseSpec;
    }
    computerFinderHistory = Array.isArray(state.history) ? state.history : [];
    computerFinderHistory.forEach((entry) => appendFinderMessage(entry.role, entry.content, entry.sources || [], []));
    latestComputerFinderResult = state.latest || null;
    activeComputerFinderJobId = state.activeJobId || null;
    activeComputerFinderSpec = state.activeJobSpec || state.baseSpec || "";
    if (latestComputerFinderResult) computerFinderSaveActions?.classList.remove("d-none");
    if (activeComputerFinderJobId) resumeComputerFinderJob(activeComputerFinderJobId);
  } catch (error) {
    sessionStorage.removeItem(conversationStorageKey());
  }
}

async function computerFinderJsonResponse(response) {
  const responseText = await response.text();
  try {
    return responseText ? JSON.parse(responseText) : {};
  } catch (parseError) {
    return { message: responseText || parseError.message };
  }
}

function setComputerFinderRunning(running) {
  const submitButton = document.getElementById("computer-finder-submit");
  const specButton = document.getElementById("computer-finder-spec-auto");
  if (!submitButton) return;
  if (specButton) specButton.disabled = running;
  if (running) {
    submitButton.disabled = true;
    submitButton.dataset.originalText ||= submitButton.textContent;
    submitButton.textContent = "Researching...";
  } else {
    submitButton.disabled = false;
    submitButton.textContent = currentResearchMode() === "general" ? "Search The Web" : "Search Selected Items";
  }
}

function renderComputerFinderRuntime(job) {
  const events = Array.isArray(job.events) ? job.events : [];
  const siteEvents = events.filter((event) => event.kind === "site");
  const latestBySite = new Map();
  siteEvents.forEach((event) => latestBySite.set(event.url || event.label, event));
  const siteStates = Array.from(latestBySite.values());
  document.getElementById("computer-finder-runtime-phase").textContent = job.phase || "Working";
  document.getElementById("computer-finder-count-initiated").textContent = String(
    siteStates.length || events.filter((event) => event.status === "initiated").length
  );
  document.getElementById("computer-finder-count-returned").textContent = String(
    siteStates.filter((event) => event.status === "returned").length
  );
  document.getElementById("computer-finder-count-failed").textContent = String(
    siteStates.filter((event) => ["failed", "unreadable"].includes(event.status)).length
  );
  const started = job.started_at ? new Date(job.started_at).getTime() : Date.now();
  const ended = job.completed_at ? new Date(job.completed_at).getTime() : Date.now();
  const elapsedSeconds = Math.max(0, Math.floor((ended - started) / 1000));
  document.getElementById("computer-finder-runtime-elapsed").textContent =
    `${Math.floor(elapsedSeconds / 60)}:${String(elapsedSeconds % 60).padStart(2, "0")}`;
  const eventsRoot = document.getElementById("computer-finder-runtime-events");
  if (!eventsRoot) return;
  if (!events.length) {
    eventsRoot.innerHTML = '<p class="small text-muted mb-0">Waiting for the first runtime event…</p>';
    return;
  }
  eventsRoot.innerHTML = events.slice(-80).reverse().map((event) => {
    const label = escapeHtml(event.label || "Research activity");
    const detail = event.detail ? `<small>${escapeHtml(event.detail)}</small>` : "";
    const eventType = event.kind === "reasoning" ? '<span class="computer-finder-runtime-kind">Reasoning summary</span>' : "";
    const linkedLabel = event.url
      ? `<a href="${escapeHtml(event.url)}" target="_blank" rel="noopener noreferrer">${label}</a>`
      : label;
    return `<div class="computer-finder-runtime-event kind-${escapeHtml(event.kind)} status-${escapeHtml(event.status)}">
      <span class="computer-finder-runtime-dot"></span>
      <div>${eventType}<strong>${linkedLabel}</strong>${detail}</div>
      <span class="computer-finder-runtime-status">${escapeHtml(event.status)}</span>
    </div>`;
  }).join("");
}

function finishComputerFinderJob(job) {
  clearTimeout(computerFinderPollTimer);
  computerFinderPollTimer = null;
  computerFinderWorkingMessage?.remove();
  computerFinderWorkingMessage = null;
  activeComputerFinderJobId = null;
  setComputerFinderRunning(false);
  if (job.status === "completed") {
    const answer = job.message || "";
    appendFinderMessage("assistant", answer, job.sources || [], job.steps || []);
    computerFinderHistory.push({ role: "assistant", content: answer, sources: job.sources || [] });
    latestComputerFinderResult = {
      spec: activeComputerFinderSpec || computerFinderBaseSpec?.value || "",
      message: answer,
      sources: job.sources || [],
      mode: currentResearchMode(),
    };
    computerFinderSaveActions?.classList.remove("d-none");
    setComputerFinderSaveStatus("");
    if (generateSpecAfterSearch) {
      generateSpecAfterSearch = false;
      downloadSpecificationSheet();
    }
  } else {
    generateSpecAfterSearch = false;
    const message = `Search could not be completed: ${job.error || "Unknown error"}`;
    appendFinderMessage("assistant", message, [], job.steps || []);
    computerFinderHistory.push({ role: "assistant", content: message });
  }
  saveConversationState();
}

async function pollComputerFinderJob(jobId) {
  try {
    const statusUrl = computerFinderWorkspace.dataset.searchStatusUrl.replace("JOB_ID", encodeURIComponent(jobId));
    const response = await fetch(statusUrl);
    const payload = await computerFinderJsonResponse(response);
    if (!response.ok || !payload.ok) throw new Error(payload.message || "Could not read search progress.");
    const job = payload.job;
    renderComputerFinderRuntime(job);
    if (["completed", "failed"].includes(job.status)) {
      finishComputerFinderJob(job);
      return;
    }
    computerFinderPollTimer = setTimeout(() => pollComputerFinderJob(jobId), 1000);
  } catch (error) {
    document.getElementById("computer-finder-runtime-phase").textContent = `Progress unavailable: ${error.message}`;
    computerFinderPollTimer = setTimeout(() => pollComputerFinderJob(jobId), 2500);
  }
}

function resumeComputerFinderJob(jobId) {
  setComputerFinderRunning(true);
  if (!computerFinderWorkingMessage) {
    computerFinderWorkingMessage = document.createElement("div");
    computerFinderWorkingMessage.className = "finder-message finder-message-assistant finder-message-working";
    computerFinderWorkingMessage.innerHTML = `<div class="finder-message-label">${researchModeLabel()}</div><div>Research continues in the background. Live activity is shown on the right.</div>`;
    computerFinderConversation.appendChild(computerFinderWorkingMessage);
  }
  pollComputerFinderJob(jobId);
}

computerFinderForm?.addEventListener("submit", async (event) => {
  event.preventDefault();
  const submitButton = document.getElementById("computer-finder-submit");
  const baseSpec = computerFinderBaseSpec?.value.trim() || "";
  const instruction = computerFinderInstruction?.value.trim() || "";
  if (!baseSpec) {
    appendFinderMessage("assistant", currentResearchMode() === "general" ? "Enter a research question before searching." : "Add starting requirements or select tender items before searching.");
    return;
  }
  const userMessage = instruction || (computerFinderHistory.length
    ? "Search again using the current request."
    : currentResearchMode() === "general" ? "Research this question." : "Find the best matching products for these requirements.");
  appendFinderMessage("user", userMessage);
  const requestHistory = computerFinderHistory.slice(-6);
  computerFinderHistory.push({ role: "user", content: userMessage });
  computerFinderInstruction.value = "";
  setComputerFinderRunning(true);
  try {
    const response = await fetch(computerFinderWorkspace.dataset.searchUrl, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        base_spec: baseSpec,
        instruction: userMessage,
        history: requestHistory,
        mode: currentResearchMode(),
        use_allowed_websites: Boolean(generalUseAllowedWebsites?.checked),
      }),
    });
    const payload = await computerFinderJsonResponse(response);
    if (!response.ok || !payload.ok) throw new Error(payload.message || "Computer search failed.");
    activeComputerFinderJobId = payload.job.id;
    activeComputerFinderSpec = `${baseSpec}\n\nLatest refinement: ${userMessage}`;
    saveConversationState();
    resumeComputerFinderJob(activeComputerFinderJobId);
  } catch (error) {
    appendFinderMessage("assistant", `Search could not be completed: ${error.message}`);
    computerFinderHistory.push({ role: "assistant", content: `Search failed: ${error.message}` });
    saveConversationState();
    setComputerFinderRunning(false);
  }
});

document.getElementById("computer-finder-spec-auto")?.addEventListener("click", () => {
  if (currentResearchMode() !== "computer") {
    setComputerFinderSaveStatus("Switch to Computer Finder to generate a machine specification.", "warning");
    return;
  }
  if (!computerFinderBaseSpec?.value.trim()) {
    appendFinderMessage("assistant", "Add starting requirements or select tender items before generating a specification.");
    return;
  }
  generateSpecAfterSearch = true;
  computerFinderInstruction.value = "Find one exact best-fit product and collect comprehensive manufacturer-backed technical data for a machine specification sheet: model, processor, memory, storage, graphics, physical format, dimensions, weight, security, networking, ports, expansion, included peripherals, software, warranty, compliance, identifiers, and official product/datasheet/support sources. Do not include any price or cost information.";
  computerFinderForm.requestSubmit();
});

document.getElementById("computer-finder-clear")?.addEventListener("click", () => {
  computerFinderHistory = [];
  latestComputerFinderResult = null;
  generateSpecAfterSearch = false;
  activeComputerFinderJobId = null;
  activeComputerFinderSpec = "";
  clearTimeout(computerFinderPollTimer);
  computerFinderPollTimer = null;
  computerFinderWorkingMessage = null;
  computerFinderInstruction.value = "";
  computerFinderConversation.innerHTML = "";
  appendFinderMessage("assistant", "Conversation cleared. Update the starting requirements if needed, then begin a new search.");
  computerFinderSaveActions?.classList.add("d-none");
  setComputerFinderSaveStatus("");
  document.getElementById("computer-finder-runtime-phase").textContent = "Ready";
  document.getElementById("computer-finder-runtime-elapsed").textContent = "0:00";
  document.getElementById("computer-finder-runtime-events").innerHTML =
    '<p class="small text-muted mb-0">Runtime events will appear here when a search starts.</p>';
  ["initiated", "returned", "failed"].forEach((status) => {
    document.getElementById(`computer-finder-count-${status}`).textContent = "0";
  });
  setComputerFinderRunning(false);
  sessionStorage.removeItem(conversationStorageKey());
});

researchMode?.addEventListener("change", () => {
  clearTimeout(computerFinderPollTimer);
  computerFinderPollTimer = null;
  computerFinderHistory = [];
  latestComputerFinderResult = null;
  generateSpecAfterSearch = false;
  activeComputerFinderJobId = null;
  activeComputerFinderSpec = "";
  computerFinderWorkingMessage = null;
  computerFinderBaseSpec.value = "";
  computerFinderInstruction.value = "";
  computerFinderConversation.innerHTML = "";
  updateResearchModeUi();
  appendFinderMessage("assistant", currentResearchMode() === "general"
    ? "Ask any research question. I’ll search the web, read relevant sources, and produce a cited answer you can refine."
    : "Tell me what matters most, or start the search using the selected tender requirements.");
  computerFinderSaveActions?.classList.add("d-none");
  restoreConversationState();
});

document.getElementById("computer-finder-download")?.addEventListener("click", async () => {
  if (!latestComputerFinderResult || !computerFinderSaveActions) return;
  setComputerFinderSaveStatus("Preparing download...");
  try {
    const response = await fetch(computerFinderSaveActions.dataset.exportUrl, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(latestComputerFinderResult),
    });
    if (!response.ok) {
      const result = await computerFinderJsonResponse(response);
      throw new Error(result.message || "Could not export the result.");
    }
    const blob = await response.blob();
    const disposition = response.headers.get("Content-Disposition") || "";
    const filenameMatch = disposition.match(/filename="?([^";]+)"?/i);
    const downloadUrl = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = downloadUrl;
    link.download = filenameMatch?.[1] || "computer_finder_result.md";
    document.body.appendChild(link);
    link.click();
    link.remove();
    URL.revokeObjectURL(downloadUrl);
    setComputerFinderSaveStatus("Result downloaded.", "success");
  } catch (error) {
    setComputerFinderSaveStatus(error.message, "danger");
  }
});

async function downloadSpecificationSheet() {
  if (!latestComputerFinderResult || !computerFinderSaveActions) return;
  setComputerFinderSaveStatus("Building specification sheet from sourced research...");
  const button = document.getElementById("computer-finder-spec-download");
  if (button) button.disabled = true;
  try {
    const response = await fetch(computerFinderSaveActions.dataset.specExportUrl, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(latestComputerFinderResult),
    });
    if (!response.ok) {
      const result = await computerFinderJsonResponse(response);
      throw new Error(result.message || "Could not generate the specification sheet.");
    }
    const blob = await response.blob();
    const disposition = response.headers.get("Content-Disposition") || "";
    const filenameMatch = disposition.match(/filename="?([^";]+)"?/i);
    const downloadUrl = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = downloadUrl;
    link.download = filenameMatch?.[1] || "Machine_Specification.docx";
    document.body.appendChild(link);
    link.click();
    link.remove();
    URL.revokeObjectURL(downloadUrl);
    setComputerFinderSaveStatus("Specification sheet generated. Pricing was excluded.", "success");
  } catch (error) {
    setComputerFinderSaveStatus(error.message, "danger");
  } finally {
    if (button) button.disabled = false;
  }
}

document.getElementById("computer-finder-spec-download")?.addEventListener("click", downloadSpecificationSheet);

document.getElementById("computer-finder-attach")?.addEventListener("click", async () => {
  if (!latestComputerFinderResult || !computerFinderSaveActions) return;
  const tenderId = document.getElementById("computer-finder-tender")?.value;
  const attachButton = document.getElementById("computer-finder-attach");
  if (!tenderId) {
    setComputerFinderSaveStatus("Choose a tender first.", "warning");
    return;
  }
  attachButton.disabled = true;
  setComputerFinderSaveStatus("Saving result to tender...");
  try {
    const response = await fetch(computerFinderSaveActions.dataset.attachUrl, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ ...latestComputerFinderResult, tender_id: tenderId }),
    });
    const result = await computerFinderJsonResponse(response);
    if (!response.ok || !result.ok) throw new Error(result.message || "Could not save the result to the tender.");
    setComputerFinderSaveStatus(result.message || "Result saved to tender.", "success");
    if (result.tender_url) {
      computerFinderSaveStatus.append(" ");
      const tenderLink = document.createElement("a");
      tenderLink.href = result.tender_url;
      tenderLink.textContent = "Open tender";
      computerFinderSaveStatus.appendChild(tenderLink);
    }
  } catch (error) {
    setComputerFinderSaveStatus(error.message, "danger");
  } finally {
    attachButton.disabled = false;
  }
});

document.getElementById("computer-finder-spec-attach")?.addEventListener("click", async () => {
  if (!latestComputerFinderResult || !computerFinderSaveActions) return;
  const tenderId = document.getElementById("computer-finder-tender")?.value;
  const button = document.getElementById("computer-finder-spec-attach");
  if (!tenderId) {
    setComputerFinderSaveStatus("Choose a tender first.", "warning");
    return;
  }
  button.disabled = true;
  setComputerFinderSaveStatus("Generating and adding specification sheet to tender...");
  try {
    const response = await fetch(computerFinderSaveActions.dataset.specAttachUrl, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ ...latestComputerFinderResult, tender_id: tenderId }),
    });
    const result = await computerFinderJsonResponse(response);
    if (!response.ok || !result.ok) throw new Error(result.message || "Could not add the specification sheet.");
    setComputerFinderSaveStatus(result.message, "success");
    if (result.tender_url) {
      computerFinderSaveStatus.append(" ");
      const link = document.createElement("a");
      link.href = result.tender_url;
      link.textContent = "Open tender";
      computerFinderSaveStatus.appendChild(link);
    }
  } catch (error) {
    setComputerFinderSaveStatus(error.message, "danger");
  } finally {
    button.disabled = false;
  }
});

computerFinderSettingsForm?.addEventListener("submit", async (event) => {
  event.preventDefault();
  const submitButton = document.getElementById("computer-finder-settings-submit");
  const payload = Object.fromEntries(new FormData(computerFinderSettingsForm).entries());
  submitButton.disabled = true;
  try {
    const response = await fetch(computerFinderSettingsForm.dataset.settingsUrl, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    const result = await computerFinderJsonResponse(response);
    if (!response.ok || !result.ok) throw new Error(result.message || "Could not save settings.");
    document.getElementById("computer-finder-domain-summary").textContent = `Saved. Active: ${result.allowed_domains.length} allowed, ${result.blocked_domains.length} blocked.`;
  } catch (error) {
    document.getElementById("computer-finder-domain-summary").textContent = error.message;
  } finally {
    submitButton.disabled = false;
  }
});

computerFinderPromptsForm?.addEventListener("submit", async (event) => {
  event.preventDefault();
  const submitButton = document.getElementById("computer-finder-prompts-submit");
  const status = document.getElementById("computer-finder-prompts-status");
  const prompts = Object.fromEntries(new FormData(computerFinderPromptsForm).entries());
  submitButton.disabled = true;
  status.className = "small text-muted ms-2";
  status.textContent = "Saving...";
  try {
    const response = await fetch(computerFinderPromptsForm.dataset.promptsUrl, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ prompts }),
    });
    const result = await computerFinderJsonResponse(response);
    if (!response.ok || !result.ok) throw new Error(result.message || "Could not save Finder instructions.");
    status.className = "small text-success ms-2";
    status.textContent = result.message;
  } catch (error) {
    status.className = "small text-danger ms-2";
    status.textContent = error.message;
  } finally {
    submitButton.disabled = false;
  }
});

updateResearchModeUi();
restoreConversationState();
