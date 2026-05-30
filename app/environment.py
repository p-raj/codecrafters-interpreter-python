from dataclasses import dataclass, field
from app.exception import InterpreterException
from .token import Token


@dataclass
class Environment:
    enclosing: Environment | None = None
    values: dict[str, object] = field(default_factory=dict)

    def define(self, name: str, value: object):
        self.values[name] = value

    def get(self, name: Token) -> object:
        if name.lexeme in self.values:
            return self.values[name.lexeme]
        if self.enclosing:
            return self.enclosing.get(name)

        raise InterpreterException(name, "Undefined variable '" + name.lexeme + "'.")

    def assign(self, name: Token, value: object) -> None:
        if name.lexeme in self.values:
            self.values[name.lexeme] = value
            return

        if self.enclosing is not None:
            self.enclosing.assign(name, value)
            return

        raise InterpreterException(name, f"Undefined variable '{name.lexeme}'.")
