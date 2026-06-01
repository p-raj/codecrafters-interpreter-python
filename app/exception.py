from dataclasses import dataclass
from .token import Token, TokenType


@dataclass
class Error:
    msg: str
    line: int
    loc: str | None = None

    def __str__(self):
        if self.loc:
            return f"[line {self.line}] Error {self.loc}: {self.msg}"
        return f"[line {self.line}] Error: {self.msg}"


class ScannerException(Exception):
    pass


class UnterminatedStringLiteral(ScannerException):
    def __init__(self, line: int):
        super().__init__(Error("Unterminated string.", line))


class UnexpectedCharacter(ScannerException):
    def __init__(self, ch: str, line: int):
        super().__init__(Error(f"Unexpected character: {ch}", line))


class ParserException(Exception):
    def __init__(self, token: Token, message: str):
        if token.kind == TokenType.EOF:
            super().__init__(Error(msg=message, line=token.line, loc="at end"))
        else:
            super().__init__(Error(msg=message, line=token.line, loc=token.lexeme))


class InterpreterException(Exception):
    def __init__(self, token: Token, message: str):
        super().__init__(Error(msg=message, line=token.line))


class ExecutionException(Exception):
    pass


class BreakExecutionException(ExecutionException):
    pass


class ReturnExecutionException(ExecutionException):
    def __init__(self, value: object):
        self.value = value
