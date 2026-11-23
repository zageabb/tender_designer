"""Regression coverage for selected-source monthly tender item splitting."""
from services.delivery_schedule import build_delivery_items, parse_delivery_schedule

DESCRIPTION = (
    'Description: Laptop Computer • 13th gen or greater power efficient processor '
    '(Intel or AMD) • 16GB Ram DDR5 • 500GB SSD NVMe • LAN port/RJ45 • Wi-Fi 6 '
    '• 14~16" Screen • OS needed (not home edition) • Charger included '
    '• 50WHrs Battery • 3 Year Warranty Tentative Delivery schedule: '
    'January 2027: 100 sets February 2027: 100 sets March 2027: 100 sets '
    'April 2027: 100 sets May 2027: 200 sets June 2027: 200 sets '
    'July 2027: 200 sets'
)


def test_laptop_schedule_creates_seven_monthly_items():
    items = build_delivery_items(DESCRIPTION, "Tender item #12")
    assert len(items) == 7
    assert [int(i["quantity_required"]) for i in items] == [100, 100, 100, 100, 200, 200, 200]
    assert sum(int(i["quantity_required"]) for i in items) == 1000
    assert items[0]["description"] == "Laptop Computer - January 2027"
    assert items[-1]["delivery_month"] == "July 2027"
    assert all("16GB Ram DDR5" in i["specification_summary"] for i in items)
    assert all("3 Year Warranty" in i["specification_summary"] for i in items)
    assert all("Delivery schedule" not in i["specification_summary"] for i in items)


def test_no_schedule_returns_no_items():
    assert build_delivery_items("Laptop Computer • 16GB RAM", "source") == []


def test_rejects_partial_schedule_instead_of_dropping_month():
    description = "Laptop • 16GB RAM Tentative Delivery schedule: January 2027: 100 sets February 2027: TBD sets"
    assert build_delivery_items(description, "source") == []


def test_duplicate_month_is_rejected():
    description = "Laptop Tentative Delivery schedule: January 2027: 100 sets January 2027: 200 sets"
    assert build_delivery_items(description, "source") == []


def test_commas_and_mixed_case_are_supported():
    description = "Laptop Tentative Delivery Schedule: january 2027: 1,000 units FEBRUARY 2027: 250 units"
    spec, schedule = parse_delivery_schedule(description)
    assert spec == "Laptop"
    assert [(i["month"], i["quantity"]) for i in schedule] == [("January", 1000), ("February", 250)]


def test_multiline_document_description_and_schedule():
    extracted = (
        "Tender item 1\nDescription:\n"
        "Laptop Computer • 13th gen CPU • 16GB Ram DDR5 • 3 Year Warranty\n"
        "Tentative Delivery schedule:\n"
        "January 2027: 100 sets\n"
        "February 2027: 100 sets\n"
        "March 2027: 100 sets\n"
        "April 2027: 100 sets\n"
        "May 2027: 200 sets\n"
        "June 2027: 200 sets\n"
        "July 2027: 200 sets\n"
        "Other terms: provide a 3-year warranty\n"
    )
    items = build_delivery_items(extracted, "Document #9: laptops.pdf")
    assert len(items) == 7
    assert sum(int(item["quantity_required"]) for item in items) == 1000
    assert items[0]["description"] == "Laptop Computer - January 2027"
    assert "3 Year Warranty" in items[-1]["specification_summary"]


def test_rejects_incomplete_month_on_following_line():
    extracted = (
        "Description: Laptop Computer\n"
        "Delivery schedule:\nJanuary 2027: 100 sets\n"
        "February 2027: TBD sets\n"
    )
    assert build_delivery_items(extracted, "document") == []
