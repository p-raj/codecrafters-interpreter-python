from .token import Token, TokenType
from .expr import Expr
from .exception import ParserException
from typing import Callable

"""
expression     → equality ;
equality       → comparison ( ( "!=" | "==" ) comparison )* ;
comparison     → term ( ( ">" | ">=" | "<" | "<=" ) term )* ;
term           → factor ( ( "-" | "+" ) factor )* ;
factor         → unary ( ( "/" | "*" ) unary )* ;
unary          → ( "!" | "-" ) unary | primary ;
primary        → NUMBER | STRING | "true" | "false" | "nil" | "(" expression ")" ;
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

    def parse(self):
        try:
            return self.expression()
        except ParserException as e:
            self.propagate_err(e)
            return None

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
        # assignment → IDENTIFIER "=" assignment | equality ;
        return self.ternary()

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
        # primary        → NUMBER | STRING | "true" | "false" | "nil" | "(" expression ")" ;
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
                "MiParserException(ssing condition and then-branch before ':'.",
            )
        raise ParserException(self.peek(), "Expect expression.")
