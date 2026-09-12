from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status

from app.api.deps import get_dataset_service
from app.schemas.dataset import DatasetCreate, DatasetRead, DatasetUpdate
from app.services.dataset_service import DatasetService

router = APIRouter()
Service = Annotated[DatasetService, Depends(get_dataset_service)]


@router.get("", response_model=list[DatasetRead])
def list_datasets(service: Service) -> list[DatasetRead]:
    return service.list_all()


@router.post("", response_model=DatasetRead, status_code=status.HTTP_201_CREATED)
def create_dataset(payload: DatasetCreate, service: Service) -> DatasetRead:
    return service.create(payload)


@router.get("/{dataset_id}", response_model=DatasetRead)
def get_dataset(dataset_id: str, service: Service) -> DatasetRead:
    dataset = service.get(dataset_id)
    if dataset is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Dataset not found")
    return dataset


@router.patch("/{dataset_id}", response_model=DatasetRead)
def update_dataset(dataset_id: str, payload: DatasetUpdate, service: Service) -> DatasetRead:
    dataset = service.update(dataset_id, payload)
    if dataset is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Dataset not found")
    return dataset


@router.delete("/{dataset_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_dataset(dataset_id: str, service: Service) -> None:
    if not service.delete(dataset_id):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Dataset not found")
