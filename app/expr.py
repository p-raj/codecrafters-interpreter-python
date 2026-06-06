from __future__ import annotations
from abc import ABC, abstractmethod
from dataclasses import dataclass
from .token import Token
from typing import Protocol, TypeVar, List, TYPE_CHECKING


if TYPE_CHECKING:
    from app.stmt import Stmt


class Expr(ABC):
    @abstractmethod
    def accept(): ...


@dataclass(frozen=True)
class Comma(Expr):
    left: Expr
    right: Expr

    def accept(self, visitor: Visitor[R]) -> R:
        return visitor.visit_comma_expr(self)


@dataclass(frozen=True)
class Logical(Expr):
    left: Expr
    operator: Token
    right: Expr

    def accept(self, visitor: Visitor[R]) -> R:
        return visitor.visit_logical_expr(self)


@dataclass(frozen=True)
class Ternary(Expr):
    condition: Expr
    then_branch: Expr
    else_branch: Expr

    def accept(self, visitor: Visitor[R]) -> R:
        return visitor.visit_ternary_expr(self)


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


@dataclass(frozen=True)
class Variable(Expr):
    name: Token

    def accept(self, visitor: Visitor[R]) -> R:
        return visitor.visit_variable_expr(self)


@dataclass(frozen=True)
class Assign(Expr):
    name: Token
    value: Expr

    def accept(self, visitor: Visitor[R]) -> R:
        return visitor.visit_assign_expr(self)


@dataclass(frozen=True)
class Call(Expr):
    callee: Expr
    paren: Token
    arguments: List[Expr]

    def accept(self, visitor: Visitor[R]) -> R:
        return visitor.visit_call_expr(self)


@dataclass(frozen=True)
class Lambda(Expr):
    params: List[Token]
    body: List[Stmt]

    def accept(self, visitor: Visitor[R]) -> R:
        return visitor.visit_lambda_expr(self)


@dataclass(frozen=True)
class Get(Expr):
    objekt: Expr
    name: Token

    def accept(self, visitor: Visitor[R]) -> R:
        return visitor.visit_get_expr(self)


@dataclass(frozen=True)
class Set(Expr):
    objekt: Expr
    name: Token
    value: Expr

    def accept(self, visitor: Visitor[R]) -> R:
        return visitor.visit_set_expr(self)


@dataclass(frozen=True)
class This(Expr):
    keyword: Token

    def accept(self, visitor: Visitor[R]) -> R:
        return visitor.visit_this_expr(self)



Expr.Comma = Comma
Expr.Logical = Logical
Expr.Ternary = Ternary
Expr.Binary = Binary
Expr.Grouping = Grouping
Expr.Literal = Literal
Expr.Unary = Unary
Expr.Variable = Variable
Expr.Assign = Assign
Expr.Call = Call
Expr.Lambda = Lambda
Expr.Get = Get
Expr.Set = Set
Expr.This = This

R = TypeVar("R")


class Visitor(Protocol[R]):
    def visit_comma_expr(self, expr: Comma) -> R: ...
    def visit_logical_expr(self, expr: Logical) -> R: ...
    def visit_ternary_expr(self, expr: Ternary) -> R: ...
    def visit_binary_expr(self, expr: Binary) -> R: ...
    def visit_grouping_expr(self, expr: Grouping) -> R: ...
    def visit_literal_expr(self, expr: Literal) -> R: ...
    def visit_unary_expr(self, expr: Unary) -> R: ...
    def visit_variable_expr(self, expr: Variable) -> R: ...
    def visit_assign_expr(self, expr: Assign) -> R: ...
    def visit_call_expr(self, expr: Call) -> R: ...
    def visit_lambda_expr(self, expr: Lambda) -> R: ...
    def visit_get_expr(self, expr: Get) -> R: ...
    def visit_set_expr(self, expr: Set) -> R: ...
    def visit_this_expr(self, expr: This) -> R: ...

