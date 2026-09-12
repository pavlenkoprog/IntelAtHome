from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.api.deps import get_entity_service
from app.schemas.entity import EntityCreate, EntityRead, EntityUpdate
from app.services.entity_service import EntityService

router = APIRouter()
Service = Annotated[EntityService, Depends(get_entity_service)]


@router.get("", response_model=list[EntityRead])
def list_entities(
    service: Service,
    entity_type: Annotated[str | None, Query()] = None,
) -> list[EntityRead]:
    return service.list_all(entity_type=entity_type)


@router.post("", response_model=EntityRead, status_code=status.HTTP_201_CREATED)
def create_entity(payload: EntityCreate, service: Service) -> EntityRead:
    return service.create(payload)


@router.get("/{entity_id}", response_model=EntityRead)
def get_entity(entity_id: str, service: Service) -> EntityRead:
    entity = service.get(entity_id)
    if entity is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Entity not found")
    return entity


@router.patch("/{entity_id}", response_model=EntityRead)
def update_entity(entity_id: str, payload: EntityUpdate, service: Service) -> EntityRead:
    entity = service.update(entity_id, payload)
    if entity is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Entity not found")
    return entity


@router.delete("/{entity_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_entity(entity_id: str, service: Service) -> None:
    if not service.delete(entity_id):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Entity not found")
