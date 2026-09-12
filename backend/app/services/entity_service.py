from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.entity import Entity
from app.schemas.entity import EntityCreate, EntityUpdate


class EntityService:
    def __init__(self, db: Session) -> None:
        self.db = db

    def list_all(self, entity_type: str | None = None) -> list[Entity]:
        stmt = select(Entity).order_by(Entity.created_at.desc())
        if entity_type:
            stmt = stmt.where(Entity.entity_type == entity_type)
        return list(self.db.scalars(stmt))

    def get(self, entity_id: str) -> Entity | None:
        return self.db.get(Entity, entity_id)

    def create(self, payload: EntityCreate) -> Entity:
        entity = Entity(**payload.model_dump())
        self.db.add(entity)
        self.db.commit()
        self.db.refresh(entity)
        return entity

    def update(self, entity_id: str, payload: EntityUpdate) -> Entity | None:
        entity = self.get(entity_id)
        if entity is None:
            return None
        for field, value in payload.model_dump(exclude_unset=True).items():
            setattr(entity, field, value)
        self.db.commit()
        self.db.refresh(entity)
        return entity

    def delete(self, entity_id: str) -> bool:
        entity = self.get(entity_id)
        if entity is None:
            return False
        self.db.delete(entity)
        self.db.commit()
        return True
