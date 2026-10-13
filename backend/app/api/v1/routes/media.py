from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from fastapi.responses import Response

from app.api.deps import get_media_service
from app.schemas.media import MediaPinRead
from app.services.media_geo import (
    MediaGeo,
    blank_preview,
    decode_image,
    detect_kind,
    extract_embedded_exif,
    normalize_preview,
    read_video,
)
from app.services.media_service import MediaService

router = APIRouter()
Service = Annotated[MediaService, Depends(get_media_service)]

IMAGE_LIMIT = 40 * 1024 * 1024
VIDEO_LIMIT = 200 * 1024 * 1024
HEAD_LIMIT = 8 * 1024 * 1024
TAIL_LIMIT = 16 * 1024 * 1024
PREVIEW_LIMIT = 4 * 1024 * 1024
READ_SIZE = 1024 * 1024


@router.get("", response_model=list[MediaPinRead])
def list_media(service: Service) -> list[MediaPinRead]:
    return service.list_all()


@router.post("", response_model=MediaPinRead, status_code=status.HTTP_201_CREATED)
async def create_media(
    service: Service,
    file: Annotated[UploadFile, File()],
    preview: Annotated[UploadFile | None, File()] = None,
) -> MediaPinRead:
    try:
        kind, image_bytes, video_parts = await _load_upload(file)
        preview_bytes = await _read_optional(preview, PREVIEW_LIMIT, "Превью больше 4 МБ")
        if kind == "image":
            geo, thumb = _image_result(image_bytes or b"", preview_bytes)
        else:
            geo = read_video(video_parts)
            thumb = _safe_preview(preview_bytes) or blank_preview()
        return service.create(_safe_name(file.filename), kind, geo, thumb)
    finally:
        await file.close()
        if preview is not None:
            await preview.close()


@router.get("/{media_id}/preview")
def get_preview(media_id: str, service: Service) -> Response:
    row = service.get(media_id)
    if row is None or not row.preview:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Превью не найдено")
    return Response(content=row.preview, media_type="image/jpeg", headers={"Cache-Control": "no-store"})


@router.delete("/{media_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_media(media_id: str, service: Service) -> None:
    if not service.delete(media_id):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Файл не найден")


def _image_result(data: bytes, preview_bytes: bytes | None) -> tuple[MediaGeo, bytes]:
    try:
        return decode_image(data)
    except ValueError:
        geo = extract_embedded_exif(data) or MediaGeo()
        thumb = _safe_preview(preview_bytes)
        if thumb is None and not geo.has_location:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Не удалось прочитать изображение") from None
        return geo, thumb or blank_preview()


def _safe_preview(data: bytes | None) -> bytes | None:
    if not data:
        return None
    try:
        return normalize_preview(data)
    except Exception:
        return None


def _safe_name(filename: str | None) -> str:
    name = Path(filename or "file").name.replace("\x00", "").strip()
    return (name or "file")[:180]


async def _load_upload(upload: UploadFile) -> tuple[str, bytes | None, list[bytes]]:
    first = await upload.read(64 * 1024)
    if not first:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Пустой файл")
    kind = detect_kind(upload.filename or "", upload.content_type or "", first)
    if kind is None:
        raise HTTPException(status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE, detail="Нужно изображение или видео")
    if kind == "image":
        rest = await _read_rest(upload, IMAGE_LIMIT - len(first), "Изображение больше 40 МБ")
        return kind, first + rest, []

    head = bytearray(first)
    tail = bytearray()
    total = len(first)
    while True:
        chunk = await upload.read(READ_SIZE)
        if not chunk:
            break
        total += len(chunk)
        if total > VIDEO_LIMIT:
            raise HTTPException(status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, detail="Видео больше 200 МБ")
        if len(head) < HEAD_LIMIT:
            need = HEAD_LIMIT - len(head)
            head.extend(chunk[:need])
            chunk = chunk[need:]
        if not chunk:
            continue
        tail.extend(chunk)
        if len(tail) > TAIL_LIMIT:
            del tail[: len(tail) - TAIL_LIMIT]

    parts = [bytes(head)]
    if tail:
        parts.append(bytes(tail))
        parts.append(bytes(head[-512:]) + bytes(tail[:512]))
    return kind, None, parts


async def _read_optional(upload: UploadFile | None, limit: int, message: str) -> bytes | None:
    if upload is None:
        return None
    data = await upload.read(64 * 1024)
    if not data:
        return None
    data += await _read_rest(upload, limit - len(data), message)
    return data


async def _read_rest(upload: UploadFile, remaining: int, message: str) -> bytes:
    if remaining < 0:
        raise HTTPException(status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, detail=message)
    chunks = []
    while remaining:
        chunk = await upload.read(min(READ_SIZE, remaining + 1))
        if not chunk:
            break
        if len(chunk) > remaining:
            raise HTTPException(status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, detail=message)
        chunks.append(chunk)
        remaining -= len(chunk)
    return b"".join(chunks)
