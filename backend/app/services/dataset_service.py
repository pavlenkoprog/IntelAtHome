from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.dataset import Dataset
from app.schemas.dataset import DatasetCreate, DatasetUpdate


class DatasetService:
    def __init__(self, db: Session) -> None:
        self.db = db

    def list_all(self) -> list[Dataset]:
        return list(self.db.scalars(select(Dataset).order_by(Dataset.created_at.desc())))

    def get(self, dataset_id: str) -> Dataset | None:
        return self.db.get(Dataset, dataset_id)

    def create(self, payload: DatasetCreate) -> Dataset:
        dataset = Dataset(**payload.model_dump())
        self.db.add(dataset)
        self.db.commit()
        self.db.refresh(dataset)
        return dataset

    def update(self, dataset_id: str, payload: DatasetUpdate) -> Dataset | None:
        dataset = self.get(dataset_id)
        if dataset is None:
            return None
        for field, value in payload.model_dump(exclude_unset=True).items():
            setattr(dataset, field, value)
        self.db.commit()
        self.db.refresh(dataset)
        return dataset

    def delete(self, dataset_id: str) -> bool:
        dataset = self.get(dataset_id)
        if dataset is None:
            return False
        self.db.delete(dataset)
        self.db.commit()
        return True
