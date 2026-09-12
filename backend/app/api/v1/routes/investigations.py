from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status

from app.api.deps import get_investigation_service
from app.schemas.investigation import InvestigationCreate, InvestigationRead, InvestigationUpdate
from app.services.investigation_service import InvestigationService

router = APIRouter()
Service = Annotated[InvestigationService, Depends(get_investigation_service)]


@router.get("", response_model=list[InvestigationRead])
def list_investigations(service: Service) -> list[InvestigationRead]:
    return service.list_all()


@router.post("", response_model=InvestigationRead, status_code=status.HTTP_201_CREATED)
def create_investigation(payload: InvestigationCreate, service: Service) -> InvestigationRead:
    return service.create(payload)


@router.get("/{investigation_id}", response_model=InvestigationRead)
def get_investigation(investigation_id: str, service: Service) -> InvestigationRead:
    investigation = service.get(investigation_id)
    if investigation is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Investigation not found")
    return investigation


@router.patch("/{investigation_id}", response_model=InvestigationRead)
def update_investigation(
    investigation_id: str,
    payload: InvestigationUpdate,
    service: Service,
) -> InvestigationRead:
    investigation = service.update(investigation_id, payload)
    if investigation is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Investigation not found")
    return investigation


@router.delete("/{investigation_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_investigation(investigation_id: str, service: Service) -> None:
    if not service.delete(investigation_id):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Investigation not found")
