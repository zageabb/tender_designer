# Vendor Knowledge

Tender Designer can store reusable vendor stock/price documents independently from any individual tender.

## Intended workflow

1. A vendor stock or price list arrives in the Tender Designer mailbox.
2. Open the mailbox message.
3. On a supported `.xlsx`, `.xlsm` or `.csv` attachment, choose **Push to Vendor Knowledge**.
4. Confirm the vendor name. By default the sender name/email is used; the importer also detects titles such as `Technoworld Offers - 8th September 2026`.
5. The document is copied into managed Vendor Knowledge storage and normalised into searchable item rows.
6. The new version becomes **Active** and older active versions for the same vendor become **Archived**.
7. Equipment Research searches active, available vendor items and includes the strongest matches as commercial evidence while continuing to use web/OEM evidence for technical compliance.

## Versioning and retention

- Source documents are immutable once imported.
- New versions archive older active versions for that vendor.
- Archived versions, product rows, source metadata and original files remain retained.
- Archived versions can be reactivated later.
- There is intentionally no automatic delete path for Vendor Knowledge versions.
- Identical files for the same vendor are de-duplicated rather than creating another version.

## Normalised commercial fields

The importer detects common columns including description, part number, quantity/stock, quantity-break prices, unit price, condition and vendor item ID. It also keeps sheet name, source row, category/headings, source date, stock type (new/refurbished/open box) and the original row JSON for traceability.

The supplied Technoworld workbook layout is supported, including the `New Stock`, `Official HP Certified Refurb`, and `TW Open Box & Refurb` sheets.

## Search behaviour

Vendor Knowledge search:

- uses active versions by default;
- uses available items by default;
- gives exact/partial part-number matches a large score boost;
- matches technical tokens such as processor family, RAM, SSD size, screen size and other model terms;
- slightly prefers new stock over refurbished/open-box when technical relevance is otherwise similar;
- keeps commercial information separate from technical compliance.

The read-only JSON endpoint is:

`GET /vendor-knowledge/api/search?q=<specification or part number>`
