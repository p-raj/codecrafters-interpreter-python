"""
main.c — entry point for pyvm.

Supports two modes:
  1. REPL: ``python -m pyvm.main`` — read-eval-print loop.
  2. File: ``python -m pyvm.main path/to/script.lox`` — run a file.
"""

from __future__ import annotations

import sys

from pyvm.vm import vm, init_vm, free_vm, interpret, InterpretResult

REPL_LINE_LEN: int = 1024


def _repl() -> None:
    """static void repl()"""
    while True:
        try:
            line = input("> ")
        except EOFError:
            print()
            break
        interpret(line)


def _read_file(path: str) -> str:
    """static char* readFile(const char* path)"""
    try:
        with open(path, "r") as f:
            return f.read()
    except IOError:
        sys.stderr.write(f'Could not open file "{path}".\n')
        sys.exit(74)


def _run_file(path: str) -> None:
    """static void runFile(const char* path)"""
    source = _read_file(path)
    result = interpret(source)

    if result is InterpretResult.INTERPRET_COMPILE_ERROR:
        sys.exit(65)
    if result is InterpretResult.INTERPRET_RUNTIME_ERROR:
        sys.exit(70)


def main(argv: list[str]) -> int:
    """int main(int argc, const char* argv[])"""
    # Init VM.
    init_vm()

    try:
        if len(argv) == 1:
            _repl()
        elif len(argv) == 2:
            _run_file(argv[1])
        else:
            sys.stderr.write("Usage: clox [path]\n")
            sys.exit(64)
    finally:
        # Exit VM.
        free_vm()
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))