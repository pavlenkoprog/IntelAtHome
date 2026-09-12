from datetime import datetime

from pydantic import Field

from app.schemas.common import ORMModel


class EntityCreate(ORMModel):
    name: str = Field(min_length=1, max_length=255)
    entity_type: str = "unknown"
    description: str = ""
    properties: dict = Field(default_factory=dict)
    dataset_id: str | None = None


class EntityUpdate(ORMModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    entity_type: str | None = None
    description: str | None = None
    properties: dict | None = None
    dataset_id: str | None = None


class EntityRead(ORMModel):
    id: str
    name: str
    entity_type: str
    description: str
    properties: dict
    dataset_id: str | None
    created_at: datetime
    updated_at: datetime
