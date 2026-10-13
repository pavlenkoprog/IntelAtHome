import uuid

from sqlalchemy import Float, LargeBinary, String
from sqlalchemy.orm import Mapped, deferred, mapped_column

from app.models.base import Base, TimestampMixin


class MediaPin(TimestampMixin, Base):
    __tablename__ = "media_pins"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    filename: Mapped[str] = mapped_column(String(180), nullable=False)
    media_type: Mapped[str] = mapped_column(String(16), nullable=False)
    latitude: Mapped[float | None] = mapped_column(Float, nullable=True)
    longitude: Mapped[float | None] = mapped_column(Float, nullable=True)
    altitude: Mapped[float | None] = mapped_column(Float, nullable=True)
    taken_at: Mapped[str | None] = mapped_column(String(32), nullable=True)
    gps_source: Mapped[str | None] = mapped_column(String(16), nullable=True)
    preview: Mapped[bytes] = deferred(mapped_column(LargeBinary, nullable=False))
