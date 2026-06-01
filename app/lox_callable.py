from __future__ import annotations
from typing import TYPE_CHECKING, runtime_checkable
from typing import Protocol, override
from typing import List
import time

if TYPE_CHECKING:
    from app.interpreter import Interpreter


@runtime_checkable
class LoxCallable(Protocol):
    def arity(self) -> int: ...
    def call(self, interpreter: Interpreter, arguments: List[object]) -> object: ...


class ClockLoxCallable(LoxCallable):
    @override
    def arity(self) -> int:
        return 0

    @override
    def call(self, interpreter: Interpreter, arguments: list[object]):
        return float(time.time())

    def __str__(self):
        return "<native fn clock>"
