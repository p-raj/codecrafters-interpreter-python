from dataclasses import dataclass


@dataclass
class Error:
    msg: str
    line: int

    def __str__(self):
        return f"[line {self.line}] Error: {self.msg}"


class ScannerException(Exception):
    pass


class UnterminatedStringLiteral(ScannerException):
    def __init__(self, line: int):
        super().__init__(Error("Unterminated string.", line))


class UnexpectedCharacter(ScannerException):
    def __init__(self, ch: str, line: int):
        super().__init__(Error(f"Unexpected character: {ch}", line))
