const computerFinderWorkspace = document.getElementById("computer-finder-workspace");
const computerFinderForm = document.getElementById("computer-finder-form");
const computerFinderConversation = document.getElementById("computer-finder-conversation");
const computerFinderBaseSpec = document.getElementById("computer-finder-base-spec");
const computerFinderInstruction = document.getElementById("computer-finder-instruction");
const computerFinderSettingsForm = document.getElementById("computer-finder-settings-form");
const computerFinderSaveActions = document.getElementById("computer-finder-save-actions");
const computerFinderSaveStatus = document.getElementById("computer-finder-save-status");
let computerFinderHistory = [];
let latestComputerFinderResult = null;

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
  const label = role === "user" ? "You" : "Computer Finder";
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
  };
  sessionStorage.setItem(computerFinderWorkspace.dataset.storageKey, JSON.stringify(state));
}

function restoreConversationState() {
  if (!computerFinderWorkspace) return;
  try {
    const raw = sessionStorage.getItem(computerFinderWorkspace.dataset.storageKey);
    if (!raw) return;
    const state = JSON.parse(raw);
    if (state.baseSpec && computerFinderBaseSpec && !computerFinderBaseSpec.value.trim()) {
      computerFinderBaseSpec.value = state.baseSpec;
    }
    computerFinderHistory = Array.isArray(state.history) ? state.history : [];
    computerFinderHistory.forEach((entry) => appendFinderMessage(entry.role, entry.content, entry.sources || [], []));
    latestComputerFinderResult = state.latest || null;
    if (latestComputerFinderResult) computerFinderSaveActions?.classList.remove("d-none");
  } catch (error) {
    sessionStorage.removeItem(computerFinderWorkspace.dataset.storageKey);
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

computerFinderForm?.addEventListener("submit", async (event) => {
  event.preventDefault();
  const submitButton = document.getElementById("computer-finder-submit");
  const baseSpec = computerFinderBaseSpec?.value.trim() || "";
  const instruction = computerFinderInstruction?.value.trim() || "";
  if (!baseSpec) {
    appendFinderMessage("assistant", "Add starting requirements or select tender items before searching.");
    return;
  }
  const userMessage = instruction || (computerFinderHistory.length ? "Search again using the current requirements." : "Find the best matching products for these requirements.");
  appendFinderMessage("user", userMessage);
  const requestHistory = computerFinderHistory.slice(-6);
  computerFinderHistory.push({ role: "user", content: userMessage });
  computerFinderInstruction.value = "";
  submitButton.disabled = true;
  submitButton.dataset.originalText = submitButton.textContent;
  submitButton.textContent = "Researching...";
  const workingMessage = document.createElement("div");
  workingMessage.className = "finder-message finder-message-assistant finder-message-working";
  workingMessage.innerHTML = '<div class="finder-message-label">Computer Finder</div><div>Searching the web, reading product pages and comparing evidence…</div>';
  computerFinderConversation.appendChild(workingMessage);
  try {
    const response = await fetch(computerFinderWorkspace.dataset.searchUrl, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ base_spec: baseSpec, instruction: userMessage, history: requestHistory }),
    });
    const payload = await computerFinderJsonResponse(response);
    workingMessage.remove();
    if (!response.ok || !payload.ok) throw new Error(payload.message || "Computer search failed.");
    const answer = payload.message || "";
    appendFinderMessage("assistant", answer, payload.sources || [], payload.steps || []);
    computerFinderHistory.push({ role: "assistant", content: answer, sources: payload.sources || [] });
    latestComputerFinderResult = {
      spec: `${baseSpec}\n\nLatest refinement: ${userMessage}`,
      message: answer,
      sources: payload.sources || [],
    };
    computerFinderSaveActions?.classList.remove("d-none");
    setComputerFinderSaveStatus("");
    saveConversationState();
  } catch (error) {
    workingMessage.remove();
    appendFinderMessage("assistant", `Search could not be completed: ${error.message}`);
    computerFinderHistory.push({ role: "assistant", content: `Search failed: ${error.message}` });
    saveConversationState();
  } finally {
    submitButton.disabled = false;
    submitButton.textContent = submitButton.dataset.originalText || "Search Selected Items";
  }
});

document.getElementById("computer-finder-clear")?.addEventListener("click", () => {
  computerFinderHistory = [];
  latestComputerFinderResult = null;
  computerFinderInstruction.value = "";
  computerFinderConversation.innerHTML = "";
  appendFinderMessage("assistant", "Conversation cleared. Update the starting requirements if needed, then begin a new search.");
  computerFinderSaveActions?.classList.add("d-none");
  setComputerFinderSaveStatus("");
  sessionStorage.removeItem(computerFinderWorkspace.dataset.storageKey);
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

restoreConversationState();
