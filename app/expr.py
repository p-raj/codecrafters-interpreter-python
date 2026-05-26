from abc import ABC, abstractmethod
from dataclasses import dataclass
from .token import Token
from typing import Protocol, TypeVar


"""
expression     → literal | unary | binary | grouping ;
literal        → NUMBER | STRING | "true" | "false" | "nil" ;
grouping       → "(" expression ")" ;
unary          → ( "-" | "!" ) expression ;
binary         → expression operator expression ;
operator       → "==" | "!=" | "<" | "<=" | ">" | ">=" | "+"  | "-"  | "*" | "/"

"""


class Expr(ABC):
    @abstractmethod
    def accept(): ...


@dataclass(frozen=True)
class Binary(Expr):
    left: Expr
    operator: Token
    right: Expr

    def accept(self, visitor: Visitor[R]) -> R:
        return visitor.visit_binary_expr(self)


@dataclass(frozen=True)
class Grouping(Expr):
    expression: Expr

    def accept(self, visitor: Visitor[R]) -> R:
        return visitor.visit_grouping_expr(self)


@dataclass(frozen=True)
class Literal(Expr):
    value: object

    def accept(self, visitor: Visitor[R]) -> R:
        return visitor.visit_literal_expr(self)


@dataclass(frozen=True)
class Unary(Expr):
    operator: Token
    right: Expr

    def accept(self, visitor: Visitor[R]) -> R:
        return visitor.visit_unary_expr(self)


Expr.Binary = Binary
Expr.Grouping = Grouping
Expr.Literal = Literal
Expr.Unary = Unary

R = TypeVar("R")


class Visitor(Protocol[R]):
    def visit_binary_expr(self, expr: Binary) -> R: ...
    def visit_grouping_expr(self, expr: Grouping) -> R: ...
    def visit_literal_expr(self, expr: Literal) -> R: ...
    def visit_unary_expr(self, expr: Unary) -> R: ...
