"""
chunk.h / chunk.c — bytecode chunks for pyvm.

A Chunk is a dynamic array of bytes (the bytecode) plus a parallel array of
line numbers (for runtime error reporting) and a constant pool (ValueArray).

In the C version, chunks are manually managed with grow/free macros.  In Python
we use lists, but preserve the same structure and comments.
"""

from __future__ import annotations

from enum import IntEnum
from typing import Optional

from pyvm.value import Value, ValueArray

# --------------------------------------------------------------------------- #
# OpCode  (mirrors the C enum)
# --------------------------------------------------------------------------- #

# In our bytecode format each instruction has a one-byte operation code (opcode).
# That number controls what kind of instruction we're dealing with.  Each opcode
# determines how many operand bytes it has and what they mean.  Each time we add
# a new opcode to clox, we specify what its operands look like (the instruction
# format).
class OpCode(IntEnum):
    # The compiled chunk needs to not only contain the values 1 and 2,
    # but know when to produce them so that they are printed in the right order.
    # We need an instruction that produces a particular constant.
    # OP-CODE OPERAND(VALUE-INDEX) => 2 bytes
    OP_CONSTANT = 0
    # Having OP CODES in bytecode makes the VM go faster than having the value
    # be accessed via index.
    OP_NIL = 1
    OP_TRUE = 2
    OP_FALSE = 3
    # Evaluate expression for assignment.
    OP_POP = 4
    # Variable GET
    # Local var.
    OP_GET_LOCAL = 5
    # Read global var.
    OP_GET_GLOBAL = 6
    # Define global variables.
    OP_DEFINE_GLOBAL = 7
    OP_GET_UPVALUE = 8
    # Variable SET
    OP_SET_LOCAL = 9
    # Assignment.
    OP_SET_GLOBAL = 10
    OP_SET_UPVALUE = 11
    OP_GET_SUPER = 12
    # ==, !=, <, >, <=, and >=
    # The expression a != b has the same semantics as !(a == b), so the
    # compiler is free to compile the former as if it were the latter.  Instead
    # of a dedicated OP_NOT_EQUAL instruction, it can output an OP_EQUAL
    # followed by an OP_NOT.  Likewise, a <= b is the same as !(a > b) and
    # a >= b is !(a < b).  Thus, we only need three new instructions.
    OP_EQUAL = 13
    OP_GET_PROPERTY = 14
    OP_SET_PROPERTY = 15
    OP_GREATER = 16
    OP_LESS = 17
    # OP-CODE => 1 byte
    # Binary Ops
    # Arithmetic operations.
    OP_ADD = 18
    OP_SUBTRACT = 19
    OP_MULTIPLY = 20
    OP_DIVIDE = 21
    OP_NOT = 22
    # Unary Ops
    # var a = 1.2; print -a => -1.2
    OP_NEGATE = 23
    OP_PRINT = 24
    OP_JUMP = 25
    OP_JUMP_IF_FALSE = 26
    OP_LOOP = 27
    # Function call.
    OP_CALL = 28
    # In other words, this single instruction combines the operands of the
    # OP_GET_PROPERTY and OP_CALL instructions it replaces, in that order.  It
    # really is a fusion of those two instructions.
    OP_INVOKE = 29
    OP_SUPER_INVOKE = 30
    # It takes a single operand that represents a constant table index for the
    # function.  It wraps the function.
    OP_CLOSURE = 31
    # When we are about to hoist a captured value from stack to heap.
    # The instruction requires no operand.  We know that the variable will
    # always be right on top of the stack at the point that this instruction
    # executes.  We declare the instruction.
    OP_CLOSE_UPVALUE = 32
    # Pops off the last stack value and returns.
    OP_RETURN = 33
    OP_CLASS = 34
    OP_INHERIT = 35
    OP_METHOD = 36


# --------------------------------------------------------------------------- #
# Chunk  (dynamic array of bytes + line numbers + constants)
# --------------------------------------------------------------------------- #

# Bytecode is a series of instructions.  We'll store some other data along with
# the instructions, create a struct to hold it all.  This is simply a wrapper
# around an array of bytes (dynamic array).
class Chunk:
    def __init__(self) -> None:
        # How many entries are there.
        self.count: int = 0
        # How many it can hold.
        self.capacity: int = 0
        # The bytecode itself.
        self.code: list[int] = []
        # Line number support.
        # Every time we touch the code array we make a corresponding change to
        # the line number array.  In the chunk, we store a separate array of
        # integers that parallels the bytecode.  When a runtime error occurs,
        # we look up the line number at the same index as the current
        # instruction's offset in the code array.
        self.lines: list[int] = []
        # Each chunk will carry with it a list of the values that appear as
        # literals in the program.  To keep things simpler, we'll put all
        # constants in there, even simple integers.
        self.constants: ValueArray = ValueArray()


