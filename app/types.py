from __future__ import annotations

from dataclasses import dataclass
from enum import Enum, auto


class DeclarationType(Enum):
    DECLARED = auto()
    DEFINED = auto()
    USED = auto()


class ClassType(Enum):
    NONE = auto()
    CLASS = auto()


class FunctionType(Enum):
    NONE = auto()
    FUNCTION = auto()
    LAMBDA = auto()
    METHOD = auto()
    INITIALIZER = auto()


@dataclass
class Local:
    defined: DeclarationType
    index: int


@dataclass
class LocalScoped:
    index: int
    is_ready: bool


@dataclass(frozen=True)
class Resolution:
    depth: int
    index: int
