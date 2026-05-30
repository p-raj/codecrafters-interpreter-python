from abc import ABC, abstractmethod
from dataclasses import dataclass
from .token import Token
from typing import Protocol, TypeVar, List


from .expr import Expr

"""
program        → declaration* EOF ;
declaration    → varDecl | statement ;
varDecl        → "var" IDENTIFIER ( "=" expression )? ";" ;
statement      → exprStmt | printStmt ;
exprStmt       → expression <;> ;
printStmt      → print expression <;> ;

"""


class Stmt(ABC):
    @abstractmethod
    def accept(): ...


@dataclass(frozen=True)
class Expression(Stmt):
    expression: Expr

    def accept(self, visitor: Visitor[R]) -> R:
        return visitor.visit_expression_stmt(self)


@dataclass(frozen=True)
class Print(Stmt):
    expression: Expr

    def accept(self, visitor: Visitor[R]) -> R:
        return visitor.visit_print_stmt(self)


@dataclass(frozen=True)
class Var(Stmt):
    name: Token
    initializer: Expr

    def accept(self, visitor: Visitor[R]) -> R:
        return visitor.visit_var_stmt(self)


@dataclass(frozen=True)
class Block(Stmt):
    statements: List[Stmt]

    def accept(self, visitor: Visitor[R]) -> R:
        return visitor.visit_block_stmt(self)



Stmt.Expression = Expression
Stmt.Print = Print
Stmt.Var = Var
Stmt.Block = Block

R = TypeVar("R")


class Visitor(Protocol[R]):
    def visit_expression_stmt(self, stmt: Expression) -> R: ...
    def visit_print_stmt(self, stmt: Print) -> R: ...
    def visit_var_stmt(self, stmt: Var) -> R: ...
    def visit_block_stmt(self, stmt: Block) -> R: ...