def init_chunk(chunk: Chunk) -> None:
    """void initChunk(Chunk* chunk)"""
    # This reduction is a key reason why our new interpreter will be faster than
    # jlox.  You can think of bytecode as a sort of compact serialization of the
    # AST, highly optimized for how the interpreter will deserialize it in the
    # order it needs as it executes.
    chunk.count = 0
    chunk.capacity = 0
    chunk.code = []
    chunk.lines = []
    chunk.constants = ValueArray()


def free_chunk(chunk: Chunk) -> None:
    """void freeChunk(Chunk* chunk)"""
    chunk.code = []
    chunk.lines = []
    chunk.constants.free()
    init_chunk(chunk)


def write_chunk(chunk: Chunk, byte: int, line: int) -> None:
    """void writeChunk(Chunk* chunk, uint8_t byte, int line)"""
    # Can it hold one more?  In Python lists grow automatically, but we keep
    # the capacity/count fields for parity with the C version.
    chunk.capacity = max(chunk.capacity, len(chunk.code) + 1)
    chunk.code.append(byte & 0xFF)
    chunk.lines.append(line)
    chunk.count = len(chunk.code)


def add_constant(chunk: Chunk, value: Value) -> int:
    """int addConstant(Chunk* chunk, Value value)

    This quote from *Crafting Interpreters* describes a classic and nasty
    **garbage collection bug** where a newly created object is prematurely
    destroyed ("swept") because the virtual machine doesn't realize it is still
    being used.

    Here is a step-by-step breakdown of how this crash happens:

    ### 1. The Vulnerable State (The C Stack)

    When a new constant object (like a string literal or a number) is created
    during compilation, it is passed as an argument to ``add_constant()``.  At
    this exact moment:

    * The object exists in memory, but it has **not** been added to the
      constant table yet.
    * The *only* reference to this object is a local variable/parameter sitting
      on the **C stack** (the native execution stack of the interpreter itself,
      not the VM's custom values stack).

    ### 2. Triggering the Allocation

    Inside ``add_constant()``, the VM tries to append this new object to its
    table of constants.  However, if the table is currently full, it needs to
    dynamically resize (grow its capacity).  To do this, it calls a memory
    management function like ``reallocate()``.

    ### 3. The Trap: A Forced GC Run

    Because you are using a "stress testing" mode or have hit a memory
    threshold, calling ``reallocate()`` immediately triggers a garbage
    collection (``collect_garbage()``) to clear up space *before* allocating new
    memory.

    ### 4. The GC Blind Spot

    The garbage collector starts its **Mark Phase** to find all reachable
    objects.  It scans the VM's roots: global variables, the VM value stack,
    active call frames, etc.

    * **The Problem:** The GC does not automatically know how to scan the
      native C stack parameters.
    * Because the new object is *only* living in that ``add_constant()``
      function parameter on the C stack, the GC's wavefront completely misses
      it.  It leaves the object unmarked (**White**).

    ### 5. The Sweep and Crash

    After marking, the GC enters the **Sweep Phase**.  It looks at our
    brand-new constant object, sees that its ``is_marked`` flag is ``false``,
    concludes that it is unreachable garbage, and **frees its memory**.

    When the GC finishes and control returns to ``add_constant()``, the
    function tries to insert the object into the newly resized table.  But the
    pointer now points to freed, unallocated, or corrupted memory.

    **Result:** The VM attempts to read or write to a dead object and
    immediately **crashes**.

    ---

    ### How to Fix It

    To fix this kind of bug, the VM developer must ensure the object is
    "hidden" somewhere the GC *does* look before any resizing happens.  Usually
    this means temporarily pushing the new object onto the VM's own stack
    (which the GC actively marks as a root) before calling ``add_constant()``,
    and popping it off once it is safely inside the table.
    """
    # The new object being added to the constant table is passed to
    # add_constant().  At that moment, the object can be found only in the
    # parameter to that function on the C stack.  That function appends the
    # object to the constant table.  If the table doesn't have enough capacity
    # and needs to grow, it calls reallocate().  That in turn triggers a GC,
    # which fails to mark the new constant object and thus sweeps it right
    # before we have a chance to add it to the table.  Crash.
    #
    # In Python we don't have manual memory management, so the GC bug doesn't
    # apply, but we preserve the push/pop pattern for structural fidelity.
    from pyvm.vm import push, pop
    push(value)
    chunk.constants.write(value)
    pop()
    return chunk.constants.count - 1