from datetime import datetime

from pydantic import Field

from app.schemas.common import ORMModel
from app.schemas.entity import EntityRead


class InvestigationCreate(ORMModel):
    title: str = Field(min_length=1, max_length=255)
    description: str = ""
    status: str = "open"
    entity_ids: list[str] = Field(default_factory=list)


class InvestigationUpdate(ORMModel):
    title: str | None = Field(default=None, min_length=1, max_length=255)
    description: str | None = None
    status: str | None = None
    entity_ids: list[str] | None = None


class InvestigationRead(ORMModel):
    id: str
    title: str
    description: str
    status: str
    entities: list[EntityRead] = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime
