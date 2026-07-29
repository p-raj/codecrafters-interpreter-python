"""
debug.h / debug.c — the bytecode disassembler for pyvm.

Pretty-prints a Chunk's bytecode for debugging.  Each instruction format
(simple, byte, constant, jump, invoke, closure) has its own helper.
"""

from __future__ import annotations

import sys
from typing import TextIO

from pyvm.chunk import Chunk, OpCode
from pyvm.value import print_value
from pyvm.object import as_function


def _simple_instruction(name: str, offset: int) -> int:
    """static int simpleInstruction(const char* name, int offset)"""
    print(name)
    return offset + 1


def _byte_instruction(name: str, chunk: Chunk, offset: int) -> int:
    """static int byteInstruction(const char* name, Chunk* chunk, int offset)"""
    slot = chunk.code[offset + 1]
    print(f"{name:<16s} {slot:4d}")
    return offset + 2


def _constant_instruction(name: str, chunk: Chunk, offset: int) -> int:
    """static int constantInstruction(...)"""
    constant = chunk.code[offset + 1]
    print(f"{name:<16s} {constant:4d} '", end="")
    print_value(chunk.constants.values[constant])
    print("'")
    return offset + 2


def _invoke_instruction(name: str, chunk: Chunk, offset: int) -> int:
    """static int invokeInstruction(...)"""
    constant = chunk.code[offset + 1]
    arg_count = chunk.code[offset + 2]
    print(f"{name:<16s} ({arg_count} args) {constant:4d} '", end="")
    print_value(chunk.constants.values[constant])
    print("'")
    return offset + 3


def _jump_instruction(name: str, sign: int, chunk: Chunk, offset: int) -> int:
    """static int jumpInstruction(...)"""
    jump = (chunk.code[offset + 1] << 8) | chunk.code[offset + 2]
    print(f"{name:<16s} {offset:4d} -> {offset + 3 + sign * jump}")
    return offset + 3


def disassemble_chunk(chunk: Chunk, name: str, file: TextIO = sys.stdout) -> None:
    """void disassembleChunk(Chunk* chunk, const char* name)"""
    original = sys.stdout
    sys.stdout = file
    try:
        print(f"== {name} ==")
        offset = 0
        while offset < chunk.count:
            offset = disassemble_instruction(chunk, offset)
    finally:
        sys.stdout = original


