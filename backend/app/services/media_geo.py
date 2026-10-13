import io
import re
from dataclasses import dataclass, replace

from PIL import Image, ImageOps

GPS_IFD = 0x8825
EXIF_IFD = 0x8769
TAG_LAT_REF = 1
TAG_LAT = 2
TAG_LON_REF = 3
TAG_LON = 4
TAG_ALT_REF = 5
TAG_ALT = 6
TAG_DATETIME_ORIGINAL = 0x9003

_MARKERS = (b"\xa9xyz", b"location.ISO6709", b"ISO6709")
_ISO6709 = re.compile(
    r"([+-])(\d{2,6}(?:\.\d+)?)([+-])(\d{3,7}(?:\.\d+)?)(?:([+-])(\d+(?:\.\d+)?))?/"
)
_XMP_LAT = re.compile(
    rb"GPSLatitude(?!Ref)[^0-9+\-]{0,48}([+-]?\d+(?:\.\d+)?)(?:[, ]+(\d+(?:\.\d+)?))?(?:[, ]+(\d+(?:\.\d+)?))?\s*([NSns])?"
)
_XMP_LON = re.compile(
    rb"GPSLongitude(?!Ref)[^0-9+\-]{0,48}([+-]?\d+(?:\.\d+)?)(?:[, ]+(\d+(?:\.\d+)?))?(?:[, ]+(\d+(?:\.\d+)?))?\s*([EWew])?"
)
_XMP_ALT = re.compile(rb"GPSAltitude(?!Ref)[^0-9+\-]{0,32}([+-]?\d+(?:\.\d+)?)")
_HEIF_BRANDS = {b"heic", b"heix", b"heif", b"mif1", b"msf1", b"avif"}
_IMAGE_EXT = (".jpg", ".jpeg", ".png", ".webp", ".gif", ".tif", ".tiff", ".heic", ".heif", ".avif")
_VIDEO_EXT = (".mp4", ".mov", ".m4v", ".webm", ".mkv", ".avi", ".3gp", ".3g2")


@dataclass(frozen=True)
class MediaGeo:
    latitude: float | None = None
    longitude: float | None = None
    altitude: float | None = None
    taken_at: str | None = None
    gps_source: str | None = None

    @property
    def has_location(self) -> bool:
        return self.latitude is not None and self.longitude is not None


def detect_kind(filename: str, content_type: str, head: bytes) -> str | None:
    if head.startswith(b"\xff\xd8\xff") or head.startswith(b"\x89PNG\r\n\x1a\n") or head.startswith(b"GIF8"):
        return "image"
    if len(head) >= 12 and head.startswith(b"RIFF") and head[8:12] == b"WEBP":
        return "image"
    if len(head) >= 12 and head[4:8] == b"ftyp":
        return "image" if head[8:12] in _HEIF_BRANDS else "video"

    name = filename.lower()
    media_type = content_type.split(";", 1)[0].strip().lower()
    if media_type.startswith("image/") or name.endswith(_IMAGE_EXT):
        return "image"
    if media_type.startswith("video/") or name.endswith(_VIDEO_EXT):
        return "video"
    return None


def decode_image(data: bytes) -> tuple[MediaGeo, bytes]:
    try:
        with Image.open(io.BytesIO(data)) as image:
            geo = _gps_from_pillow(image) or extract_embedded_exif(data) or MediaGeo()
            return geo, make_preview(image)
    except Exception as exc:
        raise ValueError("Не удалось прочитать изображение") from exc


def read_video(parts: list[bytes]) -> MediaGeo:
    quicktime = _read_iso6709(parts)
    xmp = _read_xmp(parts)
    exif = _first_exif(parts)
    return _merge(quicktime, _merge(xmp, exif))


def extract_embedded_exif(data: bytes) -> MediaGeo | None:
    marker = b"Exif\x00\x00"
    start = 0
    while True:
        index = data.find(marker, start)
        if index < 0:
            return None
        parsed = _parse_tiff_gps(data[index + len(marker) :])
        if parsed and (parsed.has_location or parsed.taken_at):
            return parsed
        start = index + len(marker)


