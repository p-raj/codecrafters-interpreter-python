import sys
from .scanner import Scanner
from .exception import Error
from .parser import Parser
from .expr import Expr
from .utils.ast_printer import AstPrinter
from typing import Literal
from .interpreter import Interpreter
from .token import Token


class Lox:
    def __init__(self, mode: Literal["parse", "tokenize"] = "tokenize"):
        self.has_err = False
        self.command = mode
        self.has_run_err = False

    def run(self, code: str):
        self._run(code)
        if self.has_err:
            sys.exit(65)
        if self.has_run_err:
            sys.exit(70)

    def _run(self, code: str):

        if self.command == "tokenize":
            tokens: list[Token] = Scanner(code, self.error).tokenize()
            for token in tokens:
                print(token)

        if self.command == "parse":
            tokens: list[Token] = Scanner(code, self.error).tokenize()
            parser: Parser = Parser(tokens, self.error)
            expression: Expr = parser.parse()

            if self.has_err:
                return

            print(AstPrinter(expression).print())

        if self.command == "evaluate":
            tokens: list[Token] = Scanner(code, self.error).tokenize()
            parser: Parser = Parser(tokens, self.error)
            expression: Expr = parser.parse()
            if self.has_err:
                return

            intepreter: Interpreter = Interpreter(self.intepreter_error)
            intepreter.interpret(expression)

    def _report(self, error: Error):
        print(error, file=sys.stderr)
        self.has_err = True

    def error(self, err: Error):
        self._report(err)

    def intepreter_error(self, err: Error):
        print(err, file=sys.stderr)
        self.has_run_err = True
