from datetime import datetime

from pydantic import Field

from app.schemas.common import ORMModel


class DatasetCreate(ORMModel):
    name: str = Field(min_length=1, max_length=255)
    source_type: str = "manual"
    description: str = ""


class DatasetUpdate(ORMModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    source_type: str | None = None
    description: str | None = None


class DatasetRead(ORMModel):
    id: str
    name: str
    source_type: str
    description: str
    created_at: datetime
    updated_at: datetime
