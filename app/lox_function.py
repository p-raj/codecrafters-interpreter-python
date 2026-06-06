from typing import override, TYPE_CHECKING
from app.lox_callable import LoxCallable
from app.stmt import Stmt
from app.expr import Expr
from app.environment import Environment
from app.exception import ReturnExecutionException

if TYPE_CHECKING:
    from app.interpreter import Interpreter
    from app.lox_instance import LoxInstance


class LoxFunction(LoxCallable):
    def __init__(
        self,
        declaration: Stmt.Function | Expr.Lambda,
        closure: Environment,
        is_initializer: bool,
    ):
        self.declaration = declaration
        self.closure = closure
        self.is_initializer = is_initializer

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
            if self.is_initializer:
                return self.closure.get_at(0, "this")
            return r.value
        if self.is_initializer:
            return self.closure.get_at(0, "this")

    def bind(self, instance: LoxInstance):
        env = Environment(self.closure)
        env.define("this", instance)
        return LoxFunction(self.declaration, env, self.is_initializer)

    @override
    def __str__(self):
        if hasattr(self.declaration, "name"):
            return f"<fn {self.declaration.name.lexeme}>"

        return "<fn lambda>"
