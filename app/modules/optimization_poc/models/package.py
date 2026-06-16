from dataclasses import dataclass
from unicodedata import normalize

from app.modules.optimization_poc.schema import Package, Placement
from app.modules.optimization_poc.utils.constants import BEST_FIT_3D, DESTINATION_ALIASES, FRAGILITY_ORDER, MAXIMIN, MINIMAX, ROUTE_RANK, STACK_PRIORITY


@dataclass(frozen=True)
class Package3D:
    id: int
    codigo: str
    descripcion: str
    destino: str
    orden_entrega: int
    prioridad: int
    fragilidad: str
    peso_kg: float
    largo_cm: float
    ancho_cm: float
    alto_cm: float
    permite_rotacion: bool = True

    @property
    def volume(self) -> float:
        return self.largo_cm * self.ancho_cm * self.alto_cm

    @property
    def footprint(self) -> float:
        return self.largo_cm * self.ancho_cm

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
    def weight(self) -> float:
        return self.peso_kg

    @property
    def destination(self) -> str:
        return self.destino

    @property
    def fragility(self) -> str:
        return self.fragilidad

    @property
    def content_type(self) -> str:
        return self.descripcion

    @classmethod
    def from_schema(cls, package: Package) -> "Package3D":
        return cls(**package.model_dump())

    def to_schema(self) -> Package:
        return Package(**self.__dict__)


def normalize_destination(destination: str) -> str:
    normalized = normalize("NFKD", destination or "").encode("ascii", "ignore").decode("ascii")
    normalized = " ".join(normalized.upper().split())
    return DESTINATION_ALIASES.get(normalized, normalized)


def destination_rank(package: Package3D | Package | Placement) -> int:
    destination = normalize_destination(getattr(package, "destino", getattr(package, "destination", "")))
    fallback = getattr(package, "orden_entrega", getattr(package, "delivery_order", 0))
    return ROUTE_RANK.get(destination, fallback)


def package_volume(package: Package3D | Package | Placement) -> float:
    if hasattr(package, "depth") and hasattr(package, "width") and hasattr(package, "height") and not hasattr(package, "largo_cm"):
        return package.depth * package.width * package.height
    return getattr(package, "volume", getattr(package, "largo_cm") * getattr(package, "ancho_cm") * getattr(package, "alto_cm"))


def package_footprint(package: Package3D | Package | Placement) -> float:
    if hasattr(package, "depth") and hasattr(package, "width") and not hasattr(package, "largo_cm"):
        return package.depth * package.width
    return getattr(package, "footprint", getattr(package, "largo_cm") * getattr(package, "ancho_cm"))


def package_sort_key(package: Package3D | Package, strategy: str) -> tuple[float, ...]:
    volume = package_volume(package)
    footprint = package_footprint(package)
    route_rank = destination_rank(package)
    fragility_rank = FRAGILITY_ORDER.get(package.fragilidad, 9)
    stack_rank = STACK_PRIORITY.get(package.fragilidad, 9)

    if strategy == BEST_FIT_3D:
        return (-volume, -footprint, -package.peso_kg, -route_rank, stack_rank, package.codigo)
    if strategy == MAXIMIN:
        return (stack_rank, -footprint, -package.peso_kg, -route_rank, package.prioridad, -volume, package.codigo)
    if strategy == MINIMAX:
        return (-route_rank, -volume, -package.peso_kg, package.prioridad, stack_rank, package.codigo)
    return (-route_rank, package.prioridad, stack_rank, fragility_rank, -footprint, -volume, package.codigo)
