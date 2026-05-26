from app.expr import Visitor, Expr, Binary, Grouping, Literal, Unary
from app.token import Token, TokenType


class AstPrinter(Visitor[str]):
    def __init__(self, expr):
        self.expr = expr

    def print(self) -> str:
        return self.expr.accept(self)

    def parenthesize(self, name: str, *exprs: Expr) -> str:
        str_ = ["("]
        str_.append(name)
        for expr in exprs:
            str_.append(" ")
            str_.append(expr.accept(self))
        str_.append(")")
        return "".join(str_)

    def visit_binary_expr(self, expr: Binary) -> str:
        return self.parenthesize(expr.operator.lexeme, expr.left, expr.right)

    def visit_grouping_expr(self, expr: Grouping) -> str:
        return self.parenthesize("group", expr.expression)

    def visit_literal_expr(self, expr: Literal) -> str:
        if expr.value is None:
            return "nil"
        return str(expr.value)

    def visit_unary_expr(self, expr: Unary) -> str:
        return self.parenthesize(expr.operator.lexeme, expr.right)


if __name__ == "__main__":
    # Expr expression = new Expr.Binary(
    # new Expr.Unary(
    #     new Token(TokenType.MINUS, "-", null, 1),
    #     new Expr.Literal(123)),
    # new Token(TokenType.STAR, "*", null, 1),
    # new Expr.Grouping(
    #     new Expr.Literal(45.67)));
    expression = Binary(
        Unary(Token(TokenType.MINUS, "-", None, 1), Literal(123)),
        Token(TokenType.STAR, "*", None, 1),
        Grouping(Literal(45.54)),
    )
    s = AstPrinter(expression).print()
    print(s, s == "(* (- 123) (group 45.54))")