def normalize_preview(data: bytes) -> bytes:
    with Image.open(io.BytesIO(data)) as image:
        return make_preview(image)


def blank_preview() -> bytes:
    image = Image.new("RGB", (72, 54), (18, 22, 31))
    return _jpeg_bytes(image)


def make_preview(image: Image.Image) -> bytes:
    frame = ImageOps.exif_transpose(image) or image
    frame = frame.convert("RGB")
    frame.thumbnail((360, 360))
    return _jpeg_bytes(frame)


def _jpeg_bytes(image: Image.Image) -> bytes:
    buffer = io.BytesIO()
    image.save(buffer, format="JPEG", quality=72, optimize=True)
    return buffer.getvalue()


def _merge(primary: MediaGeo | None, extra: MediaGeo | None) -> MediaGeo:
    if primary and primary.has_location:
        if extra and extra.taken_at and not primary.taken_at:
            return replace(primary, taken_at=extra.taken_at)
        return primary
    if extra and extra.has_location:
        return extra
    if primary and primary.taken_at:
        return primary
    if extra and extra.taken_at:
        return extra
    return MediaGeo()


def _first_exif(parts: list[bytes]) -> MediaGeo | None:
    for part in parts:
        parsed = extract_embedded_exif(part)
        if parsed and parsed.has_location:
            return parsed
    for part in parts:
        parsed = extract_embedded_exif(part)
        if parsed and parsed.taken_at:
            return parsed
    return None


def _gps_from_pillow(image: Image.Image) -> MediaGeo | None:
    exif = image.getexif()
    if not exif:
        return None
    gps = {int(key): value for key, value in exif.get_ifd(GPS_IFD).items()}
    taken = _normalize_time(_exif_text(exif.get_ifd(EXIF_IFD).get(TAG_DATETIME_ORIGINAL) or exif.get(TAG_DATETIME_ORIGINAL)))
    if not gps:
        return MediaGeo(taken_at=taken) if taken else None

    latitude = _apply_ref(_as_degrees(gps.get(TAG_LAT)), gps.get(TAG_LAT_REF), "S")
    longitude = _apply_ref(_as_degrees(gps.get(TAG_LON)), gps.get(TAG_LON_REF), "W")
    if latitude is None or longitude is None or not (-90 <= latitude <= 90 and -180 <= longitude <= 180):
        return MediaGeo(taken_at=taken) if taken else None

    altitude = _altitude(gps.get(TAG_ALT), gps.get(TAG_ALT_REF))
    return MediaGeo(round(latitude, 7), round(longitude, 7), altitude, taken, "exif")


def _as_degrees(value) -> float | None:
    if value is None or isinstance(value, (bytes, str)):
        return None
    try:
        parts = list(value)
    except TypeError:
        parts = None
    if parts is not None and parts and not isinstance(value, (int, float)):
        try:
            degrees = float(parts[0])
            minutes = float(parts[1]) if len(parts) > 1 else 0.0
            seconds = float(parts[2]) if len(parts) > 2 else 0.0
        except (TypeError, ValueError, IndexError):
            return None
        return degrees + minutes / 60 + seconds / 3600
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _apply_ref(value: float | None, ref, negative: str) -> float | None:
    if value is None:
        return None
    if _ref_text(ref) == negative:
        return -abs(value)
    return value


def _ref_text(ref) -> str:
    if isinstance(ref, bytes):
        text = ref.decode("ascii", errors="ignore")
    else:
        text = str(ref or "")
    return text[:1].upper()


def _altitude(value, ref) -> float | None:
    if value is None:
        return None
    try:
        altitude = float(value)
    except (TypeError, ValueError):
        try:
            altitude = float(value[0])
        except (TypeError, ValueError, IndexError):
            return None
    if isinstance(ref, bytes):
        below = bool(ref) and ref[0] == 1
    else:
        try:
            below = int(ref or 0) == 1
        except (TypeError, ValueError):
            below = False
    if below:
        altitude = -abs(altitude)
    if not -500 <= altitude <= 50_000:
        return None
    return round(altitude, 2)


