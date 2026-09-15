(() => {
  if (typeof currentResearchMode !== "function") return;

  const VENDOR_ONLY_MARKER = "[VENDOR_KNOWLEDGE_ONLY]";
  const VENDOR_ONLY_STORAGE_KEY = "equipment-research:vendor-knowledge-only";

  if (typeof researchModeLabel === "function") {
    researchModeLabel = function researchModeLabel() {
      return currentResearchMode() === "general" ? "General Search" : "Equipment Research";
    };
  }

  const vendorOnlyToggle = () => document.getElementById("equipment-vendor-knowledge-only");

  const vendorOnlyEnabled = () => currentResearchMode() !== "general" && Boolean(vendorOnlyToggle()?.checked);

  const applyVendorModeLabels = () => {
    const toggleWrap = document.getElementById("equipment-vendor-knowledge-only-wrap");
    if (toggleWrap) toggleWrap.classList.toggle("d-none", currentResearchMode() === "general");
    if (currentResearchMode() === "general") return;
    const submit = document.getElementById("computer-finder-submit");
    if (submit && !submit.disabled) {
      submit.textContent = vendorOnlyEnabled() ? "Search Vendor Knowledge" : "Search Equipment";
    }
    const runtimeLabel = document.querySelector(".computer-finder-runtime-header .finder-message-label");
    if (runtimeLabel) runtimeLabel.textContent = vendorOnlyEnabled() ? "Vendor Verification Activity" : "Live Research Activity";
  };

  const installVendorKnowledgeMode = () => {
    const form = document.getElementById("computer-finder-form");
    if (!form || document.getElementById("equipment-vendor-knowledge-only-wrap")) return;
    const buttonRow = form.querySelector(".d-flex.gap-2.flex-wrap.mt-3");
    const control = document.createElement("div");
    control.id = "equipment-vendor-knowledge-only-wrap";
    control.className = "border rounded p-3 mt-3 bg-light-subtle";
    control.innerHTML = `
      <div class="form-check form-switch mb-1">
        <input class="form-check-input" type="checkbox" role="switch" id="equipment-vendor-knowledge-only">
        <label class="form-check-label fw-semibold" for="equipment-vendor-knowledge-only">Vendor Knowledge candidates only</label>
      </div>
      <div class="small text-muted ms-4">Only products currently held in Vendor Knowledge may be returned. Internet/OEM sources may still be searched to verify that those products meet the tender specification; outside alternatives will not be introduced.</div>
    `;
    if (buttonRow) form.insertBefore(control, buttonRow);
    else form.appendChild(control);

    const toggle = vendorOnlyToggle();
    try {
      toggle.checked = sessionStorage.getItem(VENDOR_ONLY_STORAGE_KEY) === "1";
    } catch (_error) {
      toggle.checked = false;
    }
    toggle.addEventListener("change", () => {
      try {
        sessionStorage.setItem(VENDOR_ONLY_STORAGE_KEY, toggle.checked ? "1" : "0");
      } catch (_error) {
        // Session storage is optional; the control still works for this page load.
      }
      applyVendorModeLabels();
    });
  };

  const applyEquipmentLabels = () => {
    if (currentResearchMode() === "general") {
      applyVendorModeLabels();
      return;
    }
    const title = document.getElementById("research-page-title");
    const description = document.getElementById("research-page-description");
    const requestLabel = document.getElementById("research-request-label");
    const submit = document.getElementById("computer-finder-submit");
    const specAuto = document.getElementById("computer-finder-spec-auto");
    const promptHeading = document.getElementById("equipment-research-prompt-heading");
    const promptCopy = document.getElementById("equipment-research-prompt-copy");

    if (title) title.textContent = "Equipment Research";
    if (description) description.textContent = "Find equipment against tender technical requirements, compare compliance, and keep commercial data separate from the technical match.";
    if (requestLabel) requestLabel.textContent = "Tender / equipment requirements";
    if (computerFinderBaseSpec) {
      computerFinderBaseSpec.placeholder = "Describe the equipment, quantity, ratings, standards, configuration and mandatory technical requirements.";
    }
    if (computerFinderInstruction) {
      computerFinderInstruction.placeholder = "Example: Treat 25 kA as mandatory, prefer OEM datasheets, and flag anything only supported at product-family level.";
    }
    if (submit && !submit.disabled) submit.textContent = "Search Equipment";
    if (specAuto) specAuto.textContent = "Generate IT Spec Sheet";
    if (promptHeading) promptHeading.textContent = "Equipment Research instructions";
    if (promptCopy) promptCopy.textContent = "Live instructions for technical requirement parsing, evidence-led equipment searches and compliance comparison.";
    applyVendorModeLabels();
  };

  if (typeof updateResearchModeUi === "function") {
    const originalUpdateResearchModeUi = updateResearchModeUi;
    updateResearchModeUi = function equipmentAwareUpdateResearchModeUi() {
      originalUpdateResearchModeUi();
      applyEquipmentLabels();
    };
  }

  if (typeof setComputerFinderRunning === "function") {
    const originalSetComputerFinderRunning = setComputerFinderRunning;
    setComputerFinderRunning = function equipmentAwareSetComputerFinderRunning(running) {
      originalSetComputerFinderRunning(running);
      if (!running) applyEquipmentLabels();
    };
  }

  const originalFetch = window.fetch.bind(window);
  window.fetch = (input, init = {}) => {
    const requestUrl = typeof input === "string" ? input : input?.url || "";
    const searchUrl = computerFinderWorkspace?.dataset?.searchUrl || "";
    const method = String(init.method || (typeof input !== "string" ? input?.method : "GET") || "GET").toUpperCase();
    if (
      vendorOnlyEnabled()
      && method === "POST"
      && searchUrl
      && (requestUrl === searchUrl || requestUrl.endsWith(searchUrl))
      && typeof init.body === "string"
    ) {
      try {
        const payload = JSON.parse(init.body);
        if (payload.mode !== "general") {
          const baseSpec = String(payload.base_spec || "").replace(VENDOR_ONLY_MARKER, "").trim();
          payload.base_spec = `${baseSpec}\n\n${VENDOR_ONLY_MARKER}`.trim();
          init = { ...init, body: JSON.stringify(payload) };
        }
      } catch (_error) {
        // Leave non-JSON requests untouched.
      }
    }
    return originalFetch(input, init);
  };

  installVendorKnowledgeMode();
  applyEquipmentLabels();
})();
