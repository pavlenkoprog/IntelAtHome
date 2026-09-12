import uuid

from sqlalchemy import Column, ForeignKey, String, Table, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin

investigation_entities = Table(
    "investigation_entities",
    Base.metadata,
    Column("investigation_id", String(36), ForeignKey("investigations.id"), primary_key=True),
    Column("entity_id", String(36), ForeignKey("entities.id"), primary_key=True),
)


class Investigation(TimestampMixin, Base):
    __tablename__ = "investigations"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(String(32), default="open", index=True)

    entities: Mapped[list["Entity"]] = relationship(
        secondary=investigation_entities,
        back_populates="investigations",
    )
