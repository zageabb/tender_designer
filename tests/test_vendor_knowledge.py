from __future__ import annotations

from openpyxl import Workbook

from services.vendor_knowledge import parse_vendor_workbook


def test_parse_vendor_workbook_detects_versions_categories_and_availability(tmp_path):
    path = tmp_path / "vendor_stock.xlsx"
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "New Stock"
    sheet.append([])
    sheet.append([None, "Technoworld Offers - 8th September 2026"])
    sheet.append([])
    sheet.append(["Sept Deal", "Item Description", "Part No", "Qty", "Price Qty 1- 29", "Price Qty 30+"])
    sheet.append([None, "Laptops"])
    sheet.append(["New In", "Example ProBook Core Ultra 5 16GB 512GB", "ABC123", "100+", 599, 575])
    sheet.append([None, "Sold out example", "ABC000", 0, 399, 390])

    refurb = workbook.create_sheet("Official HP Certified Refurb")
    refurb.append([])
    refurb.append([None, "Technoworld Refurbished Offers - 8th September 2026"])
    refurb.append([])
    refurb.append([None, "Item Description", "Part No", "Qty", "Price Qty 1- 29", "Price Qty 30+"])
    refurb.append([None, "Laptops"])
    refurb.append([None, "HP EliteBook 840 G7 16GB 256GB", "REF123", 5, 292, 292])
    workbook.save(path)

    parsed = parse_vendor_workbook(path)

    assert parsed.detected_vendor == "Technoworld"
    assert parsed.source_date.isoformat() == "2026-09-08"
    assert len(parsed.items) == 3
    assert parsed.items[0].source_category == "Laptops"
    assert parsed.items[0].quantity_minimum == 100
    assert parsed.items[0].quantity_exact is False
    assert parsed.items[0].is_available is True
    assert parsed.items[1].is_available is False
    assert parsed.items[2].stock_type == "refurbished"
