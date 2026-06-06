from __future__ import annotations
from typing import override, Callable
from app.expr import Visitor as EVisitor, Expr
from app.stmt import Visitor as SVisitor, Stmt
from app.interpreter import Interpreter
from app.token import Token
from app.exception import Error
from app.types import FunctionType, ClassType


class Stack:
    def __init__(self):
        self.s = []

    def push(self, o: object):
        self.s.append(o)

    def pop(self) -> object:
        return self.s.pop()

    def peek(self) -> object:
        return self.s[-1]

    def is_empty(self) -> bool:
        return len(self.s) == 0

    def __len__(self) -> int:
        return len(self.s)

    def __getitem__(self, idx):
        return self.s[idx]


class Resolver(EVisitor[str], SVisitor[None]):
    def __init__(self, interpreter: Interpreter, error_callback: Callable):
        self.interpreter = interpreter
        self.scopes = Stack()
        self.propagate_err = error_callback
        self.current_function: FunctionType = FunctionType.NONE
        self.current_class: ClassType = ClassType.NONE

    def begin_scope(self):
        _s: dict[str, bool] = {}
        self.scopes.push(_s)

    def end_scope(self):
        self.scopes.pop()

    def _dd(self, name: Token | str, flag: bool):
        if isinstance(name, Token):
            name = name.lexeme
        if self.scopes.is_empty():
            return
        scope = self.scopes.peek()
        scope[name] = flag

    def declare(self, name: Token):
        if self.scopes.is_empty():
            return
        scope = self.scopes.peek()
        if name.lexeme in scope:
            self.propagate_err(
                Error("Already a variable with this name in this scope.", name.line)
            )
        self._dd(name, False)

    def define(self, name: Token):
        self._dd(name, True)

    def resolvee(self, expr: Expr):
        expr.accept(self)

    def resolves(self, stmt: Stmt):
        stmt.accept(self)

    def resolvess(self, statements: list[Stmt]):
        for stmt in statements:
            self.resolves(stmt)

    def resolve_local(self, expr: Expr, name: Token):
        idx = len(self.scopes) - 1
        while idx >= 0:
            scope = self.scopes[idx]
            if name.lexeme in scope:
                # distance between calee and the variable declared
                self.interpreter.resolve(expr, len(self.scopes) - 1 - idx)
                return
            idx -= 1

    def resolve_function(self, func: Stmt.Function, ftype: FunctionType):
        enclosing_function: FunctionType = self.current_function
        self.current_function = ftype
        self.begin_scope()
        for param in func.params:
            self.declare(param)
            self.define(param)
        self.resolvess(func.body)
        self.end_scope()
        self.current_function = enclosing_function

    ##############################
    # visitor overrides | Expression
    ##############################
    @override
    def visit_assign_expr(self, expr: Expr.Assign):
        self.resolvee(expr.value)
        self.resolve_local(expr, expr.name)

    @override
    def visit_variable_expr(self, expr: Expr.Variable):
        if (
            not self.scopes.is_empty()
            and self.scopes.peek().get(expr.name.lexeme) is False
        ):
            self.propagate_err(
                Error(
                    "Can't read local variable in its own initializer.", expr.name.line
                )
            )
        self.resolve_local(expr, expr.name)

    @override
    def visit_binary_expr(self, expr: Expr.Binary):
        self.resolvee(expr.left)
        self.resolvee(expr.right)

    @override
    def visit_call_expr(self, expr: Expr.Call):
        self.resolvee(expr.callee)
        for argument in expr.arguments:
            self.resolvee(argument)

    @override
    def visit_grouping_expr(self, expr: Expr.Grouping):
        self.resolvee(expr.expression)

    @override
    def visit_literal_expr(self, expr: Expr.Literal):
        return

    @override
    def visit_logical_expr(self, expr: Expr.Logical):
        self.resolvee(expr.left)
        self.resolvee(expr.right)

    @override
    def visit_unary_expr(self, expr: Expr.Unary):
        self.resolvee(expr.right)

    @override
    def visit_get_expr(self, expr: Expr.Get):
        self.resolvee(expr.objekt)

    @override
    def visit_set_expr(self, expr: Expr.Set):
        self.resolvee(expr.value)
        self.resolvee(expr.objekt)

    @override
    def visit_this_expr(self, expr: Expr.This):
        if self.current_class == ClassType.NONE:
            self.propagate_err(
                Error("Can't use 'this' outside of a class.", expr.keyword)
            )
        else:
            self.resolve_local(expr, expr.keyword)

    ##############################
    # visitor overrides | Statement
    ##############################
    @override
    def visit_block_stmt(self, stmt: Stmt.Block):
        self.begin_scope()
        self.resolvess(stmt.statements)
        self.end_scope()

    @override
    def visit_var_stmt(self, stmt: Stmt.Var):
        self.declare(stmt.name)
        if stmt.initializer:
            self.resolvee(stmt.initializer)
        self.define(stmt.name)

    @override
    def visit_function_stmt(self, stmt: Stmt.Function):
        self.declare(stmt.name)
        self.define(stmt.name)
        self.resolve_function(stmt, FunctionType.FUNCTION)

    @override
    def visit_expression_stmt(self, stmt: Stmt.Expression):
        self.resolvee(stmt.expression)

    @override
    def visit_if_stmt(self, stmt: Stmt.If):
        self.resolvee(stmt.condition)
        self.resolvee(stmt.then_branch)
        if stmt.else_branch:
            self.resolvee(stmt.else_branch)

    @override
    def visit_print_stmt(self, stmt: Stmt.Print):
        self.resolvee(stmt.expression)

    @override
    def visit_return_stmt(self, stmt: Stmt.Return):
        if self.current_function == FunctionType.NONE:
            self.propagate_err(Error("Can't return from top-level code.", stmt.keyword))
        if stmt.value:
            # if self.current_function != FunctionType.INITIALIZER:
            #     self.propagate_err(
            #         Error(
            #             "Can't return a value from an initializer.", stmt.keyword.line
            #         )
            #     )
            # else:
            self.resolvee(stmt.value)

    @override
    def visit_while_stmt(self, stmt: Stmt.While):
        self.resolvee(stmt.condition)
        self.resolvee(stmt.body)

    @override
    def visit_class_stmt(self, stmt: Stmt.Class):
        enclosing_class = self.current_class
        self.current_class = ClassType.CLASS
        self.declare(stmt.name)
        self.define(stmt.name)
        self.begin_scope()
        self._dd("this", True)
        for method in stmt.methods:
            self.resolve_function(method, FunctionType.METHOD)
        self.end_scope()
        self.current_class = enclosing_class


"""
Could not solve - 
Our resolver calculates which environment the variable is found in, but it’s still looked up by name in that map.
A more efficient environment representation would store local variables in an array and look them up by index.

Extend the resolver to associate a unique index for each local variable declared in a scope. 
When resolving a variable access, look up both the scope the variable is in and its index and store that.
In the interpreter, use that to quickly access a variable by its index instead of using a map.
"""
