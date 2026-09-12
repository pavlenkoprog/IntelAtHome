from app.services.geo_service import (
    _CACHE,
    _STORE,
    _format_src_date,
    _parse_adsb,
    _put_store,
    _spread_flights,
    flights,
    places,
    radar_tile_url,
    sample_weather_grid,
    weather_field,
    weather_radar,
)


def test_places_require_zoom() -> None:
    assert places(10, 10, 12, 12, zoom=3)["items"] == []


def test_flights_filter_store_to_bbox() -> None:
    _STORE.clear()
    _put_store(
        "flights",
        {
            "items": [
                {"id": "in", "name": "In", "kind": "flight", "lat": 51, "lon": 31, "military": False},
                {"id": "out", "name": "Out", "kind": "flight", "lat": 10, "lon": 10, "military": False},
            ],
            "source": "OpenSky",
        },
    )
    data = flights(40, 20, 60, 40)
    assert [item["id"] for item in data["items"]] == ["in"]
    assert data["source"] == "OpenSky"


def test_flights_world_store_keeps_all() -> None:
    _STORE.clear()
    _put_store(
        "flights",
        {
            "items": [
                {"id": "abc", "name": "A", "kind": "flight", "lat": 0, "lon": 0, "military": False},
                {"id": "xyz", "name": "B", "kind": "flight", "lat": 50, "lon": 30, "military": False},
            ],
            "source": "OpenSky",
        },
    )
    data = flights(-80, -170, 80, 170)
    assert {item["id"] for item in data["items"]} == {"abc", "xyz"}


def test_parse_adsb_accepts_aircraft_key() -> None:
    items = _parse_adsb(
        {"aircraft": [{"hex": "ABC", "lat": 1.5, "lon": 2.5, "flight": "TST1", "track": 90}]}
    )
    assert items == [
        {
            "id": "abc",
            "name": "TST1",
            "kind": "flight",
            "lat": 1.5,
            "lon": 2.5,
            "altitude": None,
            "heading": 90,
            "country": None,
            "military": False,
        }
    ]


def test_flights_warming_without_store() -> None:
    _STORE.clear()
    data = flights(40, 20, 60, 40)
    assert data["items"] == []
    assert data["reason"] == "warming"


def test_spread_flights_keeps_sparse_cells() -> None:
    items = [
        *[{"id": f"a{i}", "name": "A", "kind": "flight", "lat": 51.5, "lon": -0.2} for i in range(80)],
        {"id": "b1", "name": "B", "kind": "flight", "lat": 46.0, "lon": 6.0},
    ]
    chosen = _spread_flights(items, 45, -5, 54, 8, limit=20)
    assert any(item["id"] == "b1" for item in chosen)


def test_places_keep_mixed_kinds(monkeypatch) -> None:
    monkeypatch.setattr(
        "app.services.geo_service._natural_earth_cities",
        lambda: [
            {"id": "t1", "name": "Town", "kind": "town", "lat": 10.5, "lon": 10.5, "pop": 80000},
            {"id": "t2", "name": "Village", "kind": "town", "lat": 10.4, "lon": 10.4, "pop": 12000},
        ],
    )
    monkeypatch.setattr(
        "app.services.geo_service._natural_earth_ports",
        lambda: [{"id": "p1", "name": "Harbor", "kind": "port", "lat": 10.3, "lon": 10.6}],
    )
    monkeypatch.setattr(
        "app.services.geo_service._openflights_airports",
        lambda: [
            {"id": "a1", "name": "IATA Field", "kind": "airport", "lat": 10.2, "lon": 10.2, "iata": "ABC"},
            {"id": "m1", "name": "Air Base", "kind": "military", "lat": 10.1, "lon": 10.1, "iata": None},
        ],
    )
    data = places(10, 10, 11, 11, zoom=6)
    kinds = {item["kind"] for item in data["items"]}
    assert kinds == {"town", "port", "airport", "military"}


def test_format_src_date() -> None:
    assert _format_src_date(20250616) == "2025-06-16"
    assert _format_src_date(99999) is None
    assert _format_src_date(None) is None


def test_radar_tile_url() -> None:
    url = radar_tile_url("https://tilecache.rainviewer.com", "/v2/radar/abc")
    assert url == "https://tilecache.rainviewer.com/v2/radar/abc/256/{z}/{x}/{y}/2/1_1.png"


def test_weather_grid_covers_viewport() -> None:
    cells = sample_weather_grid(50, 30, 60, 40, zoom=6)
    assert 16 <= len(cells) <= 120
    assert min(cell["south"] for cell in cells) <= 50
    assert max(cell["north"] for cell in cells) >= 60
    assert all(-90 <= cell["lat"] <= 90 for cell in cells)


def test_weather_grid_keeps_fine_cells_when_zoomed_in() -> None:
    cells = sample_weather_grid(44.9, 33.9, 45.2, 34.3, zoom=11)
    widths = [cell["east"] - cell["west"] for cell in cells]
    heights = [cell["north"] - cell["south"] for cell in cells]
    assert cells
    assert max(widths) <= 0.11
    assert max(heights) <= 0.11


def test_weather_grid_wraps_antimeridian() -> None:
    cells = sample_weather_grid(-10, 170, 10, -170, zoom=4)
    assert cells
    assert all(-180 <= cell["lon"] <= 180 for cell in cells)


def test_weather_radar_builds_url(monkeypatch) -> None:
    _CACHE.clear()
    _STORE.clear()
    monkeypatch.setattr(
        "app.services.geo_service._get_json",
        lambda *args, **kwargs: {
            "host": "https://tilecache.rainviewer.com",
            "radar": {"past": [{"time": 1, "path": "/v2/radar/abc"}], "nowcast": []},
            "satellite": {"infrared": []},
        },
    )
    data = weather_radar()
    assert data["rain_url"].endswith("/v2/radar/abc/256/{z}/{x}/{y}/2/1_1.png")
    assert data["clouds_url"] is None


def test_weather_field_reads_planet_store() -> None:
    _STORE.clear()
    _put_store(
        "weather",
        {
            "items": [
                {
                    "lat": 55.0,
                    "lon": 37.0,
                    "kind": "weather",
                    "cloud_cover": 80,
                    "wind_speed": 5.0,
                    "storm": False,
                },
                {
                    "lat": -30.0,
                    "lon": 150.0,
                    "kind": "weather",
                    "cloud_cover": 10,
                    "wind_speed": 2.0,
                    "storm": False,
                },
            ],
            "grid": {"dlat": 12, "dlon": 12, "rows": 2, "cols": 2},
            "source": "Open-Meteo",
        },
    )
    data = weather_field(50, 30, 60, 40, zoom=6)
    assert data["source"] == "Open-Meteo"
    assert len(data["items"]) == 1
    assert data["items"][0]["lat"] == 55.0


def test_weather_field_warming_without_store() -> None:
    _STORE.clear()
    data = weather_field(50, 30, 60, 40, zoom=6)
    assert data["items"] == []
    assert data["reason"] == "warming"
