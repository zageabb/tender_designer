const computerFinderForm = document.getElementById("computer-finder-form");
const computerFinderSettingsForm = document.getElementById("computer-finder-settings-form");
const computerFinderStatus = document.getElementById("computer-finder-status");
const computerFinderResult = document.getElementById("computer-finder-result");
const computerFinderSources = document.getElementById("computer-finder-sources");
const computerFinderSteps = document.getElementById("computer-finder-steps");
const computerFinderClear = document.getElementById("computer-finder-clear");
const computerFinderSaveActions = document.getElementById("computer-finder-save-actions");
const computerFinderSaveStatus = document.getElementById("computer-finder-save-status");
let latestComputerFinderResult = null;

function setComputerFinderStatus(message, kind = "secondary") {
  if (!computerFinderStatus) return;
  computerFinderStatus.className = `alert alert-${kind} mb-3`;
  computerFinderStatus.textContent = message;
}

function renderComputerFinderMarkdown(text) {
  if (typeof renderMarkdown === "function") {
    return renderMarkdown(text);
  }
  return escapeHtml(text).replaceAll("\n", "<br>");
}

function renderComputerFinderSources(sources) {
  if (!computerFinderSources) return;
  if (!sources?.length) {
    computerFinderSources.innerHTML = "";
    return;
  }
  const items = sources
    .map((source, index) => {
      const title = escapeHtml(source.title || source.url || `Source ${index + 1}`);
      const url = escapeHtml(source.url || "#");
      return `<li><a href="${url}" target="_blank" rel="noopener noreferrer">[${index + 1}] ${title}</a></li>`;
    })
    .join("");
  computerFinderSources.innerHTML = `<h3 class="h6 mt-4">Source Links</h3><ol>${items}</ol>`;
}

function renderComputerFinderSteps(steps) {
  if (!computerFinderSteps) return;
  if (!steps?.length) {
    computerFinderSteps.classList.add("d-none");
    computerFinderSteps.innerHTML = "";
    return;
  }
  computerFinderSteps.classList.remove("d-none");
  computerFinderSteps.innerHTML = renderComputerFinderMarkdown(steps.map((step) => `- ${step}`).join("\n"));
}

function setComputerFinderSaveStatus(message, kind = "muted") {
  if (!computerFinderSaveStatus) return;
  computerFinderSaveStatus.className = `small mt-2 text-${kind}`;
  computerFinderSaveStatus.textContent = message;
}

async function computerFinderJsonResponse(response) {
  const responseText = await response.text();
  try {
    return responseText ? JSON.parse(responseText) : {};
  } catch (parseError) {
    return { message: responseText || parseError.message };
  }
}

if (computerFinderForm) {
  computerFinderForm.addEventListener("submit", async (event) => {
    event.preventDefault();
    const specInput = document.getElementById("computer-spec");
    const submitButton = document.getElementById("computer-finder-submit");
    const spec = specInput.value.trim();
    if (!spec) {
      setComputerFinderStatus("Enter a computer specification before searching.", "warning");
      return;
    }
    computerFinderResult.innerHTML = "";
    computerFinderSources.innerHTML = "";
    latestComputerFinderResult = null;
    computerFinderSaveActions?.classList.add("d-none");
    setComputerFinderSaveStatus("");
    renderComputerFinderSteps([]);
    setComputerFinderStatus("Searching configured websites and reading candidate product pages...", "info");
    submitButton.disabled = true;
    submitButton.dataset.originalText = submitButton.textContent;
    submitButton.textContent = "Searching...";
    try {
      const response = await fetch(computerFinderForm.dataset.searchUrl, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ spec }),
      });
      const payload = await computerFinderJsonResponse(response);
      if (!response.ok || !payload.ok) {
        renderComputerFinderSteps(payload.steps || []);
        throw new Error(payload.message || "Computer search failed.");
      }
      computerFinderResult.innerHTML = renderComputerFinderMarkdown(payload.message || "");
      renderComputerFinderSources(payload.sources || []);
      renderComputerFinderSteps(payload.steps || []);
      latestComputerFinderResult = {
        spec,
        message: payload.message || "",
        sources: payload.sources || [],
      };
      computerFinderSaveActions?.classList.remove("d-none");
      setComputerFinderStatus("Search complete.", "success");
    } catch (error) {
      setComputerFinderStatus(error.message, "danger");
    } finally {
      submitButton.disabled = false;
      submitButton.textContent = submitButton.dataset.originalText || "Search And Match";
    }
  });
}

if (computerFinderClear) {
  computerFinderClear.addEventListener("click", () => {
    document.getElementById("computer-spec").value = "";
    computerFinderResult.innerHTML = "";
    computerFinderSources.innerHTML = "";
    latestComputerFinderResult = null;
    computerFinderSaveActions?.classList.add("d-none");
    setComputerFinderSaveStatus("");
    renderComputerFinderSteps([]);
    setComputerFinderStatus("Ready for a spec.", "secondary");
  });
}

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
    const filenameMatch = disposition.match(/filename=\"?([^\";]+)\"?/i);
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
  const tenderSelect = document.getElementById("computer-finder-tender");
  const attachButton = document.getElementById("computer-finder-attach");
  const tenderId = tenderSelect?.value;
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
    if (!response.ok || !result.ok) {
      throw new Error(result.message || "Could not save the result to the tender.");
    }
    setComputerFinderSaveStatus(result.message || "Result saved to tender.", "success");
    if (result.tender_url && computerFinderSaveStatus) {
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

if (computerFinderSettingsForm) {
  computerFinderSettingsForm.addEventListener("submit", async (event) => {
    event.preventDefault();
    const submitButton = document.getElementById("computer-finder-settings-submit");
    const formData = new FormData(computerFinderSettingsForm);
    const payload = Object.fromEntries(formData.entries());
    submitButton.disabled = true;
    submitButton.dataset.originalText = submitButton.textContent;
    submitButton.textContent = "Saving...";
    try {
      const response = await fetch(computerFinderSettingsForm.dataset.settingsUrl, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
      const responseText = await response.text();
      let result = {};
      try {
        result = responseText ? JSON.parse(responseText) : {};
      } catch (parseError) {
        result = { message: responseText || parseError.message };
      }
      if (!response.ok || !result.ok) {
        throw new Error(result.message || "Could not save settings.");
      }
      const summary = document.getElementById("computer-finder-domain-summary");
      if (summary) {
        summary.textContent = `Active: ${result.allowed_domains.length} allowed, ${result.blocked_domains.length} blocked.`;
      }
      setComputerFinderStatus(result.message || "Settings saved.", "success");
    } catch (error) {
      setComputerFinderStatus(error.message, "danger");
    } finally {
      submitButton.disabled = false;
      submitButton.textContent = submitButton.dataset.originalText || "Save Search Settings";
    }
  });
}
