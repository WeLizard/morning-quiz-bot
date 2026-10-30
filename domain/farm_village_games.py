"""Transport independent village game registry and reward arithmetic."""
from dataclasses import dataclass
from . import farm_ballista, farm_pie


@dataclass(frozen=True)
class Spec:
    npc: str
    min_level: int
    ttl: int
    family: str
    reward: str
    version: int


GAMES = {'pukh_ballista': Spec('pukh', 1, farm_ballista.TTL, 'replay', 'vigour', 1),
         'agata_pie': Spec('agata', 1, farm_pie.TTL, 'replay', 'festival', 1)}


def stars(score):
    return 3 if score >= 900 else 2 if score >= 700 else 1 if score >= 400 else 0


def reward_total(kind, base, count):
    if not count:
        return 0
    return base * count // 100 if kind == 'vigour' else base * (50, 75, 100)[count-1] // 100
