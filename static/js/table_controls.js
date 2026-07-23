(() => {
  const SKIP_SELECTORS = [
    "[data-dashboard-table]",
    "[data-tenders-table]",
    "[data-admin-table]",
  ];

  const shouldSkipTable = (table) => SKIP_SELECTORS.some((selector) => table.matches(selector));

  const headerText = (cell) => (cell?.textContent || "").replace(/\s+/g, " ").trim();

  const inferValueType = (values) => {
    const populated = values.filter((value) => value !== "");
    if (populated.length === 0) {
      return "text";
    }
    const allNumbers = populated.every((value) => !Number.isNaN(Number(value.replace(/[^0-9.\-]/g, ""))));
    if (allNumbers) {
      return "number";
    }
    const allDates = populated.every((value) => !Number.isNaN(Date.parse(value)));
    if (allDates) {
      return "date";
    }
    return "text";
  };

  const buildControls = (table, columns, renderRows) => {
    const controls = document.createElement("div");
    controls.className = "card-body border-bottom";
    controls.innerHTML = `
      <div class="row g-3" data-generic-table-filters>
        <div class="col-md-4">
          <label class="form-label">Search</label>
          <input class="form-control" type="search" placeholder="Search this table" data-generic-table-search>
        </div>
        <div class="col-md-3">
          <label class="form-label">Column Filter</label>
          <select class="form-select" data-generic-table-column>
            <option value="">Any column</option>
          </select>
        </div>
        <div class="col-md-3">
          <label class="form-label">Filter Value</label>
          <input class="form-control" type="search" placeholder="Contains value" data-generic-table-value>
        </div>
        <div class="col-md-2 d-flex align-items-end">
          <button class="btn btn-outline-secondary w-100" type="button" data-generic-table-reset>Reset</button>
        </div>
      </div>
    `;

    const columnSelect = controls.querySelector("[data-generic-table-column]");
    for (const column of columns) {
      if (!column.label) {
        continue;
      }
      const option = document.createElement("option");
      option.value = String(column.index);
      option.textContent = column.label;
      columnSelect.appendChild(option);
    }

    controls.querySelector("[data-generic-table-search]")?.addEventListener("input", renderRows);
    controls.querySelector("[data-generic-table-column]")?.addEventListener("change", renderRows);
    controls.querySelector("[data-generic-table-value]")?.addEventListener("input", renderRows);
    controls.querySelector("[data-generic-table-reset]")?.addEventListener("click", () => {
      controls.querySelector("[data-generic-table-search]").value = "";
      controls.querySelector("[data-generic-table-column]").value = "";
      controls.querySelector("[data-generic-table-value]").value = "";
      renderRows(true);
    });

    const parentCard = table.closest(".card");
    const container = table.closest(".table-responsive");
    if (parentCard && container && container.parentElement === parentCard) {
      parentCard.insertBefore(controls, container);
    } else if (container?.parentElement) {
      container.parentElement.insertBefore(controls, container);
    }

    return controls;
  };

  const enhanceTable = (table) => {
    if (shouldSkipTable(table)) {
      return;
    }
    const body = table.tBodies?.[0];
    if (!body) {
      return;
    }
    const rows = Array.from(body.rows).filter((row) => row.children.length > 0);
    if (rows.length <= 1) {
      return;
    }
    const headerRow = table.tHead?.rows?.[0];
    if (!headerRow) {
      return;
    }

    const columns = Array.from(headerRow.cells).map((cell, index) => ({
      cell,
      index,
      label: headerText(cell),
    }));

    const sortableColumns = columns.filter((column) => column.label && column.label.toLowerCase() !== "actions");
    const allRows = [...rows];
    let sortIndex = sortableColumns[0]?.index ?? 0;
    let sortDirection = "asc";
    let controls = null;

    const readCellText = (row, index) => (row.cells[index]?.textContent || "").replace(/\s+/g, " ").trim();

    const renderRows = (resetSort = false) => {
      if (resetSort) {
        sortIndex = sortableColumns[0]?.index ?? 0;
        sortDirection = "asc";
      }
      const searchValue = (controls?.querySelector("[data-generic-table-search]")?.value || "").trim().toLowerCase();
      const filterColumn = controls?.querySelector("[data-generic-table-column]")?.value || "";
      const filterValue = (controls?.querySelector("[data-generic-table-value]")?.value || "").trim().toLowerCase();

      const filteredRows = allRows.filter((row) => {
        const rowText = Array.from(row.cells)
          .map((cell) => (cell.textContent || "").replace(/\s+/g, " ").trim().toLowerCase())
          .join(" ");
        if (searchValue && !rowText.includes(searchValue)) {
          return false;
        }
        if (filterColumn !== "" && filterValue) {
          const target = readCellText(row, Number(filterColumn)).toLowerCase();
          if (!target.includes(filterValue)) {
            return false;
          }
        }
        return true;
      });

      const type = inferValueType(filteredRows.map((row) => readCellText(row, sortIndex)));
      filteredRows.sort((left, right) => {
        let leftValue = readCellText(left, sortIndex);
        let rightValue = readCellText(right, sortIndex);
        if (type === "number") {
          leftValue = Number(leftValue.replace(/[^0-9.\-]/g, ""));
          rightValue = Number(rightValue.replace(/[^0-9.\-]/g, ""));
        } else if (type === "date") {
          leftValue = Date.parse(leftValue || "9999-12-31");
          rightValue = Date.parse(rightValue || "9999-12-31");
        } else {
          leftValue = leftValue.toLowerCase();
          rightValue = rightValue.toLowerCase();
        }
        if (leftValue < rightValue) {
          return sortDirection === "asc" ? -1 : 1;
        }
        if (leftValue > rightValue) {
          return sortDirection === "asc" ? 1 : -1;
        }
        return 0;
      });

      for (const row of allRows) {
        row.remove();
      }
      for (const row of filteredRows) {
        body.appendChild(row);
      }
    };

    for (const column of sortableColumns) {
      const label = column.label;
      column.cell.innerHTML = "";
      const button = document.createElement("button");
      button.type = "button";
      button.className = "btn btn-link btn-sm p-0 text-decoration-none";
      button.textContent = label;
      button.addEventListener("click", () => {
        if (sortIndex === column.index) {
          sortDirection = sortDirection === "asc" ? "desc" : "asc";
        } else {
          sortIndex = column.index;
          sortDirection = "asc";
        }
        renderRows();
      });
      column.cell.appendChild(button);
    }

    controls = buildControls(table, columns, renderRows);
    renderRows();
  };

  document.addEventListener("DOMContentLoaded", () => {
    document.querySelectorAll("table").forEach(enhanceTable);
  });
})();
