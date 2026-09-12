from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.models.entity import Entity
from app.models.investigation import Investigation
from app.schemas.investigation import InvestigationCreate, InvestigationUpdate


class InvestigationService:
    def __init__(self, db: Session) -> None:
        self.db = db

    def _base_query(self):
        return select(Investigation).options(selectinload(Investigation.entities))

    def list_all(self) -> list[Investigation]:
        return list(self.db.scalars(self._base_query().order_by(Investigation.created_at.desc())))

    def get(self, investigation_id: str) -> Investigation | None:
        return self.db.scalar(self._base_query().where(Investigation.id == investigation_id))

    def _attach_entities(self, investigation: Investigation, entity_ids: list[str]) -> None:
        if not entity_ids:
            investigation.entities = []
            return
        entities = list(self.db.scalars(select(Entity).where(Entity.id.in_(entity_ids))))
        investigation.entities = entities

    def create(self, payload: InvestigationCreate) -> Investigation:
        data = payload.model_dump(exclude={"entity_ids"})
        investigation = Investigation(**data)
        self._attach_entities(investigation, payload.entity_ids)
        self.db.add(investigation)
        self.db.commit()
        self.db.refresh(investigation)
        return self.get(investigation.id)

    def update(self, investigation_id: str, payload: InvestigationUpdate) -> Investigation | None:
        investigation = self.get(investigation_id)
        if investigation is None:
            return None
        data = payload.model_dump(exclude_unset=True, exclude={"entity_ids"})
        for field, value in data.items():
            setattr(investigation, field, value)
        if payload.entity_ids is not None:
            self._attach_entities(investigation, payload.entity_ids)
        self.db.commit()
        self.db.refresh(investigation)
        return self.get(investigation.id)

    def delete(self, investigation_id: str) -> bool:
        investigation = self.get(investigation_id)
        if investigation is None:
            return False
        self.db.delete(investigation)
        self.db.commit()
        return True