def _exif_text(value) -> str | None:
    if value is None:
        return None
    if isinstance(value, bytes):
        value = value.decode("ascii", errors="ignore")
    text = str(value).strip("\x00 ").strip()
    return text or None


def _normalize_time(value: str | None) -> str | None:
    if not value:
        return None
    text = value.strip().replace("\x00", "")
    if len(text) < 19 or text[4] != ":" or text[7] != ":":
        return None
    return f"{text[0:4]}-{text[5:7]}-{text[8:10]}T{text[11:19]}"


def _read_iso6709(parts: list[bytes]) -> MediaGeo | None:
    for part in parts:
        for marker in _MARKERS:
            start = 0
            while True:
                index = part.find(marker, start)
                if index < 0:
                    break
                window = part[index : index + 220].decode("latin-1", errors="ignore")
                parsed = _parse_iso_window(window)
                if parsed:
                    return parsed
                start = index + len(marker)
    return None


def _parse_iso_window(text: str) -> MediaGeo | None:
    for match in _ISO6709.finditer(text):
        latitude = _iso_number(match.group(1), match.group(2), "lat")
        longitude = _iso_number(match.group(3), match.group(4), "lon")
        if latitude is None or longitude is None:
            continue
        if not (-90 <= latitude <= 90 and -180 <= longitude <= 180):
            continue
        altitude = None
        if match.group(6):
            altitude = float(f"{match.group(5)}{match.group(6)}")
            if not -500 <= altitude <= 50_000:
                altitude = None
            else:
                altitude = round(altitude, 2)
        return MediaGeo(round(latitude, 7), round(longitude, 7), altitude, None, "quicktime")
    return None


def _iso_number(sign: str, token: str, kind: str) -> float | None:
    whole, dot, frac = token.partition(".")
    base = 2 if kind == "lat" else 3
    if len(whole) not in {base, base + 2, base + 4}:
        return None
    if len(whole) == base:
        value = float(token)
    elif len(whole) == base + 2:
        minutes = float(f"{whole[base:]}{dot}{frac}" if dot else whole[base:])
        if minutes >= 60:
            return None
        value = int(whole[:base]) + minutes / 60
    else:
        minutes = int(whole[base : base + 2])
        seconds = float(f"{whole[base + 2:]}{dot}{frac}" if dot else whole[base + 2 :])
        if minutes >= 60 or seconds >= 60:
            return None
        value = int(whole[:base]) + minutes / 60 + seconds / 3600
    return -value if sign == "-" else value


def _read_xmp(parts: list[bytes]) -> MediaGeo | None:
    for part in parts:
        lat_match = _XMP_LAT.search(part)
        lon_match = _XMP_LON.search(part)
        if not lat_match or not lon_match:
            continue
        latitude = _xmp_degrees(lat_match, "S")
        longitude = _xmp_degrees(lon_match, "W")
        if latitude is None or longitude is None or not (-90 <= latitude <= 90 and -180 <= longitude <= 180):
            continue
        altitude = None
        alt_match = _XMP_ALT.search(part)
        if alt_match:
            altitude = float(alt_match.group(1))
            if b"GPSAltitudeRef" in part and re.search(rb"GPSAltitudeRef[^0-9]{0,16}1", part):
                altitude = -abs(altitude)
            if not -500 <= altitude <= 50_000:
                altitude = None
            else:
                altitude = round(altitude, 2)
        return MediaGeo(round(latitude, 7), round(longitude, 7), altitude, None, "xmp")
    return None


def _xmp_degrees(match: re.Match[bytes], negative: str) -> float | None:
    try:
        degrees = float(match.group(1))
        minutes = float(match.group(2) or 0)
        seconds = float(match.group(3) or 0)
    except ValueError:
        return None
    if match.group(2):
        sign = -1 if degrees < 0 else 1
        degrees = sign * (abs(degrees) + minutes / 60 + seconds / 3600)
    if (match.group(4) or b"").decode("ascii", errors="ignore").upper() == negative:
        degrees = -abs(degrees)
    return degrees


