from dataclasses import dataclass

from app.modules.optimization_poc.schema import Truck
from app.modules.optimization_poc.utils.constants import MAX_ROUTE_RANK


@dataclass(frozen=True)
class Truck3D:
    id: str
    nombre: str
    largo_cm: float
    ancho_cm: float
    alto_cm: float
    capacidad_peso_kg: float

    @property
    def volume(self) -> float:
        return self.ancho_cm * self.alto_cm * self.largo_cm

    @property
    def length(self) -> float:
        return self.largo_cm

    @property
    def width(self) -> float:
        return self.ancho_cm

    @property
    def height(self) -> float:
        return self.alto_cm

    @property
    def max_weight(self) -> float:
        return self.capacidad_peso_kg

    @classmethod
    def from_schema(cls, truck: Truck) -> "Truck3D":
        return cls(**truck.model_dump())

    def to_schema(self) -> Truck:
        return Truck(**self.__dict__)


def truck_volume(truck: Truck3D | Truck) -> float:
    return getattr(truck, "volume", truck.ancho_cm * truck.alto_cm * truck.largo_cm)


def route_ratio_from_rank(rank: int) -> float:
    return rank / max(MAX_ROUTE_RANK, 1)


def target_z_from_rank(rank: int, truck: Truck3D | Truck, depth: float) -> float:
    available_depth = max(truck.largo_cm - depth, 0.0)
    ratio = route_ratio_from_rank(rank)
    target_depth = truck.largo_cm * (1.0 - ratio)
    return round(min(target_depth, available_depth), 3)
