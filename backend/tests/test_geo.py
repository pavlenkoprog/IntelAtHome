from app.services.geo_service import (
    _CACHE,
    _format_src_date,
    flights,
    places,
    radar_tile_url,
    sample_weather_grid,
    weather_field,
    weather_radar,
)


def test_places_require_zoom() -> None:
    assert places(10, 10, 12, 12, zoom=3)["items"] == []


def test_flights_reject_huge_bbox() -> None:
    assert flights(-80, -170, 80, 170)["items"] == []


def test_format_src_date() -> None:
    assert _format_src_date(20250616) == "2025-06-16"
    assert _format_src_date(99999) is None
    assert _format_src_date(None) is None


def test_radar_tile_url() -> None:
    url = radar_tile_url("https://tilecache.rainviewer.com", "/v2/radar/abc")
    assert url == "https://tilecache.rainviewer.com/v2/radar/abc/256/{z}/{x}/{y}/2/1_1.png"


def test_weather_grid_covers_viewport() -> None:
    cells = sample_weather_grid(50, 30, 60, 40, zoom=6)
    assert len(cells) == 70
    assert all(-90 <= cell["lat"] <= 90 for cell in cells)


def test_weather_grid_wraps_antimeridian() -> None:
    cells = sample_weather_grid(-10, 170, 10, -170, zoom=4)
    assert cells
    assert all(-180 <= cell["lon"] <= 180 for cell in cells)


def test_weather_radar_builds_url(monkeypatch) -> None:
    _CACHE.clear()
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


def test_weather_field_maps_open_meteo(monkeypatch) -> None:
    _CACHE.clear()
    monkeypatch.setattr(
        "app.services.geo_service._get_json",
        lambda *args, **kwargs: [
            {
                "current": {
                    "weather_code": 95,
                    "cloud_cover": 90,
                    "precipitation": 2.1,
                    "wind_speed_10m": 8.4,
                    "wind_direction_10m": 270,
                }
            }
        ]
        * 24,
    )
    data = weather_field(50, 30, 60, 40, zoom=3)
    assert data["source"] == "Open-Meteo"
    assert data["items"]
    assert data["items"][0]["storm"] is True
    assert data["items"][0]["wind_speed"] == 8.4


def test_weather_field_accepts_world_wrap(monkeypatch) -> None:
    _CACHE.clear()
    monkeypatch.setattr(
        "app.services.geo_service._get_json",
        lambda *args, **kwargs: {
            "current": {
                "weather_code": 3,
                "cloud_cover": 70,
                "precipitation": 0.2,
                "wind_speed_10m": 4.0,
                "wind_direction_10m": 90,
            }
        },
    )
    data = weather_field(-85, -220, 85, 220, zoom=2)
    assert data.get("reason") != "bbox_too_large"
    assert data["items"]