def _parse_tiff_gps(tiff: bytes) -> MediaGeo | None:
    try:
        if len(tiff) < 16 or tiff[:2] not in (b"II", b"MM"):
            return None
        little = tiff[:2] == b"II"
        if _u16(tiff, 2, little) != 42:
            return None
        entries = _read_ifd(tiff, _u32(tiff, 4, little), little)
        if not entries:
            return None
        taken = None
        exif_entry = entries.get(EXIF_IFD)
        if exif_entry:
            exif_entries = _read_ifd(tiff, _u32(exif_entry[2], 0, little), little)
            taken = _normalize_time(_ascii_field(tiff, exif_entries.get(TAG_DATETIME_ORIGINAL), little))
        gps_entry = entries.get(GPS_IFD)
        if not gps_entry:
            return MediaGeo(taken_at=taken) if taken else None
        gps = _read_ifd(tiff, _u32(gps_entry[2], 0, little), little)
        latitude = _gps_angle(tiff, gps, TAG_LAT_REF, TAG_LAT, little, "S")
        longitude = _gps_angle(tiff, gps, TAG_LON_REF, TAG_LON, little, "W")
        if latitude is None or longitude is None or not (-90 <= latitude <= 90 and -180 <= longitude <= 180):
            return MediaGeo(taken_at=taken) if taken else None
        altitude = _gps_altitude(tiff, gps, little)
        return MediaGeo(round(latitude, 7), round(longitude, 7), altitude, taken, "exif")
    except (ValueError, IndexError, OverflowError):
        return None


def _gps_angle(tiff: bytes, gps: dict, ref_tag: int, value_tag: int, little: bool, negative: str) -> float | None:
    degrees = _as_degrees(_rationals(_field_bytes(tiff, gps.get(value_tag), little), little))
    return _apply_ref(degrees, _ascii_field(tiff, gps.get(ref_tag), little), negative)


def _gps_altitude(tiff: bytes, gps: dict, little: bool) -> float | None:
    values = _rationals(_field_bytes(tiff, gps.get(TAG_ALT), little), little)
    if not values:
        return None
    ref = _field_bytes(tiff, gps.get(TAG_ALT_REF), little)
    return _altitude(values[0], ref[:1] if ref else 0)


def _rationals(blob: bytes, little: bool) -> list[float]:
    values = []
    for offset in range(0, len(blob) - 7, 8):
        numerator = _u32(blob, offset, little)
        denominator = _u32(blob, offset + 4, little)
        values.append(0.0 if denominator == 0 else numerator / denominator)
    return values


def _ascii_field(tiff: bytes, entry, little: bool) -> str | None:
    return _exif_text(_field_bytes(tiff, entry, little))


def _field_bytes(tiff: bytes, entry, little: bool) -> bytes:
    if entry is None:
        return b""
    typ, count, raw = entry
    unit = {1: 1, 2: 1, 3: 2, 4: 4, 5: 8, 7: 1, 9: 4, 10: 8}.get(typ, 1)
    size = unit * count
    if size <= 0 or size > 1_048_576:
        return b""
    if size <= 4:
        return raw[:size]
    offset = _u32(raw, 0, little)
    if offset < 0 or offset + size > len(tiff):
        return b""
    return tiff[offset : offset + size]


def _read_ifd(data: bytes, offset: int, little: bool) -> dict:
    if offset < 0 or offset + 2 > len(data):
        return {}
    count = _u16(data, offset, little)
    if count > 256:
        return {}
    entries = {}
    pos = offset + 2
    for _ in range(count):
        if pos + 12 > len(data):
            break
        tag = _u16(data, pos, little)
        typ = _u16(data, pos + 2, little)
        number = _u32(data, pos + 4, little)
        entries[tag] = (typ, number, data[pos + 8 : pos + 12])
        pos += 12
    return entries


def _u16(data: bytes, offset: int, little: bool) -> int:
    if offset < 0 or offset + 2 > len(data):
        raise ValueError("short read")
    return int.from_bytes(data[offset : offset + 2], "little" if little else "big")


def _u32(data: bytes, offset: int, little: bool) -> int:
    if offset < 0 or offset + 4 > len(data):
        raise ValueError("short read")
    return int.from_bytes(data[offset : offset + 4], "little" if little else "big")
