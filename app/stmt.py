from abc import ABC, abstractmethod
from dataclasses import dataclass
from .token import Token
from typing import Protocol, TypeVar, List


from .expr import Expr

"""
program        → declaration* EOF ;
declaration    → varDecl | statement ;
varDecl        → "var" IDENTIFIER ( "=" expression )? ";" ;
statement      → exprStmt | ifStmt | printStmt | block;
ifStmt         → "if" "(" expression ")" statement ( "else" statement )? ;
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


@dataclass(frozen=True)
class If(Stmt):
    condition: Expr
    then_branch: Stmt
    else_branch: Stmt

    def accept(self, visitor: Visitor[R]) -> R:
        return visitor.visit_if_stmt(self)


@dataclass(frozen=True)
class While(Stmt):
    condition: Expr
    body: Stmt

    def accept(self, visitor: Visitor[R]) -> R:
        return visitor.visit_while_stmt(self)


@dataclass(frozen=True)
class Break(Stmt):

    def accept(self, visitor: Visitor[R]) -> R:
        return visitor.visit_break_stmt(self)


@dataclass(frozen=True)
class Function(Stmt):
    name: Token
    params: List[Token]
    body: List[Stmt]

    def accept(self, visitor: Visitor[R]) -> R:
        return visitor.visit_function_stmt(self)


@dataclass(frozen=True)
class Return(Stmt):
    keyword: Token
    value: Expr

    def accept(self, visitor: Visitor[R]) -> R:
        return visitor.visit_return_stmt(self)



Stmt.Expression = Expression
Stmt.Print = Print
Stmt.Var = Var
Stmt.Block = Block
Stmt.If = If
Stmt.While = While
Stmt.Break = Break
Stmt.Function = Function
Stmt.Return = Return

R = TypeVar("R")


class Visitor(Protocol[R]):
    def visit_expression_stmt(self, stmt: Expression) -> R: ...
    def visit_print_stmt(self, stmt: Print) -> R: ...
    def visit_var_stmt(self, stmt: Var) -> R: ...
    def visit_block_stmt(self, stmt: Block) -> R: ...
    def visit_if_stmt(self, stmt: If) -> R: ...
    def visit_while_stmt(self, stmt: While) -> R: ...
    def visit_break_stmt(self, stmt: Break) -> R: ...
    def visit_function_stmt(self, stmt: Function) -> R: ...
    def visit_return_stmt(self, stmt: Return) -> R: ...

