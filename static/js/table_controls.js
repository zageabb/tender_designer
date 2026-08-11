(() => {
  const cleanText = (value) => String(value || "").replace(/\s+/g, " ").trim();
  const htmlText = (value) => {
    const node = document.createElement("div");
    node.innerHTML = value || "";
    return cleanText(node.textContent);
  };

  const selectedValues = (select) => Array.from(select?.selectedOptions || [])
    .map((option) => option.value)
    .filter(Boolean);

  const clearSelections = (select) => {
    Array.from(select?.options || []).forEach((option) => { option.selected = false; });
  };

  const addGenericControls = (table, tabulator) => {
    if (table.matches("[data-dashboard-table], [data-tenders-table], [data-admin-table]")) return;
    const controls = document.createElement("div");
    controls.className = "card-body border-bottom tabulator-controls";
    controls.innerHTML = `
      <div class="row g-3 align-items-end">
        <div class="col-md-8">
          <label class="form-label">Search table</label>
          <input class="form-control" type="search" placeholder="Search all columns" data-tabulator-search>
        </div>
        <div class="col-md-4">
          <button class="btn btn-outline-secondary w-100" type="button" data-tabulator-reset>Reset</button>
        </div>
      </div>`;
    const wrapper = table._tabulatorWrapper || table.closest(".table-responsive");
    wrapper?.parentElement?.insertBefore(controls, wrapper);
    const search = controls.querySelector("[data-tabulator-search]");
    search.addEventListener("input", () => applyGlobalSearch(tabulator, search.value));
    controls.querySelector("[data-tabulator-reset]").addEventListener("click", () => {
      search.value = "";
      tabulator.clearFilter(true);
      tabulator.clearSort();
    });
  };

  const applyGlobalSearch = (tabulator, query) => {
    const needle = cleanText(query).toLowerCase();
    if (!needle) {
      tabulator.clearFilter(false);
      return;
    }
    tabulator.setFilter((data) => (data._search || "").includes(needle));
  };

  const wireAdminControls = (table, tabulator) => {
    if (!table.matches("[data-admin-table]")) return;
    const search = document.querySelector("[data-admin-search]");
    const columns = document.querySelector("[data-admin-column-filter]");
    const value = document.querySelector("[data-admin-column-value]");
    const apply = () => {
      const needle = cleanText(search?.value).toLowerCase();
      const columnNeedle = cleanText(value?.value).toLowerCase();
      const indexes = selectedValues(columns).map(Number);
      tabulator.setFilter((data) => {
        if (needle && !data._search.includes(needle)) return false;
        if (columnNeedle && indexes.length && !indexes.some((index) => data[`_text_${index}`].includes(columnNeedle))) return false;
        return true;
      });
    };
    [search, value].forEach((control) => control?.addEventListener("input", (event) => {
      event.stopImmediatePropagation(); apply();
    }, {capture: true}));
    columns?.addEventListener("change", (event) => {
      event.stopImmediatePropagation(); apply();
    }, {capture: true});
    document.querySelector("[data-admin-reset]")?.addEventListener("click", (event) => {
      event.stopImmediatePropagation();
      if (search) search.value = "";
      if (value) value.value = "";
      clearSelections(columns);
      tabulator.clearFilter(true);
      tabulator.clearSort();
    }, {capture: true});
  };

  const wireTenderControls = (table, tabulator, prefix) => {
    const search = document.querySelector(`[data-${prefix}-search]`);
    const status = document.querySelector(`[data-${prefix}-status-filter]`);
    const date = document.querySelector(`[data-${prefix}-date-filter]`);
    const rows = tabulator.getData();
    const statuses = [...new Set(rows.map((row) => row._status).filter(Boolean))].sort();
    if (status && status.options.length === 1) {
      statuses.forEach((label) => status.add(new Option(label, label)));
    }
    const apply = () => {
      const needle = cleanText(search?.value).toLowerCase();
      const wantedStatuses = selectedValues(status);
      const wantedDates = selectedValues(date);
      const today = new Date(); today.setHours(0, 0, 0, 0);
      const nextThirty = new Date(today); nextThirty.setDate(today.getDate() + 30);
      tabulator.setFilter((data) => {
        if (needle && !data._search.includes(needle)) return false;
        if (wantedStatuses.length && !wantedStatuses.includes(data._status)) return false;
        if (!wantedDates.length) return true;
        const rowDate = data._date ? new Date(`${data._date}T00:00:00`) : null;
        return wantedDates.some((filter) => (
          (filter === "with-date" && rowDate) ||
          (filter === "without-date" && !rowDate) ||
          (filter === "overdue" && rowDate && rowDate < today) ||
          (filter === "next-30" && rowDate && rowDate >= today && rowDate <= nextThirty)
        ));
      });
    };
    search?.addEventListener("input", (event) => {
      event.stopImmediatePropagation(); apply();
    }, {capture: true});
    status?.addEventListener("change", (event) => {
      event.stopImmediatePropagation(); apply();
    }, {capture: true});
    date?.addEventListener("change", (event) => {
      event.stopImmediatePropagation(); apply();
    }, {capture: true});
    document.querySelector(`[data-${prefix}-reset]`)?.addEventListener("click", (event) => {
      event.stopImmediatePropagation();
      if (search) search.value = "";
      clearSelections(status); clearSelections(date);
      tabulator.clearFilter(true); tabulator.clearSort();
    }, {capture: true});
  };

  const enhanceTable = (table, index) => {
    const header = table.tHead?.rows?.[0];
    const body = table.tBodies?.[0];
    if (!header || !body) return;
    const cells = Array.from(header.cells);
    const sourceRows = Array.from(body.rows);
    const data = sourceRows.map((row, rowIndex) => {
      const record = {id: rowIndex, _search: cleanText(row.textContent).toLowerCase()};
      Array.from(row.cells).forEach((cell, cellIndex) => {
        record[`cell_${cellIndex}`] = cell.innerHTML;
        record[`_text_${cellIndex}`] = cleanText(cell.textContent).toLowerCase();
      });
      record._class = row.className;
      record._status = row.dataset.status || "";
      record._date = row.dataset.submissionDate || "";
      return record;
    });
    const columns = cells.map((cell, cellIndex) => {
      const title = cleanText(cell.textContent);
      return {
        title,
        field: `cell_${cellIndex}`,
        formatter: "html",
        headerSort: Boolean(title) && title.toLowerCase() !== "actions",
        sorter: (left, right) => htmlText(left).localeCompare(htmlText(right), undefined, {numeric: true, sensitivity: "base"}),
        minWidth: title.toLowerCase() === "actions" || !title ? 180 : 130,
        variableHeight: true,
      };
    });
    const replacement = document.createElement("div");
    replacement.id = `tabulator-table-${index}`;
    replacement.className = "tender-tabulator";
    const wrapper = table.closest(".table-responsive");
    table._tabulatorWrapper = wrapper;
    table.replaceWith(replacement);
    wrapper?.classList.add("tabulator-responsive");

    const tabulator = new Tabulator(replacement, {
      data,
      columns,
      layout: "fitDataStretch",
      pagination: data.length > 10,
      paginationSize: 10,
      paginationSizeSelector: [10, 25, 50, 100],
      placeholder: "No records found",
      movableColumns: true,
      rowFormatter: (row) => {
        const className = row.getData()._class;
        if (className) row.getElement().classList.add(...className.split(/\s+/).filter(Boolean));
      },
    });
    addGenericControls(table, tabulator);
    wireAdminControls(table, tabulator);
    if (table.matches("[data-dashboard-table]")) wireTenderControls(table, tabulator, "dashboard");
    if (table.matches("[data-tenders-table]")) wireTenderControls(table, tabulator, "tenders");
  };

  document.addEventListener("DOMContentLoaded", () => {
    if (typeof Tabulator === "undefined") return;
    document.querySelectorAll("table").forEach(enhanceTable);
  });
})();
