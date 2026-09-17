from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime


# raw data exactly how the API gave us
@dataclass
class RawRecord:
    source_id: str
    payload: dict

# standard format we want to standardize
@dataclass
class CanonicalRecall:
    source_id: str
    brand: str | None
    product_name: str
    hazard_description: str | None
    hazard_classification: str | None
    status: str
    date_initiated: datetime | None
    date_terminated: datetime | None
    geographic_scope: str | None
    upcs: list[str]


#Abstract Base Cllass, meaning every recall source has to follow these rules
# 1. 
class RecallSourceAdapter(ABC):
    source_name: str

    @abstractmethod
    def fetch(self, since: datetime | None) -> list[RawRecord]:
        ...

    @abstractmethod
    def normalize(self, raw: RawRecord) -> CanonicalRecall:
        ...