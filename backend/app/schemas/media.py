from datetime import datetime

from app.schemas.common import ORMModel


class MediaPinRead(ORMModel):
    id: str
    filename: str
    media_type: str
    latitude: float | None
    longitude: float | None
    altitude: float | None
    taken_at: str | None
    gps_source: str | None
    created_at: datetime
    updated_at: datetime
