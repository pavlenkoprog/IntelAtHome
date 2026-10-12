import json

import httpx

from app.services.geo_service import (
    _CACHE,
    _STORE,
    _format_src_date,
    _parse_adsb,
    _parse_caltrans_cameras,
    _parse_tfl_cameras,
    _parse_satellites,
    _put_store,
    _spread_flights,
    camera_frame,
    cameras,
    flights,
    places,
    radar_tile_url,
    satellites,
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
    assert data["grid"]["dlat"] > 0
    assert data["items"][0]["storm"] is True
    assert data["items"][0]["wind_speed"] == 8.4


def test_weather_field_falls_back_to_metno(monkeypatch) -> None:
    _CACHE.clear()

    def fake_get(url, timeout=20.0, params=None):
        if "open-meteo" in url:
            request = httpx.Request("GET", url)
            response = httpx.Response(429, request=request)
            raise httpx.HTTPStatusError("429", request=request, response=response)
        return {
            "properties": {
                "timeseries": [
                    {
                        "data": {
                            "instant": {
                                "details": {
                                    "cloud_area_fraction": 88,
                                    "wind_speed": 6.2,
                                    "wind_from_direction": 180,
                                }
                            },
                            "next_1_hours": {
                                "summary": {"symbol_code": "heavyrainandthunder"},
                                "details": {"precipitation_amount": 1.4},
                            },
                        }
                    }
                ]
            }
        }

    monkeypatch.setattr("app.services.geo_service._get_json", fake_get)
    data = weather_field(50, 30, 60, 40, zoom=6)
    assert data["source"] == "MET Norway"
    assert data["items"]
    assert data["items"][0]["cloud_cover"] == 88
    assert data["items"][0]["storm"] is True


TFL_IMAGE = "https://s3-eu-west-1.amazonaws.com/jamcams.tfl.gov.uk/00001.00001.jpg"
CALTRANS_IMAGE = "https://cwwp2.dot.ca.gov/data/d7/cctv/image/abc123.jpg"


def test_parse_tfl_cameras() -> None:
    items = _parse_tfl_cameras(
        [
            {
                "id": "JamCams_00001.00001",
                "commonName": "Oxford St",
                "lat": 51.5,
                "lon": -0.1,
                "additionalProperties": [
                    {"key": "available", "value": "true"},
                    {"key": "imageUrl", "value": TFL_IMAGE},
                ],
            },
            {
                "id": "JamCams_bad",
                "lat": 51.5,
                "lon": -0.1,
                "additionalProperties": [
                    {"key": "available", "value": "true"},
                    {"key": "imageUrl", "value": "https://evil.example/cam.jpg"},
                ],
            },
        ]
    )
    assert len(items) == 1
    assert items[0]["id"] == "tfl-00001.00001"
    assert items[0]["kind"] == "camera"
    assert items[0]["image_url"] == TFL_IMAGE


def test_parse_caltrans_cameras() -> None:
    items = _parse_caltrans_cameras(
        {
            "data": [
                {
                    "cctv": {
                        "inService": "true",
                        "location": {
                            "latitude": 34.0,
                            "longitude": -118.2,
                            "locationName": "abc123--I-5 at foo",
                            "nearbyPlace": "Los Angeles",
                        },
                        "imageData": {"static": {"currentImageURL": CALTRANS_IMAGE}},
                    }
                },
                {
                    "cctv": {
                        "inService": "false",
                        "location": {"latitude": 34.1, "longitude": -118.3, "locationName": "off"},
                        "imageData": {"static": {"currentImageURL": CALTRANS_IMAGE}},
                    }
                },
            ]
        },
        7,
    )
    assert len(items) == 1
    assert items[0]["id"] == "ca-d7-abc123"
    assert items[0]["city"] == "Los Angeles"


def test_cameras_zoom_bbox_and_strip_url() -> None:
    _STORE.clear()
    _put_store(
        "cameras",
        {
            "items": [
                {
                    "id": "tfl-in",
                    "name": "In",
                    "kind": "camera",
                    "lat": 51.5,
                    "lon": -0.1,
                    "source": "TfL JamCam",
                    "city": "London",
                    "image_url": TFL_IMAGE,
                },
                {
                    "id": "tfl-out",
                    "name": "Out",
                    "kind": "camera",
                    "lat": 10.0,
                    "lon": 10.0,
                    "source": "TfL JamCam",
                    "city": "London",
                    "image_url": TFL_IMAGE,
                },
            ],
            "source": "TfL JamCam",
        },
    )
    far = cameras(50, -1, 52, 1, zoom=2)
    assert {item["id"] for item in far["items"]} >= {"tfl-in", "tfl-out"}
    data = cameras(50, -1, 52, 1, zoom=8)
    assert [item["id"] for item in data["items"]] == ["tfl-in"]
    assert "image_url" not in data["items"][0]


def test_cameras_world_view_spreads_regions() -> None:
    _STORE.clear()
    london = [
        {
            "id": f"tfl-{i}",
            "name": f"L{i}",
            "kind": "camera",
            "lat": 51.5,
            "lon": -0.1,
            "source": "TfL JamCam",
            "image_url": TFL_IMAGE,
        }
        for i in range(80)
    ]
    california = [
        {
            "id": f"ca-d7-{i}",
            "name": f"C{i}",
            "kind": "camera",
            "lat": 34.0,
            "lon": -118.2,
            "source": "Caltrans",
            "image_url": CALTRANS_IMAGE,
        }
        for i in range(80)
    ]
    _put_store("cameras", {"items": [*london, *california], "source": "TfL / Caltrans"})
    data = cameras(40, 20, 50, 40, zoom=2)
    prefixes = {item["id"].split("-")[0] for item in data["items"]}
    assert prefixes == {"tfl", "ca"}
    assert "image_url" not in data["items"][0]


def test_cameras_warming_without_store() -> None:
    _STORE.clear()
    data = cameras(50, -1, 52, 1, zoom=8)
    assert data["items"] == []
    assert data["reason"] == "warming"


def test_camera_frame_unknown_and_allowlist(monkeypatch) -> None:
    _STORE.clear()
    assert camera_frame("missing") is None
    _put_store(
        "cameras",
        {
            "items": [
                {
                    "id": "evil",
                    "name": "Evil",
                    "kind": "camera",
                    "lat": 1,
                    "lon": 1,
                    "image_url": "https://evil.example/cam.jpg",
                },
                {
                    "id": "tfl-00001.00001",
                    "name": "Oxford St",
                    "kind": "camera",
                    "lat": 51.5,
                    "lon": -0.1,
                    "image_url": TFL_IMAGE,
                },
            ],
            "source": "TfL JamCam",
        },
    )
    assert camera_frame("evil") is None
    monkeypatch.setattr(
        "app.services.geo_service._get_bytes",
        lambda url, timeout=8.0: (b"jpeg-bytes", "image/jpeg"),
    )
    assert camera_frame("tfl-00001.00001") == (b"jpeg-bytes", "image/jpeg")


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


def test_camera_http_routes(client, monkeypatch) -> None:
    snap = {
        "items": [
            {
                "id": "tfl-00001.00001",
                "name": "Oxford St",
                "kind": "camera",
                "lat": 51.5,
                "lon": -0.1,
                "source": "TfL JamCam",
                "city": "London",
                "image_url": TFL_IMAGE,
            }
        ],
        "source": "TfL JamCam",
    }
    monkeypatch.setattr("app.services.geo_service._get_store", lambda name: snap if name == "cameras" else None)
    monkeypatch.setattr(
        "app.services.geo_service._get_bytes",
        lambda url, timeout=8.0: (b"jpeg-bytes", "image/jpeg"),
    )
    listed = client.get(
        "/api/v1/geo/cameras",
        params={"south": 50, "west": -1, "north": 52, "east": 1, "zoom": 8},
    )
    assert listed.status_code == 200
    body = listed.json()
    assert body["items"][0]["id"] == "tfl-00001.00001"
    assert "image_url" not in body["items"][0]

    frame = client.get("/api/v1/geo/cameras/tfl-00001.00001/frame")
    assert frame.status_code == 200
    assert frame.content == b"jpeg-bytes"
    assert frame.headers["content-type"].startswith("image/jpeg")
    assert frame.headers.get("cache-control") == "no-store"
    assert client.get("/api/v1/geo/cameras/missing/frame").status_code == 404


def test_parse_satellites_keeps_known_groups() -> None:
    items = _parse_satellites(
        {
            "items": {
                "satellites": [
                    {
                        "noradId": 31797,
                        "name": "SAR-LUPE 2",
                        "latitude": 14.1,
                        "longitude": 89.5,
                        "altitude": 375.1,
                        "heading": 10,
                        "speed": 7600,
                        "group": "military",
                    },
                    {
                        "noradId": 39084,
                        "name": "LANDSAT 8",
                        "latitude": 1,
                        "longitude": 2,
                        "altitude": 700,
                        "heading": 180,
                        "speed": 7500,
                        "group": "recon",
                    },
                    {"noradId": 3, "name": "SKIP", "latitude": 1, "longitude": 2, "group": "starlink"},
                    {"noradId": 4, "name": "BAD", "group": "military"},
                ]
            }
        }
    )
    assert [item["name"] for item in items] == ["SAR-LUPE 2", "LANDSAT 8"]
    assert items[0]["kind"] == "satellite"
    assert items[0]["group"] == "military"
    assert items[0]["norad"] == 31797
    assert items[0]["altitude"] == 375.1
    assert items[1]["group"] == "recon"


def test_satellites_reads_saved_snapshot() -> None:
    _STORE.clear()
    _put_store(
        "satellites",
        {
            "items": [
                {
                    "id": "31797",
                    "name": "SAR-LUPE 2",
                    "kind": "satellite",
                    "group": "military",
                    "lat": 14.1,
                    "lon": 89.5,
                }
            ],
            "source": "CelesTrak",
        },
    )
    data = satellites()
    assert data["source"] == "CelesTrak"
    assert data["items"][0]["name"] == "SAR-LUPE 2"
    assert "reason" not in data


def test_satellites_warming_without_snapshot() -> None:
    _STORE.clear()
    data = satellites()
    assert data["items"] == []
    assert data["reason"] == "warming"


def test_satellite_snapshot_is_written(tmp_path, monkeypatch) -> None:
    monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)
    monkeypatch.setattr("app.services.geo_service.SNAPSHOT_DIR", tmp_path)
    _put_store(
        "satellites",
        {"items": [{"id": "31797", "name": "SAR-LUPE 2"}], "source": "CelesTrak"},
    )
    saved = json.loads((tmp_path / "satellites.json").read_text(encoding="utf-8"))
    assert saved["source"] == "CelesTrak"
    assert saved["items"][0]["name"] == "SAR-LUPE 2"
    assert "updated" in saved
