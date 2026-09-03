(() => {
  if (typeof currentResearchMode !== "function") return;

  if (typeof researchModeLabel === "function") {
    researchModeLabel = function researchModeLabel() {
      return currentResearchMode() === "general" ? "General Search" : "Equipment Research";
    };
  }

  const applyEquipmentLabels = () => {
    if (currentResearchMode() === "general") return;
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

  applyEquipmentLabels();
})();
