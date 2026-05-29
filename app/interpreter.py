from typing import override
from app.expr import Visitor, Expr
from app.token import TokenType, Token
from app.exception import InterpreterException
from typing import Callable
import ast


class Interpreter(Visitor[str]):
    def __init__(self, error_callback: Callable):
        self.propagate_err = error_callback

    ##############################
    # main
    ##############################
    def interpret(self, expr: Expr):
        try:
            print(self.stringify(self.evaluate(expr)))
        except InterpreterException as e:
            self.propagate_err(e)

    ##############################
    # helpers
    ##############################
    def stringify(self, value: object) -> str:
        if value is None:
            return "nil"
        if isinstance(value, float):
            n, d = str(value).split(".")[-1]
            if d == "0":
                # this is int
                return n
        if isinstance(value, bool):
            return str(value).lower()

        return str(value)

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

    ##############################
    # validators
    ##############################
    def check_number_operand(self, operator: Token, operand: object):
        if (
            isinstance(operand, float)
            or isinstance(operand, int)
            or isinstance(ast.literal_eval(str(operand)), float)
            or isinstance(ast.literal_eval(str(operand)), int)
        ):
            return
        raise InterpreterException(operator, "Operand must be a number.")

    def check_number_operands(self, operator: Token, left: object, right: object):
        self.check_number_operand(operator, left)
        self.check_number_operand(operator, right)

    ##############################
    # visitor overrides
    ##############################
    @override
    def visit_comma_expr(self, expr: Expr.Comma) -> object:
        _: object = self.evaluate(expr.left)
        right: object = self.evaluate(expr.right)
        return right

    @override
    def visit_ternary_expr(self, expr: Expr.Ternary) -> object:
        pass

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
                self.check_number_operands(expr.operator, left, right)
                return float(left) != float(right)
            case TokenType.EQUAL_EQUAL:
                self.check_number_operands(expr.operator, left, right)
                return float(left) == float(right)
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
                return -(float(right))
            case TokenType.BANG:
                return not (self.is_truthy(right))
        return None

    @override
    def visit_variable_expr(self, expr: Expr.Variable) -> object:
        pass
