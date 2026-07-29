"""
scanner.h / scanner.c — the lexical scanner (tokenizer) for pyvm.

A single-pass scanner that converts source text into a stream of Tokens.
In the C version, a module-level ``Scanner`` struct holds the state.  In Python
we use a class for the same purpose.
"""

from __future__ import annotations

from enum import Enum, auto
from typing import Optional


# --------------------------------------------------------------------------- #
# TokenType  (mirrors the C enum)
# --------------------------------------------------------------------------- #

class TokenType(Enum):
    # Single-character tokens.
    TOKEN_LEFT_PAREN = auto()
    TOKEN_RIGHT_PAREN = auto()
    TOKEN_LEFT_BRACE = auto()
    TOKEN_RIGHT_BRACE = auto()
    TOKEN_COMMA = auto()
    TOKEN_DOT = auto()
    TOKEN_MINUS = auto()
    TOKEN_PLUS = auto()
    TOKEN_SEMICOLON = auto()
    TOKEN_SLASH = auto()
    TOKEN_STAR = auto()
    # One or two character tokens.
    TOKEN_BANG = auto()
    TOKEN_BANG_EQUAL = auto()
    TOKEN_EQUAL = auto()
    TOKEN_EQUAL_EQUAL = auto()
    TOKEN_GREATER = auto()
    TOKEN_GREATER_EQUAL = auto()
    TOKEN_LESS = auto()
    TOKEN_LESS_EQUAL = auto()
    # Literals.
    TOKEN_IDENTIFIER = auto()
    TOKEN_STRING = auto()
    TOKEN_NUMBER = auto()
    # Keywords.
    TOKEN_AND = auto()
    TOKEN_CLASS = auto()
    TOKEN_ELSE = auto()
    TOKEN_FALSE = auto()
    TOKEN_FOR = auto()
    TOKEN_FUN = auto()
    TOKEN_IF = auto()
    TOKEN_NIL = auto()
    TOKEN_OR = auto()
    TOKEN_PRINT = auto()
    TOKEN_RETURN = auto()
    TOKEN_SUPER = auto()
    TOKEN_THIS = auto()
    TOKEN_TRUE = auto()
    TOKEN_VAR = auto()
    TOKEN_WHILE = auto()

    TOKEN_ERROR = auto()
    TOKEN_EOF = auto()


# --------------------------------------------------------------------------- #
# Token
# --------------------------------------------------------------------------- #

class Token:
    __slots__ = ("type", "start", "length", "line")

    def __init__(self, type: TokenType, start: str, length: int, line: int) -> None:
        self.type: TokenType = type
        # In C this is a pointer into the source string.  Here we store the
        # substring and the line number.
        self.start: str = start      # the lexeme text
        self.length: int = length
        self.line: int = line

    @property
    def lexeme(self) -> str:
        """The actual source text for this token."""
        return self.start[: self.length]


# --------------------------------------------------------------------------- #
# Scanner
# --------------------------------------------------------------------------- #

class Scanner:
    """Internal scanner state (mirrors the C struct)."""

    def __init__(self, source: str) -> None:
        self.start: str = source
        self.current: str = source
        self.source: str = source
        self.pos: int = 0          # index into source
        self.start_pos: int = 0    # start of the current token
        self.line: int = 1


# Module-level scanner instance (mirrors ``Scanner scanner;`` in scanner.c)
_scanner: Optional[Scanner] = None


def _is_at_end(s: Scanner) -> bool:
    return s.pos >= len(s.source)


def _advance(s: Scanner) -> str:
    """static char advance()"""
    c = s.source[s.pos]
    s.pos += 1
    return c


def _peek(s: Scanner) -> str:
    """static char peek()"""
    if _is_at_end(s):
        return '\0'
    return s.source[s.pos]


def _peek_next(s: Scanner) -> str:
    """static char peekNext()"""
    if s.pos + 1 >= len(s.source):
        return '\0'
    return s.source[s.pos + 1]


def _match(s: Scanner, expected: str) -> bool:
    """static bool match(char expected)"""
    if _is_at_end(s):
        return False
    if s.source[s.pos] != expected:
        return False
    s.pos += 1
    return True


def _is_digit(c: str) -> bool:
    return '0' <= c <= '9'


def _is_alpha(c: str) -> bool:
    return ('a' <= c <= 'z') or ('A' <= c <= 'Z') or c == '_'


def _make_token(s: Scanner, type: TokenType) -> Token:
    """static Token makeToken(TokenType type)"""
    lexeme = s.source[s.start_pos:s.pos]
    return Token(type, lexeme, s.pos - s.start_pos, s.line)


def _error_token(s: Scanner, message: str) -> Token:
    """static Token errorToken(const char* message)"""
    return Token(TokenType.TOKEN_ERROR, message, len(message), s.line)


def _skip_whitespace(s: Scanner) -> None:
    """static void skipWhitespace()"""
    while True:
        c = _peek(s)
        if c in (' ', '\r', '\t'):
            _advance(s)
        elif c == '\n':
            s.line += 1
            _advance(s)
        elif c == '/':
            if _peek_next(s) == '/':
                while _peek(s) != '\n' and not _is_at_end(s):
                    _advance(s)
            else:
                return
        else:
            return


def _string(s: Scanner) -> Token:
    """static Token string()"""
    while _peek(s) != '"' and not _is_at_end(s):
        if _peek(s) == '\n':
            s.line += 1
        _advance(s)

    if _is_at_end(s):
        return _error_token(s, "Unterminated string.")

    _advance(s)  # closing quote
    return _make_token(s, TokenType.TOKEN_STRING)


