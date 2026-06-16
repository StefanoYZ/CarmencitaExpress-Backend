from dataclasses import dataclass


@dataclass
class Truck:
    width: float
    height: float
    length: float
    max_weight: float

    @property
    def volume(self) -> float:
        return self.width * self.height * self.length