import sys
from .scanner import Scanner


class Lox:
    def __init__(self):
        self.has_err = False

    def run(self, code: str):
        self._run(code)
        if self.has_err:
            sys.exit(65)

    def _run(self, code: str):
        tokens, errors = Scanner(code).tokenize()
        for error in errors:
            print(error, file=sys.stderr)
            self.has_err = True
        for token in tokens:
            print(token)
