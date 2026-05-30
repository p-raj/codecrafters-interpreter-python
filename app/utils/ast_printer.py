from app.expr import Visitor as EVisitor, Expr
from app.stmt import Visitor as SVisitor, Stmt
from app.token import Token, TokenType


class AstPrinter(EVisitor[str], SVisitor[str]):
    """
    Prints expressions and statements in Lisp-style prefix form.

    Examples:
        1 + 2         -> (+ 1 2)
        print 1 + 2;  -> (print (+ 1 2))
        var x = 10;   -> (var x 10)
    """

    def __init__(self, ast: Expr | list[Stmt]):
        self.ast = ast

    def print(self) -> str:
        """
        Entry point.

        If ast is a list, treat it as a list of statements.
        Otherwise, treat it as a single expression.
        """
        if isinstance(self.ast, list):
            return "\n".join(stmt.accept(self) for stmt in self.ast)

        return self.ast.accept(self)

    def parenthesize(self, name: str, *exprs: Expr) -> str:
        """
        Print one or more expressions in prefix form.
        """
        parts = ["(", name]

        for expr in exprs:
            parts.append(" ")
            parts.append(expr.accept(self))

        parts.append(")")
        return "".join(parts)

    # -------------------------
    # Expression visitors
    # -------------------------

    def visit_binary_expr(self, expr: Expr.Binary) -> str:
        return self.parenthesize(expr.operator.lexeme, expr.left, expr.right)

    def visit_grouping_expr(self, expr: Expr.Grouping) -> str:
        return self.parenthesize("group", expr.expression)

    def visit_literal_expr(self, expr: Expr.Literal) -> str:
        if expr.value is None:
            return "nil"
        if expr.value is True:
            return "true"
        if expr.value is False:
            return "false"

        return str(expr.value)

    def visit_unary_expr(self, expr: Expr.Unary) -> str:
        return self.parenthesize(expr.operator.lexeme, expr.right)

    def visit_comma_expr(self, expr: Expr.Comma) -> str:
        return self.parenthesize(",", expr.left, expr.right)

    def visit_ternary_expr(self, expr: Expr.Ternary) -> str:
        return self.parenthesize(
            "?:",
            expr.condition,
            expr.then_branch,
            expr.else_branch,
        )

    def visit_variable_expr(self, expr: Expr.Variable) -> str:
        return expr.name.lexeme

    def visit_assign_expr(self, expr: Expr.Assign) -> str:
        return self.parenthesize(
            "=",
            Expr.Variable(expr.name),
            expr.value,
        )

    # -------------------------
    # Statement visitors
    # -------------------------

    def visit_expression_stmt(self, stmt: Stmt.Expression) -> str:
        return self.parenthesize(";", stmt.expression)

    def visit_print_stmt(self, stmt: Stmt.Print) -> str:
        return self.parenthesize("print", stmt.expression)

    def visit_var_stmt(self, stmt: Stmt.Var) -> str:
        if stmt.initializer is None:
            return f"(var {stmt.name.lexeme})"

        return f"(var {stmt.name.lexeme} {stmt.initializer.accept(self)})"


if __name__ == "__main__":
    # -------------------------
    # Test 1: binary expression
    # -------------------------
    expression = Expr.Binary(
        Expr.Unary(
            Token(TokenType.MINUS, "-", None, 1),
            Expr.Literal(123),
        ),
        Token(TokenType.STAR, "*", None, 1),
        Expr.Grouping(Expr.Literal(45.54)),
    )

    result = AstPrinter(expression).print()
    expected = "(* (- 123) (group 45.54))"

    print(result)
    print("expression test:", result == expected)

    # -------------------------
    # Test 2: print statement
    # -------------------------
    print_stmt = Stmt.Print(
        Expr.Binary(
            Expr.Literal(1),
            Token(TokenType.PLUS, "+", None, 1),
            Expr.Literal(2),
        )
    )

    result = AstPrinter([print_stmt]).print()
    expected = "(print (+ 1 2))"

    print(result)
    print("print statement test:", result == expected)

    # -------------------------
    # Test 3: expression statement
    # -------------------------
    expression_stmt = Stmt.Expression(
        Expr.Binary(
            Expr.Literal(10),
            Token(TokenType.SLASH, "/", None, 1),
            Expr.Literal(2),
        )
    )

    result = AstPrinter([expression_stmt]).print()
    expected = "(; (/ 10 2))"

    print(result)
    print("expression statement test:", result == expected)

    # -------------------------
    # Test 4: var statement without initializer
    # -------------------------
    var_stmt_without_initializer = Stmt.Var(
        Token(TokenType.IDENTIFIER, "x", None, 1),
        None,
    )

    result = AstPrinter([var_stmt_without_initializer]).print()
    expected = "(var x)"

    print(result)
    print("var without initializer test:", result == expected)

    # -------------------------
    # Test 5: var statement with initializer
    # -------------------------
    var_stmt_with_initializer = Stmt.Var(
        Token(TokenType.IDENTIFIER, "y", None, 1),
        Expr.Literal(42),
    )

    result = AstPrinter([var_stmt_with_initializer]).print()
    expected = "(var y 42)"

    print(result)
    print("var with initializer test:", result == expected)

    # -------------------------
    # Test 6: multiple statements
    # -------------------------
    statements = [
        var_stmt_with_initializer,
        print_stmt,
        expression_stmt,
    ]

    result = AstPrinter(statements).print()
    expected = "\n".join(
        [
            "(var y 42)",
            "(print (+ 1 2))",
            "(; (/ 10 2))",
        ]
    )

    print(result)
    print("multiple statements test:", result == expected)

    # -------------------------
    # Test 7: print statement
    # -------------------------
    statements = [Stmt.Print(None)]
    result = AstPrinter(statements).print()
