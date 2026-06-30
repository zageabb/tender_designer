const chatContext = JSON.parse(document.body.dataset.chatContext || "{}");
const chatHistory = document.getElementById("chat-history");
const chatForm = document.getElementById("chat-form");
const uploadForm = document.getElementById("chat-upload-form");
const chatPanel = document.querySelector(".chat-panel");
const clearButton = document.getElementById("chat-clear-button");
let historyLoaded = false;
let lastRenderedHistoryCount = 0;

function buildChatContext() {
  const context = { ...chatContext };
  const selectedIds = Array.from(document.querySelectorAll(".extraction-document-checkbox:checked"))
    .map((checkbox) => Number(checkbox.value))
    .filter((value) => Number.isFinite(value));
  if (selectedIds.length) {
    context.selected_document_ids = selectedIds;
  } else {
    delete context.selected_document_ids;
  }
  return context;
}

function appendMessage(role, text, steps = []) {
  const node = document.createElement("div");
  node.className = `chat-message ${role}`;
  const body = document.createElement("div");
  body.textContent = text;
  node.appendChild(body);
  if (steps.length) {
    const detail = document.createElement("div");
    detail.className = "chat-steps";
    detail.textContent = steps.map((step) => `- ${step}`).join("\n");
    node.appendChild(detail);
  }
  chatHistory.appendChild(node);
  chatHistory.scrollTop = chatHistory.scrollHeight;
}

function escapeHtml(value) {
  return String(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#39;");
}

async function loadHistory() {
  if (!chatHistory || historyLoaded) return;
  const response = await fetch("/chat/history", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ context: buildChatContext() }),
  });
  const payload = await response.json();
  if (payload.messages?.length) {
    chatHistory.innerHTML = "";
    payload.messages.forEach((message) => appendMessage(message.role, message.message_text, message.intermediate_steps || []));
    lastRenderedHistoryCount = payload.messages.length;
  }
  historyLoaded = true;
}

loadHistory();

if (clearButton) {
  clearButton.addEventListener("click", async () => {
    const confirmed = window.confirm("Clear this chat history and reset its saved context for the current screen?");
    if (!confirmed) return;
    const response = await fetch("/chat/clear", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ context: buildChatContext() }),
    });
    const payload = await response.json();
    chatHistory.innerHTML = "";
    appendMessage("assistant", payload.message || "Chat cleared.");
    historyLoaded = false;
  });
}

if (chatForm) {
  chatForm.addEventListener("submit", async (event) => {
    event.preventDefault();
    const messageField = document.getElementById("chat-message");
    const submitButton = chatForm.querySelector("button[type='submit']");
    const message = messageField.value.trim();
    if (!message) return;
    appendMessage("user", message);
    appendMessage("system", "LLM request started. Interpreting your message and gathering the right context.");
    messageField.value = "";
    if (submitButton) {
      submitButton.disabled = true;
      submitButton.dataset.originalText = submitButton.textContent;
      submitButton.textContent = "Working...";
    }
    const response = await fetch("/chat/message", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ message, context: buildChatContext() }),
    });
    const payload = await response.json();
    appendMessage("assistant", payload.message || "No response.", payload.intermediate_steps || []);
    if (submitButton) {
      submitButton.disabled = false;
      submitButton.textContent = submitButton.dataset.originalText || "Send";
    }
    if (payload.redirect_url) {
      window.location.href = payload.redirect_url;
      return;
    }
    if (payload.refresh_page) {
      window.setTimeout(() => window.location.reload(), 500);
    }
  });
}