def disassemble_instruction(chunk: Chunk, offset: int, file: TextIO = sys.stdout) -> int:
    """int disassembleInstruction(Chunk* chunk, int offset)"""
    original = sys.stdout
    sys.stdout = file
    try:
        print(f"{offset:04d} ", end="")

        if offset > 0 and chunk.lines[offset] == chunk.lines[offset - 1]:
            print("\t| ", end="")
        else:
            print(f"{chunk.lines[offset]:4d} ", end="")

        instruction = chunk.code[offset]
        try:
            op = OpCode(instruction)
        except ValueError:
            print(f"Unknown opcode {instruction}")
            return offset + 1

        if op is OpCode.OP_CONSTANT:
            return _constant_instruction("OP_CONSTANT", chunk, offset)
        elif op is OpCode.OP_NIL:
            return _simple_instruction("OP_NIL", offset)
        elif op is OpCode.OP_TRUE:
            return _simple_instruction("OP_TRUE", offset)
        elif op is OpCode.OP_FALSE:
            return _simple_instruction("OP_FALSE", offset)
        elif op is OpCode.OP_POP:
            return _simple_instruction("OP_POP", offset)
        elif op is OpCode.OP_GET_LOCAL:
            return _byte_instruction("OP_GET_LOCAL", chunk, offset)
        elif op is OpCode.OP_SET_LOCAL:
            return _byte_instruction("OP_SET_LOCAL", chunk, offset)
        elif op is OpCode.OP_GET_GLOBAL:
            return _constant_instruction("OP_GET_GLOBAL", chunk, offset)
        elif op is OpCode.OP_DEFINE_GLOBAL:
            return _constant_instruction("OP_DEFINE_GLOBAL", chunk, offset)
        elif op is OpCode.OP_SET_GLOBAL:
            return _constant_instruction("OP_SET_GLOBAL", chunk, offset)
        elif op is OpCode.OP_GET_UPVALUE:
            return _byte_instruction("OP_GET_UPVALUE", chunk, offset)
        elif op is OpCode.OP_SET_UPVALUE:
            return _byte_instruction("OP_SET_UPVALUE", chunk, offset)
        elif op is OpCode.OP_GET_SUPER:
            return _constant_instruction("OP_GET_SUPER", chunk, offset)
        elif op is OpCode.OP_EQUAL:
            return _simple_instruction("OP_EQUAL", offset)
        elif op is OpCode.OP_GET_PROPERTY:
            return _constant_instruction("OP_GET_PROPERTY", chunk, offset)
        elif op is OpCode.OP_SET_PROPERTY:
            return _constant_instruction("OP_SET_PROPERTY", chunk, offset)
        elif op is OpCode.OP_GREATER:
            return _simple_instruction("OP_GREATER", offset)
        elif op is OpCode.OP_LESS:
            return _simple_instruction("OP_LESS", offset)
        elif op is OpCode.OP_ADD:
            return _simple_instruction("OP_ADD", offset)
        elif op is OpCode.OP_SUBTRACT:
            return _simple_instruction("OP_SUBTRACT", offset)
        elif op is OpCode.OP_MULTIPLY:
            return _simple_instruction("OP_MULTIPLY", offset)
        elif op is OpCode.OP_DIVIDE:
            return _simple_instruction("OP_DIVIDE", offset)
        elif op is OpCode.OP_NEGATE:
            return _simple_instruction("OP_NEGATE", offset)
        elif op is OpCode.OP_NOT:
            return _simple_instruction("OP_NOT", offset)
        elif op is OpCode.OP_JUMP:
            return _jump_instruction("OP_JUMP", 1, chunk, offset)
        elif op is OpCode.OP_JUMP_IF_FALSE:
            return _jump_instruction("OP_JUMP_IF_FALSE", 1, chunk, offset)
        elif op is OpCode.OP_LOOP:
            return _jump_instruction("OP_LOOP", -1, chunk, offset)
        elif op is OpCode.OP_CLOSE_UPVALUE:
            return _simple_instruction("OP_CLOSE_UPVALUE", offset)
        elif op is OpCode.OP_PRINT:
            return _simple_instruction("OP_PRINT", offset)
        elif op is OpCode.OP_CALL:
            return _byte_instruction("OP_CALL", chunk, offset)
        elif op is OpCode.OP_INVOKE:
            return _invoke_instruction("OP_INVOKE", chunk, offset)
        elif op is OpCode.OP_SUPER_INVOKE:
            return _invoke_instruction("OP_SUPER_INVOKE", chunk, offset)
        elif op is OpCode.OP_CLOSURE:
            offset += 1
            constant = chunk.code[offset]
            offset += 1
            print(f"{'OP_CLOSURE':<16s} {constant:4d} ", end="")
            print_value(chunk.constants.values[constant])
            print()
            function = as_function(chunk.constants.values[constant])
            for _ in range(function.upvalue_count):
                is_local = chunk.code[offset]
                offset += 1
                index = chunk.code[offset]
                offset += 1
                print(f"{offset - 2:04d}      |                     {'local' if is_local else 'upvalue'} {index}")
            return offset
        elif op is OpCode.OP_RETURN:
            return _simple_instruction("OP_RETURN", offset)
        elif op is OpCode.OP_CLASS:
            return _constant_instruction("OP_CLASS", chunk, offset)
        elif op is OpCode.OP_INHERIT:
            return _simple_instruction("OP_INHERIT", offset)
        elif op is OpCode.OP_METHOD:
            return _constant_instruction("OP_METHOD", chunk, offset)
        else:
            print(f"Unknown opcode {instruction}")
            return offset + 1
    finally:
        sys.stdout = original