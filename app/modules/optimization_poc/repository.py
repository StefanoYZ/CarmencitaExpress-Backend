import json
from pathlib import Path
from random import Random

from app.modules.optimization_poc.schema import Package, Truck

FIXTURE_DIR = Path(__file__).resolve().parent / "fixtures"
SHUFFLE_SEED = 2026


def _load_json(name: str) -> list[dict]:
    with (FIXTURE_DIR / name).open(encoding="utf-8") as file:
        return json.load(file)


def list_trucks() -> list[Truck]:
    return [Truck(**item) for item in _load_json("trucks.json")]


def list_packages(limit: int = 50, shuffled: bool = True) -> list[Package]:
    packages = [Package(**item) for item in _load_json("packages_50.json")[:limit]]
    if shuffled:
        packages = packages[:]
        Random(SHUFFLE_SEED).shuffle(packages)
    return packages


def get_truck(truck_id: str) -> Truck | None:
    return next((truck for truck in list_trucks() if truck.id == truck_id), None)
