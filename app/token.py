from enum import StrEnum

from dataclasses import dataclass


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
    QUESTION = "QUESTION"
    COLON = "COLON"

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
    BREAK = "BREAK"

    EOF = "EOF"


@dataclass
class Token:
    kind: TokenType
    lexeme: str
    literal: any
    line: int

    def __hash__(self):
        return hash(f"{self.kind.value}-{self.lexeme}-{self.literal}-{self.line}")

    def __eq__(self, other: Token):
        return (
            self.kind == other.kind
            and self.lexeme == other.lexeme
            and self.literal == other.literal
            and self.line == other.line
        )

    def __str__(self):
        if self.literal is not None:
            return f"{self.kind} {self.lexeme} {self.literal}"
        return f"{self.kind} {self.lexeme} null"
