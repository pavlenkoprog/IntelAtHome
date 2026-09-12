from app.services.geo_service import flights, places


def test_places_require_zoom() -> None:
    assert places(10, 10, 12, 12, zoom=3)["items"] == []


def test_flights_reject_huge_bbox() -> None:
    assert flights(-80, -170, 80, 170)["items"] == []
