from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

Fragility = Literal["BAJA", "MEDIA", "ALTA"]
Algorithm = Literal["FIRST_FIT_3D", "MINIMAX_MAXIMIN_3D"]
Strategy = Literal["MINIMAX", "MAXIMIN"]


class Package(BaseModel):
    id: int
    codigo: str
    descripcion: str
    destino: str
    orden_entrega: int
    prioridad: int
    fragilidad: Fragility
    peso_kg: float
    largo_cm: float
    ancho_cm: float
    alto_cm: float
    permite_rotacion: bool = True


class Truck(BaseModel):
    id: str
    nombre: str
    largo_cm: float
    ancho_cm: float
    alto_cm: float
    capacidad_peso_kg: float


class RunRequest(BaseModel):
    truck_id: str = "CAMION_A"
    package_limit: int = Field(default=50, ge=1, le=50)
    allow_rotation: bool = True
    strategy: Strategy = "MINIMAX"


class Placement(BaseModel):
    package_id: int
    codigo: str
    loading_sequence: int
    delivery_order: int
    x: float
    y: float
    z: float
    width: float
    height: float
    depth: float
    orientation: str
    destination: str
    fragility: Fragility
    peso_kg: float
    descripcion: str


class Metrics(BaseModel):
    execution_ms: int
    truck_volume_cm3: float
    used_volume_cm3: float
    utilization_percent: float
    placed_count: int
    unplaced_count: int
    total_weight_kg: float
    overlap_violations: int
    boundary_violations: int
    delivery_order_penalty: float
    rotation_count: int
    average_delivery_distance_cm: float


class SimulationResponse(BaseModel):
    simulation_id: str
    algorithm: Algorithm
    strategy: str | None = None
    truck: Truck
    input_count: int
    ordered_packages: list[Package]
    placements: list[Placement]
    unplaced_packages: list[Package]
    metrics: Metrics

    model_config = ConfigDict(from_attributes=True)


class ScenarioResponse(BaseModel):
    packages: list[Package]
    trucks: list[Truck]
    coordinate_system: dict[str, str]
