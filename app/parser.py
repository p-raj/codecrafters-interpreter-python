from .token import Token, TokenType
from .expr import Expr
from .stmt import Stmt
from .exception import ParserException
from typing import Callable

"""
expression     → assignment ;
assignment     → IDENTIFIER "=" assignment | equality;
equality       → comparison ( ( "!=" | "==" ) comparison )* ;
comparison     → term ( ( ">" | ">=" | "<" | "<=" ) term )* ;
term           → factor ( ( "-" | "+" ) factor )* ;
factor         → unary ( ( "/" | "*" ) unary )* ;
unary          → ( "!" | "-" ) unary | primary ;
primary        → NUMBER | STRING | "true" | "false" | "nil" | "(" expression ")" | IDENTIFIER;
"""


class Parser:
    """
    Grammar notation
        Code representation
    Terminal
        Code to match and consume a token
    Nonterminal
        Call to that rule’s function
    |
        if or switch statement
    * or +
        while or for loop
    ?
        if statement
    """

    def __init__(self, tokens: list[Token], error_callback: Callable):
        self.tokens = tokens
        self.current = 0
        self.propagate_err = error_callback

    def parsee(self):
        try:
            return self.expression()
        except ParserException as e:
            self.propagate_err(e)
            return None

    def parses(self) -> list[Stmt]:
        statements = []
        while not self.is_at_end():
            statements.append(self.declaration())
        return statements

    ######################
    # utils
    ######################
    def previous(self) -> Token:
        return self.tokens[self.current - 1]

    def peek(self) -> Token:
        return self.tokens[self.current]

    def is_at_end(self) -> bool:
        return self.peek().kind == TokenType.EOF

    def advance(self):
        if not self.is_at_end():
            self.current += 1
        return self.previous()

    def check(self, token_type: TokenType) -> bool:
        if self.is_at_end():
            return False
        return self.peek().kind == token_type

    def match(self, *token_types: TokenType) -> bool:
        for token_type in token_types:
            if self.check(token_type):
                self.advance()
                return True
        return False

    def consume(self, token_type: TokenType, message: str):
        if self.check(token_type):
            return self.advance()

        raise ParserException(self.peek(), message)

    def synchronize(self):
        self.advance()

        while not self.is_at_end():
            if self.previous().kind == TokenType.SEMICOLON:
                return

            match self.peek().kind:
                case (
                    TokenType.CLASS
                    | TokenType.FUN
                    | TokenType.VAR
                    | TokenType.FOR
                    | TokenType.IF
                    | TokenType.WHILE
                    | TokenType.RETURN
                ):
                    return
            self.advance()

    def block(self) -> list[Stmt]:
        statements: list[Stmt] = []
        while not self.check(TokenType.RIGHT_BRACE) and not self.is_at_end():
            statements.append(self.declaration())
        self.consume(TokenType.RIGHT_BRACE, "Expect '}' after block.")
        return statements

    ######################
    # statement grammar
    ######################
    def declaration(self) -> Stmt:
        try:
            if self.match(TokenType.VAR):
                return self.var_declaration()
            return self.statement()
        except ParserException as e:
            self.propagate_err(e)
            self.synchronize()

    def statement(self) -> Stmt:
        if self.match(TokenType.IF):
            return self.if_statement()
        if self.match(TokenType.PRINT):
            return self.print_statement()
        if self.match(TokenType.WHILE):
            return self.while_statement()
        if self.match(TokenType.FOR):
            return self.for_statement()
        if self.match(TokenType.LEFT_BRACE):
            return Stmt.Block(self.block())
        return self.expression_statement()

    def var_declaration(self) -> Stmt:
        name: Token = self.consume(TokenType.IDENTIFIER, "Expect variable name.")
        initializer: Expr = None
        if self.match(TokenType.EQUAL):
            initializer = self.expression()
        self.consume(TokenType.SEMICOLON, "Expect ';' after value.")
        return Stmt.Var(name, initializer)

    def print_statement(self) -> Stmt:
        value: Expr = self.expression()
        self.consume(TokenType.SEMICOLON, "Expect ';' after value.")
        return Stmt.Print(value)

    def expression_statement(self) -> Stmt:
        expr: Expr = self.expression()
        self.consume(TokenType.SEMICOLON, "Expect ';' after value.")
        return Stmt.Expression(expr)

    def if_statement(self) -> Stmt:
        # ifStmt         → "if" "(" expression ")" statement ( "else" statement )? ;
        self.consume(TokenType.LEFT_PAREN, "Expect '(' after 'if'.")
        condition: Expr = self.expression()
        self.consume(TokenType.RIGHT_PAREN, "Expect ')' after if condition.")
        then_branch: Stmt = self.statement()
        else_branch: Stmt = None
        if self.match(TokenType.ELSE):
            else_branch = self.statement()
        return Stmt.If(condition, then_branch, else_branch)

    def while_statement(self) -> Stmt:
        self.consume(TokenType.LEFT_PAREN, "Expect '(' after 'while'.")
        condition: Expr = self.expression()
        self.consume(TokenType.RIGHT_PAREN, "Expect ')' after condition.")
        body: Stmt = self.statement()
        return Stmt.While(condition, body)

    # forStmt → "for" "(" ( varDecl | exprStmt | ";" ) expression? ";" expression? ")" statement ;
    def for_statement(self) -> Stmt:
        # desugring concept
        self.consume(TokenType.LEFT_PAREN, "Expect '(' after 'for'.")

        initializer: Stmt = None
        if self.match(TokenType.SEMICOLON):
            initializer = None
        elif self.match(TokenType.VAR):
            initializer = self.var_declaration()
        else:
            initializer = self.expression_statement()

        condition: Expr = None
        if not self.check(TokenType.SEMICOLON):
            condition = self.expression()
        self.consume(TokenType.SEMICOLON, "Expect ';' after loop condition.")

        incr: Expr = None
        if not self.check(TokenType.RIGHT_PAREN):
            incr = self.expression()
        self.consume(TokenType.RIGHT_PAREN, "Expect ')' after for clauses.")

        body: Stmt = self.statement()

        if incr is not None:
            body = Stmt.Block([body, Stmt.Expression(incr)])

        if condition is None:
            condition = Expr.Literal(True)

        body = Stmt.While(condition, body)

        if initializer is not None:
            body = Stmt.Block([initializer, body])

        return body

    ######################
    # expression grammar
    ######################
    def expression(self) -> Expr:
        return self.comma()

    def comma(self) -> Expr:
        # comma -> (literal <- evaluated and ignored, literal <- used as result)
        # comma      → assignment ( "," assignment )* ;
        expr = self.assignment()
        while self.match(TokenType.COMMA):
            right: Expr = self.assignment()
            expr = Expr.Comma(expr, right)

        return expr

    def assignment(self) -> Expr:
        # assignment → IDENTIFIER "=" assignment | logic_or;
        expr: Expr = self.logic_or()

        if self.match(TokenType.EQUAL):
            eq: Token = self.previous()
            val: Expr = self.assignment()

            if isinstance(expr, Expr.Variable):
                return Expr.Assign(expr.name, val)
            raise ParserException(eq, "Invalid assignment target.")

        return expr

    # logic_or       → logic_and ( "or" logic_and )* ;
    def logic_or(self) -> Expr:
        expr: Expr = self.logic_and()
        while self.match(TokenType.OR):
            operator: Token = self.previous()
            right: Expr = self.logic_and()
            expr = Expr.Logical(expr, operator, right)
        return expr

    # logic_and      → ternary ( "and" ternary )* ;
    def logic_and(self) -> Expr:
        expr: Expr = self.ternary()
        while self.match(TokenType.AND):
            operator: Token = self.previous()
            right: Expr = self.ternary()
            expr = Expr.Logical(expr, operator, right)
        return expr

    def ternary(self) -> Expr:
        # right-associative
        # ternary -> (a + b) ? c : d
        expr = self.equality()
        if self.match(TokenType.QUESTION):
            then_branch = self.expression()
            self.consume(TokenType.COLON, "Expect ':' after then branch.")
            else_branch = self.ternary()
            expr = Expr.Ternary(expr, then_branch, else_branch)
        return expr

    def equality(self) -> Expr:
        # equality       → comparison ( ( "!=" | "==" ) comparison )* ;
        expr: Expr = self.comparison()

        while self.match(
            TokenType.BANG_EQUAL,
            TokenType.EQUAL_EQUAL,
        ):
            operator: Token = self.previous()
            right: Expr = self.comparison()
            expr = Expr.Binary(expr, operator, right)
        return expr

    def comparison(self) -> Expr:
        # comparison     → term ( ( ">" | ">=" | "<" | "<=" ) term )* ;
        expr: Expr = self.term()

        while self.match(
            TokenType.GREATER,
            TokenType.GREATER_EQUAL,
            TokenType.LESS,
            TokenType.LESS_EQUAL,
        ):
            operator: Token = self.previous()
            right: Expr = self.term()
            expr = Expr.Binary(expr, operator, right)
        return expr

    def term(self) -> Expr:
        # term           → factor ( ( "-" | "+" ) factor )* ;
        expr: Expr = self.factor()

        while self.match(
            TokenType.PLUS,
            TokenType.MINUS,
        ):
            operator: Token = self.previous()
            right: Expr = self.factor()
            expr = Expr.Binary(expr, operator, right)
        return expr

    def factor(self) -> Expr:
        # factor         → unary ( ( "/" | "*" ) unary )* ;
        expr: Expr = self.unary()

        while self.match(
            TokenType.SLASH,
            TokenType.STAR,
        ):
            operator: Token = self.previous()
            right: Expr = self.unary()
            expr = Expr.Binary(expr, operator, right)
        return expr

    def unary(self) -> Expr:
        # unary          → ( "!" | "-" ) unary | primary ;
        if self.match(
            TokenType.BANG,
            TokenType.MINUS,
        ):
            operator: Token = self.previous()
            right: Expr = self.unary()
            return Expr.Unary(operator, right)
        return self.primary()

    def primary(self) -> Expr:
        # primary        → NUMBER | STRING | "true" | "false" | "nil" | "(" expression ")" | IDENTIFIER;
        if self.match(TokenType.FALSE):
            return Expr.Literal(False)
        elif self.match(TokenType.TRUE):
            return Expr.Literal(True)
        elif self.match(TokenType.NIL):
            return Expr.Literal(None)
        elif self.match(TokenType.NUMBER, TokenType.STRING):
            return Expr.Literal(self.previous().literal)
        elif self.match(TokenType.LEFT_PAREN):
            expr: Expr = self.expression()
            self.consume(TokenType.RIGHT_PAREN, "Expect ')' after expression.")
            return Expr.Grouping(expr)
        elif self.match(TokenType.IDENTIFIER):
            return Expr.Variable(self.previous())

        # Error productions for missing left operands.

        if self.match(TokenType.BANG_EQUAL, TokenType.EQUAL_EQUAL):
            operator = self.previous()
            self.comparison()
            raise ParserException(operator, "Missing left-hand operand.")

        if self.match(
            TokenType.GREATER,
            TokenType.GREATER_EQUAL,
            TokenType.LESS,
            TokenType.LESS_EQUAL,
        ):
            operator = self.previous()
            self.term()
            raise ParserException(operator, "Missing left-hand operand.")

        if self.match(TokenType.PLUS, TokenType.MINUS):
            operator = self.previous()
            self.factor()
            raise ParserException(operator, "Missing left-hand operand.")

        if self.match(TokenType.STAR, TokenType.SLASH):
            operator = self.previous()
            self.unary()
            raise ParserException(operator, "Missing left-hand operand.")

        if self.match(TokenType.COMMA):
            operator = self.previous()
            self.assignment()
            raise ParserException(operator, "Missing left-hand operand.")

        if self.match(TokenType.QUESTION):
            operator = self.previous()
            self.expression()
            if self.match(TokenType.COLON):
                self.ternary()
            raise ParserException(operator, "Missing condition before '?'.")

        if self.match(TokenType.COLON):
            operator = self.previous()
            self.ternary()
            raise ParserException(
                operator,
                "Missing condition and then-branch before ':'.",
            )
        raise ParserException(self.peek(), "Expect expression.")
