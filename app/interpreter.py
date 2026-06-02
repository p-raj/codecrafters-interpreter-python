from __future__ import annotations
from typing import override, TYPE_CHECKING
from app.expr import Visitor as EVisitor, Expr
from app.stmt import Visitor as SVisitor, Stmt
from app.token import TokenType, Token
from app.exception import (
    InterpreterException,
    BreakExecutionException,
    ReturnExecutionException,
)
from app.environment import Environment
from typing import Callable

if TYPE_CHECKING:
    from app.lox_callable import LoxCallable


class Interpreter(EVisitor[str], SVisitor[None]):
    def __init__(self, error_callback: Callable):
        from app.lox_callable import ClockLoxCallable

        self.propagate_err = error_callback
        self.globals = Environment()
        self.environment = self.globals
        self.locals = dict()
        self.globals.define("clock", ClockLoxCallable())

    ##############################
    # main
    ##############################
    def interprete(self, expr: Expr):
        try:
            print(self.stringify(self.evaluate(expr)))
        except InterpreterException as e:
            self.propagate_err(e)

    def interprets(self, stmts: list[Stmt]):
        try:
            for stmt in stmts:
                self.execute(stmt)
        except InterpreterException as e:
            self.propagate_err(e)

    ##############################
    # helpers | generic
    ##############################
    def stringify(self, value: object) -> str:
        if value is None:
            return "nil"
        if isinstance(value, float):
            n, d = str(value).split(".")
            if d == "0":
                # this is int
                return n
        if isinstance(value, bool):
            return str(value).lower()
        return str(value)

    ##############################
    # helpers | Stmt
    ##############################
    def execute(self, stmt: Stmt) -> None:
        stmt.accept(self)

    def resolve(self, expr: Expr, depth: int) -> None:
        self.locals[id(expr)] = depth

    def execute_block(self, stmts: list[Stmt], env: Environment) -> None:
        prev: Environment = self.environment
        try:
            self.environment = env
            for stmt in stmts:
                self.execute(stmt)
        finally:
            self.environment = prev

    ##############################
    # helpers | Expr
    ##############################
    def evaluate(self, expr: Expr) -> object:
        return expr.accept(self)

    def is_truthy(self, obj: object) -> bool:
        if obj is None:
            return False
        if isinstance(obj, bool):
            return bool(obj)
        return True

    def is_equal(self, left: object, right: object) -> bool:
        if left is None or right is None:
            return True
        if left is None:
            return False
        return left == right

    def lookup_variable(self, name: Token, expr: Expr) -> object:
        dist = self.locals.get(id(expr))
        if dist is None:
            return self.globals.get(name)
        return self.environment.get_at(dist, name.lexeme)

    ##############################
    # validators
    ##############################
    def check_number_operand(self, operator: Token, operand: object):
        try:
            if isinstance(operand, bool):
                raise ValueError
            if isinstance(operand, float) or isinstance(operand, int):
                return
        except ValueError:
            pass
        raise InterpreterException(operator, "Operand must be a number.")

    def check_number_operands(self, operator: Token, left: object, right: object):
        self.check_number_operand(operator, left)
        self.check_number_operand(operator, right)

    ##############################
    # visitor overrides | Expression
    ##############################
    @override
    def visit_comma_expr(self, expr: Expr.Comma) -> object:
        _: object = self.evaluate(expr.left)
        right: object = self.evaluate(expr.right)
        return right

    @override
    def visit_logical_expr(self, expr: Expr.Logic) -> object:
        left: object = self.evaluate(expr.left)
        match expr.operator.kind:
            case TokenType.OR:
                if self.is_truthy(left):
                    return left
            case TokenType.AND:
                if not self.is_truthy(left):
                    return left
        return self.evaluate(expr.right)

    @override
    def visit_ternary_expr(self, expr: Expr.Ternary) -> object:
        if self.is_truthy(self.evaluate(expr.condition)):
            return self.evaluate(expr.then_branch)
        return self.evaluate(expr.else_branch)

    @override
    def visit_binary_expr(self, expr: Expr.Binary) -> object:
        left: object = self.evaluate(expr.left)
        right: object = self.evaluate(expr.right)

        match expr.operator.kind:
            case TokenType.MINUS:
                self.check_number_operands(expr.operator, left, right)
                return float(left) - float(right)
            case TokenType.STAR:
                self.check_number_operands(expr.operator, left, right)
                return float(left) * float(right)
            case TokenType.SLASH:
                self.check_number_operands(expr.operator, left, right)
                return float(left) / float(right)
            case TokenType.PLUS:
                if isinstance(left, float) and isinstance(right, float):
                    return left + right
                elif isinstance(left, str) and isinstance(right, str):
                    return left + right
                raise InterpreterException(
                    expr.operator, "Operands must be two numbers or two strings."
                )
            case TokenType.BANG_EQUAL:
                return not self.is_equal(left, right)
            case TokenType.EQUAL_EQUAL:
                return self.is_equal(left, right)
            case TokenType.GREATER:
                self.check_number_operands(expr.operator, left, right)
                return float(left) > float(right)
            case TokenType.GREATER_EQUAL:
                self.check_number_operands(expr.operator, left, right)
                return float(left) >= float(right)
            case TokenType.LESS:
                self.check_number_operands(expr.operator, left, right)
                return float(left) < float(right)
            case TokenType.LESS_EQUAL:
                self.check_number_operands(expr.operator, left, right)
                return float(left) <= float(right)
        return None

    @override
    def visit_grouping_expr(self, expr: Expr.Grouping) -> object:
        return self.evaluate(expr.expression)

    @override
    def visit_literal_expr(self, expr: Expr.Literal) -> object:
        return expr.value

    @override
    def visit_unary_expr(self, expr: Expr.Unary) -> object:
        right: object = self.evaluate(expr.right)

        match expr.operator.kind:
            case TokenType.MINUS:
                self.check_number_operand(expr.operator, right)
                return -(float(right))
            case TokenType.BANG:
                return not (self.is_truthy(right))
        return None

    @override
    def visit_variable_expr(self, expr: Expr.Variable) -> object:
        return self.lookup_variable(expr.name, expr)
        return self.environment.get(expr.name)

    @override
    def visit_assign_expr(self, expr: Expr.Assign) -> object:
        value: object = self.evaluate(expr.value)
        dist = self.locals.get(id(expr))
        if dist is None:
            self.globals.assign(expr.name, value)
        else:
            self.environment.assign_at(dist, expr.name, value)
        return value

    def visit_call_expr(self, expr: Expr.Call) -> object:
        from app.lox_callable import LoxCallable

        callee: object = self.evaluate(expr.callee)

        arguments: list[object] = []
        for argument in expr.arguments:
            arguments.append(self.evaluate(argument))

        if not isinstance(callee, LoxCallable):
            raise InterpreterException(
                expr.paren,
                "Can only call functions and classes.",
            )

        fn = callee
        if len(arguments) != fn.arity():
            raise InterpreterException(
                expr.paren,
                f"Expected {fn.arity()} arguments but got {len(arguments)}.",
            )

        return fn.call(self, arguments)

    @override
    def visit_lambda_expr(self, expr: Expr.Lambda) -> object:
        from app.lox_function import LoxFunction

        return LoxFunction(expr, self.environment)

    ##############################
    # visitor overrides | Statement
    ##############################
    @override
    def visit_expression_stmt(self, stmt: Stmt.Expression) -> None:
        self.evaluate(stmt.expression)

    @override
    def visit_function_stmt(self, stmt: Stmt.Function) -> None:
        from app.lox_function import LoxFunction

        func: LoxFunction = LoxFunction(stmt, self.environment)
        self.environment.define(stmt.name.lexeme, func)

    @override
    def visit_print_stmt(self, stmt: Stmt.Print) -> None:
        print(self.stringify(self.evaluate(stmt.expression)))

    @override
    def visit_var_stmt(self, stmt: Stmt.Var) -> None:
        value: object = None
        if stmt.initializer is not None:
            value = self.evaluate(stmt.initializer)
        self.environment.define(stmt.name.lexeme, value)

    @override
    def visit_block_stmt(self, stmt: Stmt.Block) -> None:
        self.execute_block(stmt.statements, Environment(self.environment))

    @override
    def visit_if_stmt(self, stmt: Stmt.If) -> None:
        if self.is_truthy(self.evaluate(stmt.condition)):
            self.execute(stmt.then_branch)
        elif stmt.else_branch:
            self.execute(stmt.else_branch)

    @override
    def visit_while_stmt(self, stmt: Stmt.While) -> None:
        while self.is_truthy(self.evaluate(stmt.condition)):
            try:
                self.execute(stmt.body)
            except BreakExecutionException:
                break

    @override
    def visit_break_stmt(self, stmt: Stmt.Break) -> None:
        raise BreakExecutionException()

    @override
    def visit_return_stmt(self, stmt: Stmt.Return) -> None:
        value: object = None
        if stmt.value:
            value = self.evaluate(stmt.value)
        raise ReturnExecutionException(value)
