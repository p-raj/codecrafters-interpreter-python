import sys
from .scanner import Scanner
from .exception import Error
from .parser import Parser
from .expr import Expr
from .stmt import Stmt
from .utils.ast_printer import AstPrinter
from typing import Literal
from .interpreter import Interpreter
from .token import Token


class Lox:
    def __init__(
        self, mode: Literal["parse", "tokenize", "evaluate", "run"] = "tokenize"
    ):
        self.has_err = False
        self.command = mode
        self.has_rt_err = False

    def run(self, code: str):
        self._run(code)
        if self.has_err:
            sys.exit(65)
        if self.has_rt_err:
            sys.exit(70)

    def _run(self, code: str):

        if self.command == "tokenize":
            tokens: list[Token] = Scanner(code, self.error).tokenize()
            for token in tokens:
                print(token)

        if self.command == "parse":
            tokens: list[Token] = Scanner(code, self.error).tokenize()
            parser: Parser = Parser(tokens, self.error)
            expression: Expr = parser.parsee()

            if self.has_err:
                return

            print(AstPrinter(expression).print())

        if self.command == "evaluate":
            tokens: list[Token] = Scanner(code, self.error).tokenize()
            parser: Parser = Parser(tokens, self.error)
            expression: Expr = parser.parsee()
            if self.has_err:
                return

            intepreter: Interpreter = Interpreter(self.intepreter_error)
            intepreter.interprete(expression)

        if self.command == "run":
            tokens: list[Token] = Scanner(code, self.error).tokenize()
            parser: Parser = Parser(tokens, self.error)
            statements: list[Stmt] = parser.parses()
            if self.has_err:
                return

            intepreter: Interpreter = Interpreter(self.intepreter_error)
            intepreter.interprets(statements)

    def _report(self, error: Error):
        print(error, file=sys.stderr)
        self.has_err = True

    def error(self, err: Error):
        self._report(err)

    def intepreter_error(self, err: Error):
        self.has_rt_err = True
        print(err, file=sys.stderr)
