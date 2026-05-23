from enum import StrEnum
from dataclasses import dataclass
from .exception import ScannerException, UnterminatedStringLiteral, UnexpectedCharacter


class TokenType(StrEnum):
    LEFT_PAREN = "LEFT_PAREN"
    RIGHT_PAREN = "RIGHT_PAREN"
    LEFT_BRACE = "LEFT_BRACE"
    RIGHT_BRACE = "RIGHT_BRACE"
    COMMA = "COMMA"
    DOT = "DOT"
    MINUS = "MINUS"
    PLUS = "PLUS"
    SEMICOLON = "SEMICOLON"
    SLASH = "SLASH"
    STAR = "STAR"

    BANG = "BANG"
    BANG_EQUAL = "BANG_EQUAL"
    EQUAL = "EQUAL"
    EQUAL_EQUAL = "EQUAL_EQUAL"
    GREATER = "GREATER"
    GREATER_EQUAL = "GREATER_EQUAL"
    LESS = "LESS"
    LESS_EQUAL = "LESS_EQUAL"

    IDENTIFIER = "IDENTIFIER"
    STRING = "STRING"
    NUMBER = "NUMBER"

    AND = "AND"
    CLASS = "CLASS"
    ELSE = "ELSE"
    FALSE = "FALSE"
    FUN = "FUN"
    FOR = "FOR"
    IF = "IF"
    NIL = "NIL"
    OR = "OR"
    PRINT = "PRINT"
    RETURN = "RETURN"
    SUPER = "SUPER"
    THIS = "THIS"
    TRUE = "TRUE"
    VAR = "VAR"
    WHILE = "WHILE"

    EOF = "EOF"


@dataclass
class Token:
    kind: TokenType
    lexeme: str
    literal: any
    line: int

    def __str__(self):
        if self.literal is not None:
            return f"{self.kind} {self.lexeme} {self.literal}"
        return f"{self.kind} {self.lexeme} null"


class Scanner:
    def __init__(self, code: str):
        self.code = code
        self.line = 1
        self.strt = 0
        self.curr = 0
        self.tokens = []
        self.errors = []

    def get_text(self):
        return self.code[self.strt : self.curr]

    def is_end(self):
        return self.curr >= len(self.code)

    def read(self):
        ch = self.code[self.curr]
        self.curr += 1
        return ch

    def peek(self, offset: int = 0) -> None | str:
        if self.is_end():
            return
        return self.code[self.curr + offset]

    def is_match(self, ch: str) -> bool:
        if self.peek() == ch:
            self.read()
            return True
        return False

    def add_token(self, kind: TokenType, literal: any = None):
        self.tokens.append(Token(kind, self.get_text(), literal, self.line))

    def add_error(self, exception):
        self.errors.append(exception)

    def tokenize(self) -> tuple(list[Token], list[ScannerException]):
        while not self.is_end():
            self.strt = self.curr
            self._tokenize()

        self.tokens.append(Token(TokenType.EOF, "", None, self.line))
        return self.tokens, self.errors

    def is_digit(self, ch: str | None) -> bool:
        if ch is None:
            return False
        return ch >= "0" and ch <= "9"

    def is_alpha(self, ch: str | None) -> bool:
        if ch is None:
            return False
        return (ch >= "a" and ch <= "z") or (ch >= "A" and ch <= "Z") or ch == "_"

    def isAlphaNumeric(self, ch: str) -> bool:
        return self.is_alpha(ch) or self.is_digit(ch)

    def parse_number(self):
        while self.is_digit(self.peek()):
            self.read()

        if self.peek() == "." and self.is_digit(self.peek(offset=1)):
            self.read()

        while self.is_digit(self.peek()):
            self.read()

        num_ = float(self.get_text())
        self.add_token(TokenType.NUMBER, num_)

    def parse_identifier(self):
        keywords = {
            "and": TokenType.AND,
            "class": TokenType.CLASS,
            "else": TokenType.ELSE,
            "false": TokenType.FALSE,
            "for": TokenType.FOR,
            "fun": TokenType.FUN,
            "if": TokenType.IF,
            "nil": TokenType.NIL,
            "or": TokenType.OR,
            "print": TokenType.PRINT,
            "return": TokenType.RETURN,
            "super": TokenType.SUPER,
            "this": TokenType.THIS,
            "true": TokenType.TRUE,
            "var": TokenType.VAR,
            "while": TokenType.WHILE,
        }

        while self.isAlphaNumeric(self.peek()):
            self.read()
        kind = keywords.get(self.code[self.strt, self.curr])
        if not kind:
            kind = TokenType.IDENTIFIER
        self.add_token(kind)

    def _tokenize(self):
        ch = self.read()
        match ch:
            case "(":
                self.add_token(TokenType.LEFT_PAREN)
            case ")":
                self.add_token(TokenType.RIGHT_PAREN)
            case "{":
                self.add_token(TokenType.LEFT_BRACE)
            case "}":
                self.add_token(TokenType.RIGHT_BRACE)
            case ",":
                self.add_token(TokenType.COMMA)
            case ";":
                self.add_token(TokenType.SEMICOLON)
            case ".":
                self.add_token(TokenType.DOT)
            case "-":
                self.add_token(TokenType.MINUS)
            case "+":
                self.add_token(TokenType.PLUS)
            case "*":
                self.add_token(TokenType.STAR)
            case "/":
                if self.is_match("/"):
                    while self.peek() != "\n" and not self.is_end():
                        # comments to the end of the line
                        self.read()
                else:
                    self.add_token(TokenType.SLASH)
            case "!":
                if self.is_match("="):
                    self.add_token(TokenType.BANG_EQUAL)
                else:
                    self.add_token(TokenType.BANG)
            case ">":
                if self.is_match("="):
                    self.add_token(TokenType.GREATER_EQUAL)
                else:
                    self.add_token(TokenType.GREATER)
            case "<":
                if self.is_match("="):
                    self.add_token(TokenType.LESS_EQUAL)
                else:
                    self.add_token(TokenType.LESS)
            case "=":
                if self.is_match("="):
                    self.add_token(TokenType.EQUAL_EQUAL)
                else:
                    self.add_token(TokenType.EQUAL)
            case " " | "\r" | "\t":
                # ignore whitespace
                pass
            case "\n":
                self.line += 1
            case '"':
                str_ = ""
                while self.peek() != '"' and not self.is_end():
                    if self.peek() == "\n":
                        self.line += 1
                    str_ += self.read()
                if self.is_end():
                    self.add_error(UnterminatedStringLiteral(self.line))
                else:
                    self.read()
                    self.add_token(TokenType.STRING, str_)
            case _:
                if self.is_digit(ch):
                    self.parse_number()
                elif self.is_alpha(ch):
                    self.parse_identifier()
                else:
                    self.add_error(UnexpectedCharacter(ch, self.line))
