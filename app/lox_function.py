from typing import override, TYPE_CHECKING
from app.lox_callable import LoxCallable
from app.stmt import Stmt
from app.environment import Environment
from app.exception import ReturnExecutionException

if TYPE_CHECKING:
    from app.interpreter import Interpreter


class LoxFunction(LoxCallable):
    def __init__(self, declaration: Stmt.Function, closure: Environment):
        self.declaration = declaration
        self.closure = closure

    @override
    def arity(self) -> int:
        return len(self.declaration.params)

    @override
    def call(self, interpreter: Interpreter, arguments: list[object]):
        environment = Environment(self.closure)
        for idx, param in enumerate(self.declaration.params):
            environment.define(param.lexeme, arguments[idx])
        try:
            interpreter.execute_block(self.declaration.body, environment)
        except ReturnExecutionException as r:
            return r.value

    @override
    def __str__(self):
        return f"<fn {self.declaration.name.lexeme}>"
