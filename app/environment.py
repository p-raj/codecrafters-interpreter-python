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
        try:
            return self.values[name.lexeme]
            if self.enclosing:
                return self.enclosing.get(name)
        except ValueError:
            raise InterpreterException(
                name, "Undefined variable '" + name.lexeme + "'."
            )

    def assign(self, name: str, value: object):
        if self.enclosing:
            self.enclosing.assign(name, object)
        else:
            self.get(name)
            self.define(name, value)
