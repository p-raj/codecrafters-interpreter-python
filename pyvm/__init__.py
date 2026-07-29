"""
pyvm — a Python port of clox (the bytecode VM from *Crafting Interpreters*).

This package implements the Lox language as a tree-walk-free bytecode VM in
Python, mirroring the C structure of clox module-for-module:

    common.py    — shared constants and debug flags
    value.py     — the tagged-union Value type and ValueArray
    chunk.py     — bytecode chunks and the OpCode enum
    scanner.py   — the lexical scanner (tokenizer)
    table.py     — the hash table (globals, string interning, methods, fields)
    object.py    — heap-allocated Obj types (string, function, closure, etc.)
    memory.py    — the mark-and-sweep garbage collector
    debug.py     — the bytecode disassembler
    compiler.py  — the single-pass Pratt parser / bytecode compiler
    vm.py        — the bytecode virtual machine
    main.py      — entry point (REPL + file runner)
"""

from __future__ import annotations

__version__ = "0.1.0"