document.querySelectorAll("form[data-llm-request]").forEach((form) => {
  form.addEventListener("submit", (event) => {
    if (form.dataset.requiresDocSelection === "true") {
      const selectedIds = Array.from(document.querySelectorAll(".extraction-document-checkbox:checked")).map((checkbox) => checkbox.value);
      if (!selectedIds.length) {
        event.preventDefault();
        window.alert("Select at least one document before running extraction.");
        return;
      }
      form.querySelectorAll("input[name='document_ids']").forEach((input) => input.remove());
      selectedIds.forEach((id) => {
        const input = document.createElement("input");
        input.type = "hidden";
        input.name = "document_ids";
        input.value = id;
        form.appendChild(input);
      });
    }
    const message = form.dataset.llmRequest || "LLM request started.";
    appendMessage("system", message);
    const button = form.querySelector("button[type='submit']");
    if (button) {
      button.disabled = true;
      button.dataset.originalText = button.textContent;
      button.textContent = "Working...";
    }
  });
});

if (uploadForm) {
  uploadForm.addEventListener("change", async () => {
    const input = document.getElementById("chat-file-input");
    if (!input.files.length) return;
    const formData = new FormData();
    formData.append("file", input.files[0]);
    const requestContext = buildChatContext();
    formData.append("context", JSON.stringify(requestContext));
    if (requestContext.tender_id) formData.append("tender_id", String(requestContext.tender_id));
    const response = await fetch("/chat/upload", { method: "POST", body: formData });
    const payload = await response.json();
    appendMessage("assistant", payload.message || "Upload finished.");
    input.value = "";
  });
}

document.querySelector("[data-chat-toggle]")?.addEventListener("click", () => {
  chatPanel.classList.toggle("is-collapsed");
});

const jobsRoot = document.querySelector("[data-extraction-jobs-root]");

function renderJobRows(jobs) {
  const body = document.getElementById("extraction-jobs-body");
  if (!body) return;
  if (!jobs.length) {
    body.innerHTML = '<tr><td colspan="5" class="text-muted">No background extraction jobs yet.</td></tr>';
    return;
  }
  body.innerHTML = jobs.map((job) => {
    const statusLabel = `${job.status.charAt(0).toUpperCase()}${job.status.slice(1)}`;
    const notes = escapeHtml((job.error_message || job.summary_message || "-").slice(0, 160));
    const docs = escapeHtml((job.selected_document_names || []).join(", ").slice(0, 120) || "-");
    return `
      <tr data-job-id="${job.id}" data-job-status="${job.status}">
        <td>#${job.id}</td>
        <td>${escapeHtml(job.task_type)}</td>
        <td><span class="badge extraction-job-badge status-${escapeHtml(job.status.toLowerCase())}">${escapeHtml(statusLabel)}</span></td>
        <td><div class="text-preview">${docs}</div></td>
        <td><div class="text-preview">${notes}</div></td>
      </tr>
    `;
  }).join("");
}

if (jobsRoot) {
  const tenderId = jobsRoot.dataset.tenderId;
  let seenActiveJobIds = new Set(
    Array.from(document.querySelectorAll("[data-job-status]"))
      .filter((row) => ["queued", "running"].includes(row.dataset.jobStatus))
      .map((row) => row.dataset.jobId),
  );

  window.setInterval(async () => {
    const [jobsResponse, historyResponse] = await Promise.all([
      fetch(`/tenders/${tenderId}/jobs/status`),
      fetch("/chat/history", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ context: buildChatContext() }),
      }),
    ]);
    const jobsPayload = await jobsResponse.json();
    const historyPayload = await historyResponse.json();
    const jobs = jobsPayload.jobs || [];
    renderJobRows(jobs);

    if (historyPayload.messages?.length && historyPayload.messages.length !== lastRenderedHistoryCount) {
      chatHistory.innerHTML = "";
      historyPayload.messages.forEach((message) => appendMessage(message.role, message.message_text, message.intermediate_steps || []));
      lastRenderedHistoryCount = historyPayload.messages.length;
      historyLoaded = true;
    }

    const activeJobs = jobs.filter((job) => ["queued", "running"].includes(job.status));
    const finishedJobs = jobs.filter((job) => ["completed", "failed"].includes(job.status) && seenActiveJobIds.has(String(job.id)));
    seenActiveJobIds = new Set(activeJobs.map((job) => String(job.id)));
    if (finishedJobs.length) {
      window.setTimeout(() => window.location.reload(), 400);
    }
  }, 4000);
}