def _number(s: Scanner) -> Token:
    """static Token number()"""
    while _is_digit(_peek(s)):
        _advance(s)

    # Look for a fractional part.
    if _peek(s) == '.' and _is_digit(_peek_next(s)):
        _advance(s)  # consume the "."
        while _is_digit(_peek(s)):
            _advance(s)
    return _make_token(s, TokenType.TOKEN_NUMBER)


def _check_keyword(s: Scanner, start: int, length: int, rest: str, type: TokenType) -> TokenType:
    """static TokenType checkKeyword(...)"""
    if s.pos - s.start_pos == start + length and s.source[s.start_pos + start : s.start_pos + start + length] == rest:
        return type
    return TokenType.TOKEN_IDENTIFIER


def _identifier_type(s: Scanner) -> TokenType:
    """static TokenType identifierType()"""
    c = s.source[s.start_pos]
    if c == 'a':
        return _check_keyword(s, 1, 2, "nd", TokenType.TOKEN_AND)
    if c == 'c':
        return _check_keyword(s, 1, 4, "lass", TokenType.TOKEN_CLASS)
    if c == 'e':
        return _check_keyword(s, 1, 3, "lse", TokenType.TOKEN_ELSE)
    if c == 'f':
        if s.pos - s.start_pos > 1:
            c2 = s.source[s.start_pos + 1]
            if c2 == 'a':
                return _check_keyword(s, 2, 3, "lse", TokenType.TOKEN_FALSE)
            if c2 == 'o':
                return _check_keyword(s, 2, 1, "r", TokenType.TOKEN_FOR)
            if c2 == 'u':
                return _check_keyword(s, 2, 1, "n", TokenType.TOKEN_FUN)
    if c == 'i':
        return _check_keyword(s, 1, 1, "f", TokenType.TOKEN_IF)
    if c == 'n':
        return _check_keyword(s, 1, 2, "il", TokenType.TOKEN_NIL)
    if c == 'o':
        return _check_keyword(s, 1, 1, "r", TokenType.TOKEN_OR)
    if c == 'p':
        return _check_keyword(s, 1, 4, "rint", TokenType.TOKEN_PRINT)
    if c == 'r':
        return _check_keyword(s, 1, 5, "eturn", TokenType.TOKEN_RETURN)
    if c == 's':
        return _check_keyword(s, 1, 4, "uper", TokenType.TOKEN_SUPER)
    if c == 't':
        if s.pos - s.start_pos > 1:
            c2 = s.source[s.start_pos + 1]
            if c2 == 'h':
                return _check_keyword(s, 2, 2, "is", TokenType.TOKEN_THIS)
            if c2 == 'r':
                return _check_keyword(s, 2, 2, "ue", TokenType.TOKEN_TRUE)
    if c == 'v':
        return _check_keyword(s, 1, 2, "ar", TokenType.TOKEN_VAR)
    if c == 'w':
        return _check_keyword(s, 1, 4, "hile", TokenType.TOKEN_WHILE)
    return TokenType.TOKEN_IDENTIFIER


def _identifier(s: Scanner) -> Token:
    """static Token identifier()"""
    while _is_alpha(_peek(s)) or _is_digit(_peek(s)):
        _advance(s)
    return _make_token(s, _identifier_type(s))


# --------------------------------------------------------------------------- #
# Public API
# --------------------------------------------------------------------------- #

def init_scanner(source: str) -> None:
    """void initScanner(const char* source)"""
    global _scanner
    _scanner = Scanner(source)


def scan_token() -> Token:
    """Token scanToken()"""
    global _scanner
    s = _scanner
    assert s is not None

    _skip_whitespace(s)
    s.start_pos = s.pos

    if _is_at_end(s):
        return _make_token(s, TokenType.TOKEN_EOF)

    c = _advance(s)
    if _is_alpha(c):
        return _identifier(s)
    if _is_digit(c):
        return _number(s)

    if c == '(':
        return _make_token(s, TokenType.TOKEN_LEFT_PAREN)
    if c == ')':
        return _make_token(s, TokenType.TOKEN_RIGHT_PAREN)
    if c == '{':
        return _make_token(s, TokenType.TOKEN_LEFT_BRACE)
    if c == '}':
        return _make_token(s, TokenType.TOKEN_RIGHT_BRACE)
    if c == ';':
        return _make_token(s, TokenType.TOKEN_SEMICOLON)
    if c == ',':
        return _make_token(s, TokenType.TOKEN_COMMA)
    if c == '.':
        return _make_token(s, TokenType.TOKEN_DOT)
    if c == '-':
        return _make_token(s, TokenType.TOKEN_MINUS)
    if c == '+':
        return _make_token(s, TokenType.TOKEN_PLUS)
    if c == '/':
        return _make_token(s, TokenType.TOKEN_SLASH)
    if c == '*':
        return _make_token(s, TokenType.TOKEN_STAR)
    if c == '!':
        return _make_token(s, TokenType.TOKEN_BANG_EQUAL if _match(s, '=') else TokenType.TOKEN_BANG)
    if c == '=':
        return _make_token(s, TokenType.TOKEN_EQUAL_EQUAL if _match(s, '=') else TokenType.TOKEN_EQUAL)
    if c == '<':
        return _make_token(s, TokenType.TOKEN_LESS_EQUAL if _match(s, '=') else TokenType.TOKEN_LESS)
    if c == '>':
        return _make_token(s, TokenType.TOKEN_GREATER_EQUAL if _match(s, '=') else TokenType.TOKEN_GREATER)
    if c == '"':
        return _string(s)

    return _error_token(s, "Unexpected character.")