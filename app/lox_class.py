from typing import override, TYPE_CHECKING
from app.lox_callable import LoxCallable


if TYPE_CHECKING:
    from app.interpreter import Interpreter
    from app.lox_function import LoxFunction


class LoxClass(LoxCallable):
    def __init__(
        self,
        name: str,
        superclass: LoxClass | None = None,
        methods: dict | None = None,
    ):
        self.name = name
        self.methods = methods or dict()
        self.superclass = superclass

    @override
    def arity(self) -> int:
        initializer: LoxFunction = self.find_method("init")
        if initializer is None:
            return 0
        return initializer.arity()

    @override
    def call(self, interpreter: Interpreter, arguments: list[object]):
        from app.lox_instance import LoxInstance

        instance: LoxInstance = LoxInstance(self)
        initializer: LoxFunction = self.find_method("init")
        if initializer is not None:
            initializer.bind(instance).call(interpreter, arguments)
        return instance

    def find_method(self, name: str):
        if name in self.methods:
            return self.methods[name]
        if self.superclass:
            return self.superclass.find_method(name)

    @override
    def __str__(self):
        return self.name
