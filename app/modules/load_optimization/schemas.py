from pydantic import BaseModel
from typing import List


class PackageRequest(BaseModel):
    id: str
    width: float
    height: float
    length: float
    weight: float
    fragility: str
    destination: str
    content_type: str


class TruckRequest(BaseModel):
    width: float
    height: float
    length: float
    max_weight: float


class OptimizationRequest(BaseModel):
    algorithm: str
    route: str = "TRUJILLO_OROCULLAY"
    origin_agency: str = "TRUJILLO"
    truck: TruckRequest
    packages: List[PackageRequest]


# RESPUESTA

class PositionResponse(BaseModel):
    x: float
    y: float
    z: float


class LoadedPackageResponse(BaseModel):
    id: str
    position: PositionResponse

    width: float
    height: float
    length: float

    weight: float
    fragility: str
    destination: str
    content_type: str


class UnloadedPackageResponse(BaseModel):
    id: str
    reason: str


class OptimizationResponse(BaseModel):
    algorithm: str

    space_utilization: float

    weight_utilization: float

    used_weight: float

    max_weight: float

    loaded_packages: List[LoadedPackageResponse]

    unloaded_packages: List[UnloadedPackageResponse]