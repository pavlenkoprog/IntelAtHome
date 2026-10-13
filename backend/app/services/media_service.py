from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.media_pin import MediaPin
from app.services.media_geo import MediaGeo


class MediaService:
    def __init__(self, db: Session) -> None:
        self.db = db

    def list_all(self) -> list[MediaPin]:
        stmt = select(MediaPin).order_by(MediaPin.created_at.desc(), MediaPin.id.desc())
        return list(self.db.scalars(stmt))

    def get(self, media_id: str) -> MediaPin | None:
        return self.db.get(MediaPin, media_id)

    def create(self, filename: str, media_type: str, geo: MediaGeo, preview: bytes) -> MediaPin:
        row = MediaPin(
            filename=filename,
            media_type=media_type,
            latitude=geo.latitude,
            longitude=geo.longitude,
            altitude=geo.altitude,
            taken_at=geo.taken_at,
            gps_source=geo.gps_source if geo.has_location else None,
            preview=preview,
        )
        self.db.add(row)
        self.db.commit()
        self.db.refresh(row)
        return row

    def delete(self, media_id: str) -> bool:
        row = self.get(media_id)
        if row is None:
            return False
        self.db.delete(row)
        self.db.commit()
        return True
