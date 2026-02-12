from services.swiftness_data_service import get_swiftness_data_service


def test_report_model_sections_have_compatible_titles():
    service = get_swiftness_data_service()
    model = service.get_report_model()
    sections = model.get("sections", [])

    assert sections, "Expected report model to include sections"

    for section in sections:
        assert isinstance(section.get("title_he"), str)
        assert section["title_he"].strip()

        assert isinstance(section.get("title_en"), str)
        assert section["title_en"].strip()

        # Backward-compatible alias used by some frontend consumers.
        assert isinstance(section.get("title"), str)
        assert section["title"].strip()


def test_report_model_sections_are_sorted_and_unique_by_order():
    service = get_swiftness_data_service()
    model = service.get_report_model()
    sections = model.get("sections", [])

    orders = [section.get("order") for section in sections]
    assert orders == sorted(orders)
    assert len(set(orders)) == len(orders)


def test_report_model_returns_immutable_section_copies():
    service = get_swiftness_data_service()

    first = service.get_report_model()
    second = service.get_report_model()

    assert first.get("sections")
    assert second.get("sections")

    first["sections"][0]["title_en"] = "MUTATED-TITLE"
    assert second["sections"][0]["title_en"] != "MUTATED-TITLE"
