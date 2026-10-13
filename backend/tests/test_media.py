import io

import pytest
from fastapi.testclient import TestClient
from PIL import Image
from PIL.ExifTags import GPS
from PIL.TiffImagePlugin import IFDRational

from app.services.media_geo import read_video


def _jpeg_with_gps() -> bytes:
    image = Image.new("RGB", (32, 24), (20, 40, 80))
    exif = image.getexif()
    gps = exif.get_ifd(0x8825)
    gps[GPS.GPSLatitudeRef] = "N"
    gps[GPS.GPSLatitude] = (IFDRational(55), IFDRational(45), IFDRational(208, 10))
    gps[GPS.GPSLongitudeRef] = "E"
    gps[GPS.GPSLongitude] = (IFDRational(37), IFDRational(37), IFDRational(2))
    gps[GPS.GPSAltitudeRef] = 0
    gps[GPS.GPSAltitude] = IFDRational(156)
    exif.get_ifd(0x8769)[0x9003] = "2024:06:01 12:30:00"
    buffer = io.BytesIO()
    image.save(buffer, format="JPEG", exif=exif)
    return buffer.getvalue()


def _png() -> bytes:
    image = Image.new("RGB", (16, 16), (10, 20, 30))
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


def test_jpeg_exif_is_stored_as_preview_only(client: TestClient) -> None:
    original = _jpeg_with_gps()
    response = client.post("/api/v1/media", files={"file": ("phone.jpg", original, "image/jpeg")})
    assert response.status_code == 201
    body = response.json()
    assert body["filename"] == "phone.jpg"
    assert body["media_type"] == "image"
    assert body["latitude"] == pytest.approx(55.7557778, abs=1e-4)
    assert body["longitude"] == pytest.approx(37.6172222, abs=1e-4)
    assert body["altitude"] == pytest.approx(156)
    assert body["taken_at"] == "2024-06-01T12:30:00"
    assert body["gps_source"] == "exif"
    assert "preview" not in body

    preview = client.get(f"/api/v1/media/{body['id']}/preview")
    assert preview.status_code == 200
    assert preview.headers["content-type"].startswith("image/jpeg")
    assert preview.content.startswith(b"\xff\xd8")
    assert preview.content != original

    listed = client.get("/api/v1/media")
    assert listed.status_code == 200
    assert listed.json()[0]["id"] == body["id"]

    assert client.delete(f"/api/v1/media/{body['id']}").status_code == 204
    assert client.get(f"/api/v1/media/{body['id']}/preview").status_code == 404
    assert client.get("/api/v1/media").json() == []


def test_png_without_gps_keeps_jpeg_preview(client: TestClient) -> None:
    original = _png()
    response = client.post("/api/v1/media", files={"file": ("scan.png", original, "image/png")})
    assert response.status_code == 201
    body = response.json()
    assert body["latitude"] is None
    assert body["longitude"] is None
    assert body["gps_source"] is None
    preview = client.get(f"/api/v1/media/{body['id']}/preview").content
    assert preview.startswith(b"\xff\xd8")
    assert preview != original


def test_video_quicktime_location(client: TestClient) -> None:
    sample = b"\x00\x00\x00\x20ftypisom" + b"\x00" * 32 + b"\xa9xyz\x00\x00+37.3317-122.0307+5.000/\x00"
    response = client.post("/api/v1/media", files={"file": ("clip.mp4", sample, "video/mp4")})
    assert response.status_code == 201
    body = response.json()
    assert body["media_type"] == "video"
    assert body["latitude"] == pytest.approx(37.3317)
    assert body["longitude"] == pytest.approx(-122.0307)
    assert body["altitude"] == pytest.approx(5)
    assert body["gps_source"] == "quicktime"
    assert client.get(f"/api/v1/media/{body['id']}/preview").content.startswith(b"\xff\xd8")


def test_unsupported_and_empty_files(client: TestClient) -> None:
    rejected = client.post("/api/v1/media", files={"file": ("notes.txt", b"hello", "text/plain")})
    assert rejected.status_code == 415
    empty = client.post("/api/v1/media", files={"file": ("empty.jpg", b"", "image/jpeg")})
    assert empty.status_code == 400


def test_container_locations_and_false_match() -> None:
    degrees = read_video([b"\xa9xyz+5545.3480+03737.0380/"])
    assert degrees.latitude == pytest.approx(55 + 45.348 / 60)
    assert degrees.longitude == pytest.approx(37 + 37.038 / 60)

    xmp = (
        b"<exif:GPSLatitude>55,45.348N</exif:GPSLatitude>"
        b"<exif:GPSLongitude>37,37.038E</exif:GPSLongitude>"
    )
    tagged = read_video([b"ftyp" + xmp])
    assert tagged.gps_source == "xmp"
    assert tagged.latitude == pytest.approx(55 + 45.348 / 60)

    stray = b"+55.7558+037.6173/" + b"\x00" * 500 + b"\xa9xyz"
    assert read_video([stray]).latitude is None
