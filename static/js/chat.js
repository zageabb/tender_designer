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
  if (context.page === "computer_finder") {
    const spec = document.getElementById("computer-spec")?.value?.trim();
    const status = document.getElementById("computer-finder-status")?.textContent?.trim();
    const result = document.getElementById("computer-finder-result")?.textContent?.trim();
    const sources = document.getElementById("computer-finder-sources")?.textContent?.trim();
    const steps = document.getElementById("computer-finder-steps")?.textContent?.trim();
    const allowedDomains = document.getElementById("computer-finder-allowed-domains")?.value?.trim();
    const blockedDomains = document.getElementById("computer-finder-blocked-domains")?.value?.trim();
    const searxngUrl = document.getElementById("computer-finder-searxng-url")?.value?.trim();
    const searxngEngines = document.getElementById("computer-finder-searxng-engines")?.value?.trim();
    if (spec) context.computer_spec = spec.slice(0, 4000);
    if (status) context.computer_finder_status = status.slice(0, 1000);
    if (result) context.computer_finder_result = result.slice(0, 6000);
    if (sources) context.computer_finder_sources = sources.slice(0, 3000);
    if (steps) context.computer_finder_diagnostics = steps.slice(0, 5000);
    if (allowedDomains) context.computer_finder_allowed_domains = allowedDomains.slice(0, 2000);
    if (blockedDomains) context.computer_finder_blocked_domains = blockedDomains.slice(0, 1000);
    if (searxngUrl) context.computer_finder_searxng_url = searxngUrl.slice(0, 500);
    if (searxngEngines) context.computer_finder_searxng_engines = searxngEngines.slice(0, 500);
  }
  return context;
}

function appendMessage(role, text, steps = []) {
  const node = document.createElement("div");
  node.className = `chat-message ${role}`;
  const body = document.createElement("div");
  body.className = "chat-message-body";
  body.innerHTML = renderMarkdown(text);
  node.appendChild(body);
  if (steps.length) {
    const detail = document.createElement("div");
    detail.className = "chat-steps";
    detail.innerHTML = renderMarkdown(steps.map((step) => `- ${step}`).join("\n"));
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

function formatInlineMarkdown(value) {
  let formatted = escapeHtml(value);
  formatted = formatted.replace(/`([^`]+)`/g, "<code>$1</code>");
  formatted = formatted.replace(/\[([^\]]+)\]\((https?:\/\/[^\s)]+)\)/g, '<a href="$2" target="_blank" rel="noopener noreferrer">$1</a>');
  formatted = formatted.replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>");
  formatted = formatted.replace(/\*([^*]+)\*/g, "<em>$1</em>");
  return formatted;
}

function renderMarkdown(text) {
  const source = String(text || "").replace(/\r\n/g, "\n").trim();
  if (!source) return "";

  const lines = source.split("\n");
  const html = [];
  let paragraph = [];
  let listType = null;
  let listItems = [];
  let inCodeBlock = false;
  let codeLines = [];

  function flushParagraph() {
    if (!paragraph.length) return;
    html.push(`<p>${paragraph.map((line) => formatInlineMarkdown(line)).join("<br>")}</p>`);
    paragraph = [];
  }

  function flushList() {
    if (!listType || !listItems.length) return;
    html.push(`<${listType}>${listItems.map((item) => `<li>${formatInlineMarkdown(item)}</li>`).join("")}</${listType}>`);
    listType = null;
    listItems = [];
  }

  function flushCodeBlock() {
    if (!inCodeBlock) return;
    html.push(`<pre><code>${escapeHtml(codeLines.join("\n"))}</code></pre>`);
    inCodeBlock = false;
    codeLines = [];
  }

  for (const line of lines) {
    if (line.trim().startsWith("```")) {
      flushParagraph();
      flushList();
      if (inCodeBlock) {
        flushCodeBlock();
      } else {
        inCodeBlock = true;
      }
      continue;
    }

    if (inCodeBlock) {
      codeLines.push(line);
      continue;
    }

    const unorderedMatch = line.match(/^\s*[-*]\s+(.*)$/);
    const orderedMatch = line.match(/^\s*\d+\.\s+(.*)$/);

    if (!line.trim()) {
      flushParagraph();
      flushList();
      continue;
    }

    if (unorderedMatch) {
      flushParagraph();
      if (listType && listType !== "ul") flushList();
      listType = "ul";
      listItems.push(unorderedMatch[1]);
      continue;
    }

    if (orderedMatch) {
      flushParagraph();
      if (listType && listType !== "ol") flushList();
      listType = "ol";
      listItems.push(orderedMatch[1]);
      continue;
    }

    flushList();
    paragraph.push(line);
  }

  flushParagraph();
  flushList();
  flushCodeBlock();

  return html.join("");
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

document.querySelectorAll("form[data-requires-doc-selection], form[data-llm-request]").forEach((form) => {
  form.addEventListener("submit", (event) => {
    if (form.dataset.requiresDocSelection === "true") {
      const selectedIds = Array.from(document.querySelectorAll(".extraction-document-checkbox:checked")).map((checkbox) => checkbox.value);
      if (!selectedIds.length) {
        event.preventDefault();
        window.alert("Select at least one document before continuing.");
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
    if (form.dataset.llmRequest) {
      const message = form.dataset.llmRequest || "LLM request started.";
      appendMessage("system", message);
    }
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
