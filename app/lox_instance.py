from typing import TYPE_CHECKING
from app.token import Token
from app.exception import InterpreterException

if TYPE_CHECKING:
    from app.lox_class import LoxClass


class LoxInstance:
    def __init__(self, klass: LoxClass):
        self.klass = klass
        self.fields: dict[str, object] = dict()

    def __repr__(self):
        return f"{self.klass.name} instance"

    def get(self, name: Token):
        if name.lexeme in self.fields:
            return self.fields[name.lexeme]
        klass_method = self.klass.find_method(name.lexeme)
        if klass_method:
            return klass_method.bind(self)
        raise InterpreterException(name, "Undefined property '" + name.lexeme + "'.")

    def set(self, name: Token, value: object):
        self.fields[name.lexeme] = value
