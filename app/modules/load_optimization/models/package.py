from dataclasses import dataclass


@dataclass
class Package:
    id: str
    width: float
    height: float
    length: float
    weight: float
    fragility: str
    destination: str
    content_type: str

    @property
    def volume(self) -> float:
        return self.width * self.height * self.length