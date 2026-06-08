from .token import Token, TokenType
from .expr import Expr
from .stmt import Stmt
from .exception import ParserException
from typing import Callable

"""
expression     -> assignment ;
assignment     -> IDENTIFIER "=" assignment | equality;
equality       -> comparison ( ( "!=" | "==" ) comparison )* ;
comparison     -> term ( ( ">" | ">=" | "<" | "<=" ) term )* ;
term  -> factor ( ( "-" | "+" ) factor )* ;
factor-> unary ( ( "/" | "*" ) unary )* ;
unary -> ( "!" | "-" ) unary | primary ;
primary        -> NUMBER | STRING | "true" | "false" | "nil" | "(" expression ")" | IDENTIFIER;
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
        self.loop_depth = 0

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

    def peek(self, offset: int = 0) -> Token:
        return self.tokens[self.current + offset]

    def is_at_end(self) -> bool:
        return self.peek().kind == TokenType.EOF

    def advance(self):
        if not self.is_at_end():
            self.current += 1
        return self.previous()

    def check(self, token_type: TokenType, offset: int = 0) -> bool:
        if self.is_at_end():
            return False
        return self.peek(offset).kind == token_type

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
    # function helpers
    ######################
    def function_body(self, kind: str) -> tuple[list[Token], list[Stmt]]:
        self.consume(TokenType.LEFT_PAREN, "Expect '(' after " + kind + " name.")

        parameters: list[Token] = []

        if not self.check(TokenType.RIGHT_PAREN):
            while True:
                if len(parameters) >= 255:
                    raise ParserException(
                        self.peek(),
                        "Can't have more than 255 parameters.",
                    )

                parameters.append(
                    self.consume(TokenType.IDENTIFIER, "Expect parameter name.")
                )

                if not self.match(TokenType.COMMA):
                    break

        self.consume(TokenType.RIGHT_PAREN, "Expect ')' after parameters.")

        self.consume(
            TokenType.LEFT_BRACE,
            f"Expect '{{' before {kind} body.",
        )

        body = self.block()

        return parameters, body

    ######################
    # statement grammar
    ######################
    def declaration(self) -> Stmt:
        """
        declaration ->  classDecl
                        | funDecl
                        | varDecl
                        | statement
                        ;
        statement   -> exprStmt
                       | forStmt
                       | ifStmt
                       | printStmt
                       | returnStmt
                       | whileStmt
                       | block ;
        classDecl     -> "class" IDENTIFIER ( "<" IDENTIFIER )?
                         "{" function* "}" ;
        funDecl       -> "fun" function ;
        function      -> IDENTIFIER "(" parameters? ")" block ;
        # Note function != funDecl
        # there is no fun to begin with
        # this is going to conflict with call expr
        parameters    -> IDENTIFIER ( "," IDENTIFIER )* ;
        returnStmt    -> "return" expression? ";" ;
        """
        try:
            if self.check(TokenType.CLASS) and self.check(TokenType.IDENTIFIER, +1):
                self.advance()
                return self.class_declaration()
            if self.check(TokenType.FUN) and self.check(TokenType.IDENTIFIER, +1):
                self.advance()
                return self.function("function")
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
        if self.match(TokenType.RETURN):
            return self.returnStatement()
        if self.match(TokenType.WHILE):
            return self.while_statement()
        if self.match(TokenType.FOR):
            return self.for_statement()
        if self.match(TokenType.BREAK):
            return self.break_statement()
        if self.match(TokenType.LEFT_BRACE):
            return Stmt.Block(self.block())
        return self.expression_statement()

    def class_declaration(self) -> Stmt:
        name: Token = self.consume(TokenType.IDENTIFIER, "Expect class name.")
        superclass: Expr.Variable | None = None
        if self.match(TokenType.LESS):
            self.consume(TokenType.IDENTIFIER, "Expect superclass name.")
            superclass = Expr.Variable(self.previous())
        self.consume(TokenType.LEFT_BRACE, "Expect '{' before class body.")
        methods: list[Stmt.Function] = []
        while not self.check(TokenType.RIGHT_BRACE) and not self.is_at_end():
            methods.append(self.function("method"))
        self.consume(TokenType.RIGHT_BRACE, "Expect '}' after class body.")
        return Stmt.Class(name, superclass, methods)

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

    def returnStatement(self) -> Stmt:
        keyword: Token = self.previous()
        value: Expr = None
        if not self.check(TokenType.SEMICOLON):
            value = self.expression()
        self.consume(TokenType.SEMICOLON, "Expect ';' after return value.")
        return Stmt.Return(keyword, value)

    def expression_statement(self) -> Stmt:
        expr: Expr = self.expression()
        self.consume(TokenType.SEMICOLON, "Expect ';' after value.")
        return Stmt.Expression(expr)

    def function(self, kind: str) -> Stmt.Function:
        name = self.consume(TokenType.IDENTIFIER, "Expect " + kind + " name.")
        params, body = self.function_body(kind)
        return Stmt.Function(name, params, body)

    def if_statement(self) -> Stmt:
        # ifStmt-> "if" "(" expression ")" statement ( "else" statement )? ;
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
        self.loop_depth += 1
        try:
            body: Stmt = self.statement()
        finally:
            self.loop_depth -= 1
        return Stmt.While(condition, body)

    # forStmt -> "for" "(" ( varDecl | exprStmt | ";" ) expression? ";" expression? ")" statement ;
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

        self.loop_depth += 1
        try:
            body: Stmt = self.statement()
        finally:
            self.loop_depth -= 1

        if incr is not None:
            body = Stmt.Block([body, Stmt.Expression(incr)])

        if condition is None:
            condition = Expr.Literal(True)

        body = Stmt.While(condition, body)

        if initializer is not None:
            body = Stmt.Block([initializer, body])

        return body

    def break_statement(self) -> Stmt:
        if self.loop_depth == 0:
            raise ParserException(self.previous(), "Expect break in a loop")
        self.consume(TokenType.SEMICOLON, "Expect ';' after break.")
        return Stmt.Break()

    ######################
    # expression grammar
    ######################
    def expression(self) -> Expr:
        return self.comma()

    def comma(self) -> Expr:
        # comma -> (literal <- evaluated and ignored, literal <- used as result)
        # comma      -> assignment ( "," assignment )* ;
        expr = self.assignment()
        while self.match(TokenType.COMMA):
            right: Expr = self.assignment()
            expr = Expr.Comma(expr, right)

        return expr

    def assignment(self) -> Expr:
        # assignment -> ( call "." )? IDENTIFIER "=" assignment | logic_or;
        expr: Expr = self.logic_or()

        if self.match(TokenType.EQUAL):
            eq: Token = self.previous()
            val: Expr = self.assignment()

            if isinstance(expr, Expr.Variable):
                return Expr.Assign(expr.name, val)
            elif isinstance(expr, Expr.Get):
                get_: Expr.Get = expr
                return Expr.Set(get_.objekt, get_.name, val)
            raise ParserException(eq, "Invalid assignment target.")

        return expr

    # logic_or       -> logic_and ( "or" logic_and )* ;
    def logic_or(self) -> Expr:
        expr: Expr = self.logic_and()
        while self.match(TokenType.OR):
            operator: Token = self.previous()
            right: Expr = self.logic_and()
            expr = Expr.Logical(expr, operator, right)
        return expr

    # logic_and      -> ternary ( "and" ternary )* ;
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
        # equality       -> comparison ( ( "!=" | "==" ) comparison )* ;
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
        # comparison     -> term ( ( ">" | ">=" | "<" | "<=" ) term )* ;
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
        # term  -> factor ( ( "-" | "+" ) factor )* ;
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
        # factor -> unary ( ( "/" | "*" ) unary )* ;
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
        # unary -> ( "!" | "-" ) unary | call ;
        if self.match(
            TokenType.BANG,
            TokenType.MINUS,
        ):
            operator: Token = self.previous()
            right: Expr = self.unary()
            return Expr.Unary(operator, right)
        return self.call()

    def call(self) -> Expr:
        # call -> primary ( "(" arguments? ")" | "." IDENTIFIER )* ;
        # arguments      → assignment ( "," assignment )* ;
        expr: Expr = self.primary()

        while True:
            if self.match(TokenType.LEFT_PAREN):
                expr = self.finishCall(expr)
            elif self.match(TokenType.DOT):
                name: Token = self.consume(
                    TokenType.IDENTIFIER, "Expect property name after '.'."
                )
                expr = Expr.Get(expr, name)
            else:
                break

        return expr

    def finishCall(self, callee: Expr) -> Expr:
        arguments: list[Expr] = []
        if not self.check(TokenType.RIGHT_PAREN):
            while True:
                # arguments      → assignment ( "," assignment )* ;
                # Note: we have introduced the comma operator
                # so we cant jump to expression
                arguments.append(self.assignment())
                if not self.match(TokenType.COMMA):
                    break
                if len(arguments) >= 255:
                    raise ParserException(
                        self.peek(), "Can't have more than 255 arguments."
                    )
        paren: Token = self.consume(
            TokenType.RIGHT_PAREN, "Expect ')' after arguments."
        )
        return Expr.Call(callee, paren, arguments)

    def lambda_expression(self) -> Expr:
        params, body = self.function_body("lambda")
        return Expr.Lambda(params, body)

    def primary(self) -> Expr:
        # primary     ->  "true" | "false" | "nil" | "this"
        #               | NUMBER | STRING | IDENTIFIER | "(" expression ")"
        #               | "super" "." IDENTIFIER ;
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
        elif self.match(TokenType.FUN):
            return self.lambda_expression()
        elif self.match(TokenType.THIS):
            return Expr.This(self.previous())
        elif self.match(TokenType.SUPER):
            keyword = self.previous()
            self.consume(TokenType.DOT, "Expect '.' after 'super'.")
            method = self.consume(
                TokenType.IDENTIFIER, "Expect superclass method name."
            )
            return Expr.Super(keyword, method)
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
