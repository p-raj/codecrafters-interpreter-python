import sys
from .scanner import Scanner
from .exception import Error
from .parser import Parser
from .expr import Expr
from .utils.ast_printer import AstPrinter
from typing import Literal


class Lox:
    def __init__(self, mode: Literal["parse", "tokenize"] = "tokenize"):
        self.has_err = False
        self.command = mode

    def run(self, code: str):
        self._run(code)
        if self.has_err:
            sys.exit(65)

    def _run(self, code: str):
        tokens = Scanner(code, self.error).tokenize()
        if self.command == "tokenize":
            for token in tokens:
                print(token)

        if self.command == "parse":
            parser: Parser = Parser(tokens, self.error)
            expression: Expr = parser.parse()

            if self.has_err:
                return

            print(AstPrinter(expression).print())

    def _report(self, error: Error):
        print(error, file=sys.stderr)
        self.has_err = True

    def error(self, err: Error):
        self._report(err)
