import json
from pathlib import Path
from random import Random

from app.modules.optimization_poc.schema import Package, Truck

FIXTURE_DIR = Path(__file__).resolve().parent / "fixtures"
SHUFFLE_SEED = 2026


def _load_json(name: str) -> list[dict]:
    with (FIXTURE_DIR / name).open(encoding="utf-8-sig") as file:
        return json.load(file)


def list_trucks() -> list[Truck]:
    return [Truck(**item) for item in _load_json("trucks.json")]


def list_packages(limit: int = 70, shuffled: bool = True) -> list[Package]:
    packages = [Package(**item) for item in _load_json("packages_70.json")[:limit]]
    if shuffled:
        packages = packages[:]
        Random(SHUFFLE_SEED).shuffle(packages)
    return packages


def list_packages_by_codes(codes: list[str]) -> list[Package]:
    normalized_codes = [code.strip().upper() for code in codes if code and code.strip()]
    packages = [Package(**item) for item in _load_json("packages_70.json")]
    package_by_code = {package.codigo.upper(): package for package in packages}
    return [package_by_code[code] for code in normalized_codes if code in package_by_code]


def get_truck(truck_id: str) -> Truck | None:
    return next((truck for truck in list_trucks() if truck.id == truck_id), None)
