from enum import Enum, auto


class LayerRule(Enum):
    OVERRIDE = auto()
    PRESERVE = auto()
    MERGE = auto()
    APPEND = auto()
