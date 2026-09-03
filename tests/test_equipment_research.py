from services.enhanced_equipment_reader import (
    _evidence_sufficient,
    _structured_product_text,
)


def test_structured_product_metadata_extracts_identity_and_ratings():
    html = '''
    <html><head>
      <script type="application/ld+json">
      {
        "@type": "Product",
        "name": "Example NX 12",
        "model": "NX-12-3150",
        "mpn": "NX123150",
        "brand": {"@type": "Brand", "name": "Example Energy"},
        "additionalProperty": [
          {"@type": "PropertyValue", "name": "Rated voltage", "value": "12 kV"},
          {"@type": "PropertyValue", "name": "Rated current", "value": "3150 A"},
          {"@type": "PropertyValue", "name": "Short-circuit rating", "value": "31.5 kA"}
        ]
      }
      </script>
    </head><body></body></html>
    '''

    text = _structured_product_text(html)

    assert "Example NX 12" in text
    assert "NX-12-3150" in text
    assert "Example Energy" in text
    assert "Rated voltage: 12 kV" in text
    assert "Rated current: 3150 A" in text
    assert "Short-circuit rating: 31.5 kA" in text


def test_evidence_sufficiency_is_based_on_technical_content_not_price():
    technical = (
        "Manufacturer technical datasheet. Model NX-12. Rated voltage 12 kV. "
        "Rated current 3150 A. Short-circuit rating 31.5 kA. IEC 62271-200. "
        + "Technical specification details. " * 40
    )
    commercial_only = "Price £12,500 available now. Buy online. " * 40

    assert _evidence_sufficient(technical) is True
    assert _evidence_sufficient(commercial_only) is False
