from app.services.geo_service import _format_src_date, flights, places


def test_places_require_zoom() -> None:
    assert places(10, 10, 12, 12, zoom=3)["items"] == []


def test_flights_reject_huge_bbox() -> None:
    assert flights(-80, -170, 80, 170)["items"] == []


def test_format_src_date() -> None:
    assert _format_src_date(20250616) == "2025-06-16"
    assert _format_src_date(99999) is None
    assert _format_src_date(None) is None
