from typing import Annotated

from fastapi import Depends
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.services.dataset_service import DatasetService
from app.services.entity_service import EntityService
from app.services.investigation_service import InvestigationService
from app.services.media_service import MediaService

DbSession = Annotated[Session, Depends(get_db)]


def get_dataset_service(db: DbSession) -> DatasetService:
    return DatasetService(db)


def get_entity_service(db: DbSession) -> EntityService:
    return EntityService(db)


def get_investigation_service(db: DbSession) -> InvestigationService:
    return InvestigationService(db)


def get_media_service(db: DbSession) -> MediaService:
    return MediaService(db)
