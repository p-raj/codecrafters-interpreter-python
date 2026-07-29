"""
vm.h / vm.c — the bytecode virtual machine for pyvm.

The virtual machine is the core of the interpreter.  You hand it a function
(compiled from source) and it runs the bytecode.

In the C version, the VM is a global struct ``vm`` and the run loop uses macros
(READ_BYTE, READ_SHORT, READ_CONSTANT, READ_STRING, BINARY_OP) for speed.  Here
we use a VM class with a global ``vm`` instance and inline helper methods.
"""

from __future__ import annotations

import sys
import time
from typing import Optional

from enum import Enum, auto

from pyvm.common import (
    UINT8_COUNT, DEBUG_TRACE_EXECUTION, DEBUG_LOG_GC,
)
from pyvm.chunk import Chunk, OpCode
from pyvm.value import (
    Value, NIL_VAL, BOOL_VAL, NUMBER_VAL, OBJ_VAL,
    values_equal, print_value, IS_NIL, IS_BOOL, IS_NUMBER, IS_OBJ,
)
from pyvm.object import (
    Obj, ObjString, ObjFunction, ObjClosure, ObjClass, ObjInstance,
    ObjUpvalue, ObjBoundMethod, ObjType,
    as_class, as_closure, as_function, as_instance, as_string, as_c_string,
    as_bound_method, as_native, is_class, is_instance, is_string,
    is_obj_type, new_class, new_closure, new_instance, new_native, copy_string,
    new_upvalue, new_bound_method,
)
from pyvm.table import Table, table_get, table_set, table_delete, table_add_all


# --------------------------------------------------------------------------- #
# Limits
# --------------------------------------------------------------------------- #

FRAMES_MAX: int = 64
STACK_MAX: int = FRAMES_MAX * UINT8_COUNT


# --------------------------------------------------------------------------- #
# InterpretResult
# --------------------------------------------------------------------------- #

class InterpretResult(Enum):
    INTERPRET_OK = auto()
    INTERPRET_COMPILE_ERROR = auto()
    INTERPRET_RUNTIME_ERROR = auto()


# --------------------------------------------------------------------------- #
# CallFrame
# --------------------------------------------------------------------------- #

# Each call that hasn't returned yet—we need to track where on the stack that
# function's locals begin, and where the caller should resume.  A CallFrame
# represents a single ongoing function call.
class CallFrame:
    def __init__(self) -> None:
        self.closure: Optional[ObjClosure] = None
        # In C, ``ip`` is a uint8_t* pointing into the bytecode.  Here we use an
        # integer index into the closure's chunk.code list.
        self.ip: int = 0
        # In C, ``slots`` is a Value* pointing into the VM's value stack at the
        # first slot this function can use.  Here we store an integer index.
        self.slots: int = 0

# Instead of storing the return address in the callee's frame, the caller stores
# its own ip.  When we return from a function, the VM will jump to the ip of the
# caller's CallFrame and resume from there.


# --------------------------------------------------------------------------- #
# VM
# --------------------------------------------------------------------------- #

class VM:
    def __init__(self) -> None:
        # Introducing function-based stack & call stacks.  We don't have a chunk
        # executing, now it's callers and callees.
        self.frames: list[CallFrame] = [CallFrame() for _ in range(FRAMES_MAX)]
        self.frame_count: int = 0

        # In the C version, the stack is a fixed array of STACK_MAX Values.
        # We use a pre-allocated list so upvalue indices remain stable even
        # after stack_top moves down (mirroring C pointer semantics).
        self.stack: list[Optional[Value]] = [None] * STACK_MAX
        self.stack_top: int = 0

        # We need a hash table to store these globals.
        self.globals: Table = Table()
        # In order to reliably deduplicate all strings, the VM needs to be able
        # to find every string that's created.
        self.strings: Table = Table()
        # init() function — class initializer.
        self.init_string: Optional[ObjString] = None
        # To make sure all the defined closures close over VARIABLES and not
        # VALUES.  SHARE VARIABLES.
        self.open_upvalues: Optional[ObjUpvalue] = None

        # GC bookkeeping — work queue.
        self.gray_count: int = 0
        self.gray_stack: list[Obj] = []

        # GC optimization | latency and throughput tradeoff.
        self.bytes_allocated: int = 0
        self.next_gc: int = 0

        # Reference of all the objects that are heap allocated (intrusive linked
        # list head).
        self.objects: Optional[Obj] = None

        # Debug flag mirrors (from common.py).
        self.debug_trace_execution: bool = DEBUG_TRACE_EXECUTION
        self.debug_log_gc: bool = DEBUG_LOG_GC

    # ----------------------------------------------------------------- #
    # Stack operations  (mirrors push() / pop() / peek())
    # ----------------------------------------------------------------- #

    def push(self, value: Value) -> None:
        """void push(Value value)"""
        self.stack[self.stack_top] = value
        self.stack_top += 1

    def pop(self) -> Value:
        """Value pop()"""
        self.stack_top -= 1
        return self.stack[self.stack_top]  # type: ignore[return-value]

    def peek(self, distance: int) -> Value:
        """static Value peek(int distance)"""
        return self.stack[self.stack_top - 1 - distance]  # type: ignore[return-value]


# The global VM instance (mirrors ``VM vm;`` / ``extern VM vm;`` in C).
vm: VM = VM()


# --------------------------------------------------------------------------- #
# Module-level push/pop wrappers (used by chunk.add_constant)
# --------------------------------------------------------------------------- #

def push(value: Value) -> None:
    vm.push(value)


def pop() -> Value:
    return vm.pop()


# --------------------------------------------------------------------------- #
# Native functions
# --------------------------------------------------------------------------- #

def clock_native(arg_count: int, args: list[Value]) -> Value:
    """static Value clockNative(int argCount, Value* args)"""
    return NUMBER_VAL(time.process_time())


# --------------------------------------------------------------------------- #
# initVM / freeVM
# --------------------------------------------------------------------------- #

def _reset_stack() -> None:
    """static void resetStack()"""
    vm.stack_top = 0
    vm.frame_count = 0
    vm.open_upvalues = None


def _runtime_error(message: str) -> None:
    """static void runtimeError(const char* format, ...)"""
    import sys
    print(message, file=sys.stderr)

    # Stack trace: walk frames from innermost to outermost.
    for i in range(vm.frame_count - 1, -1, -1):
        frame = vm.frames[i]
        function = frame.closure.function
        # The -1 is because the IP is already sitting on the next instruction to
        # be executed but we want the stack trace to point to the previous
        # failed instruction.
        instruction = frame.ip - 1
        line = function.chunk.lines[instruction]
        print(f"[line {line}] in ", end="", file=sys.stderr)
        if function.name is None:
            print("script", file=sys.stderr)
        else:
            print(f"{function.name.chars}()", file=sys.stderr)
    _reset_stack()


# Without something like a foreign function interface, users can't define their
# own native functions.  That's our job as VM implementers.  We'll start with a
# helper to define a new native function exposed to Lox programs.
def _define_native(name: str, function) -> None:
    """static void defineNative(const char* name, NativeFn function)"""
    vm.push(OBJ_VAL(copy_string(name)))
    vm.push(OBJ_VAL(new_native(function)))
    table_set(vm.globals, as_string(vm.stack[vm.stack_top - 2]), vm.stack[vm.stack_top - 1])
    # Why we push and pop the name and function on the stack.  This is the kind
    # of stuff you have to worry about when garbage collection gets involved.
    # Both copyString() and newNative() dynamically allocate memory.  That means
    # once we have a GC, they can potentially trigger a collection.  If that
    # happens, we need to ensure the collector knows we're not done with the
    # name and ObjFunction so that it doesn't free them out from under us.
    # Storing them on the value stack accomplishes that.
    vm.pop()
    vm.pop()


def init_vm() -> None:
    """void initVM()"""
    _reset_stack()
    vm.objects = None

    vm.bytes_allocated = 0
    vm.next_gc = 1024 * 1024

    vm.gray_count = 0
    vm.gray_stack = []

    vm.globals = Table()
    vm.strings = Table()
    # Look carefully.  See any bug waiting to happen?  No?  It's a subtle one.
    # The garbage collector now reads vm.initString.  That field is initialized
    # from the result of calling copyString().  But copying a string allocates
    # memory, which can trigger a GC.  If the collector ran at just the wrong
    # time, it would read vm.initString before it had been initialized.  So,
    # first we zero the field out.
    vm.init_string = None
    # init: initialize class instance.
    vm.init_string = copy_string("init", 4)
    _define_native("clock", clock_native)


def free_vm() -> None:
    """void freeVM()"""
    from pyvm.memory import free_objects
    from pyvm.table import free_table
    free_table(vm.globals)
    free_table(vm.strings)
    vm.init_string = None
    free_objects()


# --------------------------------------------------------------------------- #
# Calling helpers
# --------------------------------------------------------------------------- #

def _call(closure: ObjClosure, arg_count: int) -> bool:
    """static bool call(ObjClosure* closure, int argCount)"""
    if arg_count != closure.function.arity:
        _runtime_error(f"Expected {closure.function.arity} arguments but got {arg_count}.")
        return False
    if vm.frame_count == FRAMES_MAX:
        _runtime_error("Stack overflow.")
        return False
    frame = vm.frames[vm.frame_count]
    vm.frame_count += 1
    frame.closure = closure
    frame.ip = 0
    frame.slots = vm.stack_top - arg_count - 1
    return True


def _call_value(callee: Value, arg_count: int) -> bool:
    """static bool callValue(Value callee, int argCount)"""
    if callee.is_obj:
        obj = callee.as_obj()
        if obj.type is ObjType.OBJ_BOUND_METHOD:
            bound = as_bound_method(callee)
            vm.stack[vm.stack_top - arg_count - 1] = bound.receiver
            return _call(bound.method, arg_count)
        elif obj.type is ObjType.OBJ_CLASS:
            # When you call a class like var b = Brioche(1, 2);:
            # The stack initially holds: [ ... | Brioche (class) | arg1 | arg2 ].
            # newInstance(klass) creates the new Brioche instance object.
            # This assignment overwrites Brioche (class) on the stack with the
            # new instance: [ ... | Brioche instance | arg1 | arg2 ].  This
            # effectively replaces the class object with the newly created
            # instance while keeping the arguments in place for any
            # constructor/initializer method that runs afterward.
            klass = as_class(callee)
            vm.stack[vm.stack_top - arg_count - 1] = OBJ_VAL(new_instance(klass))
            # Invoking initializers.
            found, initializer = table_get(klass.methods, vm.init_string)
            if found:
                return _call(as_closure(initializer), arg_count)
            elif arg_count != 0:
                _runtime_error(f"Expected 0 arguments but got {arg_count}.")
                return False
            return True
        elif obj.type is ObjType.OBJ_CLOSURE:
            # [NOTE] Since we wrap all functions in ObjClosures, the runtime
            # will never try to invoke a bare ObjFunction anymore.  Those
            # objects live only in constant tables and get immediately wrapped
            # in closures before anything else sees them.
            return _call(as_closure(callee), arg_count)
        elif obj.type is ObjType.OBJ_NATIVE:
            native = as_native(callee)
            result = native(arg_count, [vm.stack[vm.stack_top - arg_count + i] for i in range(arg_count)])  # type: ignore[list-item]
            vm.stack_top -= arg_count + 1
            vm.push(result)
            return True
        # else: Non-callable object type.  Fall through.
    _runtime_error("Can only call functions and classes.")
    return False


def _invoke_from_class(klass: ObjClass, name: ObjString, arg_count: int) -> bool:
    """static bool invokeFromClass(ObjClass* klass, ObjString* name, int argCount)"""
    found, method = table_get(klass.methods, name)
    if not found:
        _runtime_error(f"Undefined property '{name.chars}'.")
        return False
    return _call(as_closure(method), arg_count)


def _invoke(name: ObjString, arg_count: int) -> bool:
    """static bool invoke(ObjString* name, int argCount)"""
    receiver = vm.peek(arg_count)
    if not is_instance(receiver):
        _runtime_error("Only instances have methods.")
        return False
    instance = as_instance(receiver)

    # Pretty simple fix.  Before looking up a method on the instance's class, we
    # look for a field with the same name.  If we find a field, then we store it
    # on the stack in place of the receiver, under the argument list.  This is
    # how OP_GET_PROPERTY behaves since the latter instruction executes before a
    # subsequent parenthesized list of arguments has been evaluated.
    found, value = table_get(instance.fields, name)
    if found:
        vm.stack[vm.stack_top - arg_count - 1] = value
        return _call_value(value, arg_count)
    return _invoke_from_class(instance.klass, name, arg_count)


def _bind_method(klass: ObjClass, name: ObjString) -> bool:
    """static bool bindMethod(ObjClass* klass, ObjString* name)"""
    found, method = table_get(klass.methods, name)
    if not found:
        _runtime_error(f"Undefined property '{name.chars}'.")
        return False
    bound = new_bound_method(vm.peek(0), as_closure(method))
    vm.pop()
    vm.push(OBJ_VAL(bound))
    return True


def _capture_upvalue(local_index: int) -> ObjUpvalue:
    """static ObjUpvalue* captureUpvalue(Value* local)"""
    global vm
    prev_upvalue: Optional[ObjUpvalue] = None
    upvalue = vm.open_upvalues
    # Trace the linked list.
    # Even better, we can order the list of open upvalues by the stack slot
    # index they point to.  The common case is that a slot has not already been
    # captured—sharing variables between closures is uncommon—and closures tend
    # to capture locals near the top of the stack.  If we store the open upvalue
    # array in stack slot order, as soon as we step past the slot where the
    # local we're capturing lives, we know it won't be found.  When that local
    # is near the top of the stack, we can exit the loop pretty early.
    while upvalue is not None and upvalue._stack_index is not None and upvalue._stack_index > local_index:
        prev_upvalue = upvalue
        upvalue = upvalue.next
    if upvalue is not None and upvalue._stack_index == local_index:
        return upvalue
    created_upvalue = new_upvalue(local_index)
    created_upvalue.next = upvalue

    if prev_upvalue is None:
        vm.open_upvalues = created_upvalue
    else:
        prev_upvalue.next = created_upvalue
    return created_upvalue


def _close_upvalues(last_index: int) -> None:
    """static void closeUpvalues(Value* last)"""
    global vm
    while (
        vm.open_upvalues is not None
        and vm.open_upvalues._stack_index is not None
        and vm.open_upvalues._stack_index >= last_index
    ):
        upvalue = vm.open_upvalues
        upvalue.close()
        vm.open_upvalues = upvalue.next


def _define_method(name: ObjString) -> None:
    """static void defineMethod(ObjString* name)"""
    method = vm.peek(0)
    klass = as_class(vm.peek(1))
    table_set(klass.methods, name, method)
    vm.pop()


def _is_falsy(value: Value) -> bool:
    """static bool isFalsy(Value value)"""
    return value.is_nil or (value.is_bool and not value.as_bool())


def _concatenate() -> None:
    """static void concatenate()"""
    # If we pop these, now with GC these could very well be swept.
    b = as_string(vm.peek(0))
    a = as_string(vm.peek(1))

    chars = a.chars + b.chars
    length = len(chars)

    result = _take_string(chars, length)
    vm.pop()
    vm.pop()
    vm.push(OBJ_VAL(result))


def _take_string(chars: str, length: int) -> ObjString:
    """Local wrapper for take_string (avoids late import in hot path)."""
    from pyvm.object import take_string
    return take_string(chars, length)


# --------------------------------------------------------------------------- #
# run() — the bytecode dispatch loop
# --------------------------------------------------------------------------- #

def _run() -> InterpretResult:
    """static InterpretResult run()"""
    frame = vm.frames[vm.frame_count - 1]

    def read_byte() -> int:
        # #define READ_BYTE() (*frame->ip++)
        nonlocal frame
        b = frame.closure.function.chunk.code[frame.ip]
        frame.ip += 1
        return b

    def read_short() -> int:
        # #define READ_SHORT() (frame->ip += 2, (uint16_t)((frame->ip[-2] << 8) | frame->ip[-1]))
        nonlocal frame
        frame.ip += 2
        return (frame.closure.function.chunk.code[frame.ip - 2] << 8) | frame.closure.function.chunk.code[frame.ip - 1]

    def read_constant() -> Value:
        # #define READ_CONSTANT() (frame->closure->function->chunk.constants.values[READ_BYTE()])
        return frame.closure.function.chunk.constants.values[read_byte()]

    def read_string() -> ObjString:
        # #define READ_STRING() AS_STRING(READ_CONSTANT())
        return as_string(read_constant())

    while True:
        if vm.debug_trace_execution:
            print("\t\t", end="")
            for slot in range(vm.stack_top):
                print("[ ", end="")
                if vm.stack[slot] is not None:
                    print_value(vm.stack[slot])  # type: ignore[arg-type]
                print(" ]", end="")
            print()
            from pyvm.debug import disassemble_instruction
            disassemble_instruction(
                frame.closure.function.chunk,
                frame.ip,
            )

        # Given a numeric opcode, we need to get to the right code that
        # implements that instruction's semantics.  This process is called
        # decoding or dispatching the instruction.
        instruction = read_byte()
        try:
            op = OpCode(instruction)
        except ValueError:
            _runtime_error(f"Unknown opcode {instruction}")
            return InterpretResult.INTERPRET_RUNTIME_ERROR

        if op is OpCode.OP_CONSTANT:
            constant = read_constant()
            vm.push(constant)

        elif op is OpCode.OP_NIL:
            vm.push(NIL_VAL())

        elif op is OpCode.OP_TRUE:
            vm.push(BOOL_VAL(True))

        elif op is OpCode.OP_FALSE:
            vm.push(BOOL_VAL(False))

        elif op is OpCode.OP_POP:
            vm.pop()

        elif op is OpCode.OP_GET_LOCAL:
            # It takes a single-byte operand for the stack slot where the local
            # lives.  It loads the value from that index and then pushes it on
            # top of the stack where later instructions can find it.
            slot = read_byte()
            # OP_GET_LOCAL reads the given local slot relative to the current
            # frame's slots array.
            vm.push(vm.stack[frame.slots + slot])  # type: ignore[arg-type]

        elif op is OpCode.OP_GET_GLOBAL:
            name = read_string()
            # We pull the constant table index from the instruction's operand
            # and get the variable name.  Then we use that as a key to look up
            # the variable's value in the globals hash table.
            found, value = table_get(vm.globals, name)
            if not found:
                _runtime_error(f"Undefined variable '{name.chars}'.")
                return InterpretResult.INTERPRET_RUNTIME_ERROR
            vm.push(value)

        elif op is OpCode.OP_DEFINE_GLOBAL:
            # We get the name of the variable from the constant table.  Then we
            # take the value from the top of the stack and store it in a hash
            # table with that name as the key.
            name = read_string()
            table_set(vm.globals, name, vm.peek(0))
            vm.pop()

        elif op is OpCode.OP_SET_LOCAL:
            slot = read_byte()
            # Remember, assignment is an expression, and every expression
            # produces a value.  The value of an assignment expression is the
            # assigned value itself, so the VM just leaves the value on the
            # stack.
            vm.stack[frame.slots + slot] = vm.peek(0)

        elif op is OpCode.OP_SET_GLOBAL:
            name = read_string()
            if table_set(vm.globals, name, vm.peek(0)):
                # If set and is a new key, we will mark that as an error.  If the
                # variable hasn't been defined yet, it's a runtime error to try
                # to assign to it.  Lox doesn't do implicit variable declaration.
                table_delete(vm.globals, name)
                _runtime_error(f"Undefined variable '{name.chars}'.")
                return InterpretResult.INTERPRET_RUNTIME_ERROR
            # The other difference is that setting a variable doesn't pop the
            # value off the stack.  Remember, assignment is an expression, so it
            # needs to leave that value there in case the assignment is nested
            # inside some larger expression.

        elif op is OpCode.OP_GET_UPVALUE:
            slot = read_byte()
            vm.push(frame.closure.upvalues[slot].get_location_value())  # type: ignore[union-attr]

        elif op is OpCode.OP_SET_UPVALUE:
            slot = read_byte()
            frame.closure.upvalues[slot].set_location_value(vm.peek(0))  # type: ignore[union-attr]

        elif op is OpCode.OP_GET_PROPERTY:
            if not is_instance(vm.peek(0)):
                _runtime_error("Only instances have properties.")
                return InterpretResult.INTERPRET_RUNTIME_ERROR

            instance = as_instance(vm.peek(0))
            name = read_string()

            # We insert this after the code to look up a field on the receiver
            # instance.  Fields take priority over and shadow methods, so we look
            # for a field first.  If the instance does not have a field with the
            # given property name, then the name may refer to a method.
            found, value = table_get(instance.fields, name)
            if found:
                vm.pop()  # Instance.
                vm.push(value)
            else:
                if not _bind_method(instance.klass, name):
                    return InterpretResult.INTERPRET_RUNTIME_ERROR

        elif op is OpCode.OP_SET_PROPERTY:
            if not is_instance(vm.peek(1)):
                _runtime_error("Only instances have fields.")
                return InterpretResult.INTERPRET_RUNTIME_ERROR
            instance = as_instance(vm.peek(1))
            table_set(instance.fields, read_string(), vm.peek(0))
            value = vm.pop()
            vm.pop()
            vm.push(value)

        elif op is OpCode.OP_GET_SUPER:
            name = read_string()
            superclass = as_class(vm.pop())
            if not _bind_method(superclass, name):
                return InterpretResult.INTERPRET_RUNTIME_ERROR

        elif op is OpCode.OP_EQUAL:
            b = vm.pop()
            a = vm.pop()
            vm.push(BOOL_VAL(values_equal(a, b)))

        elif op is OpCode.OP_GREATER:
            if not _binary_op(lambda a, b: a > b, is_comparison=True):
                return InterpretResult.INTERPRET_RUNTIME_ERROR

        elif op is OpCode.OP_LESS:
            if not _binary_op(lambda a, b: a < b, is_comparison=True):
                return InterpretResult.INTERPRET_RUNTIME_ERROR

        elif op is OpCode.OP_ADD:
            if is_string(vm.peek(0)) and is_string(vm.peek(1)):
                _concatenate()
            elif IS_NUMBER(vm.peek(0)) and IS_NUMBER(vm.peek(1)):
                b = vm.pop().as_number()
                a = vm.pop().as_number()
                vm.push(NUMBER_VAL(a + b))
            else:
                _runtime_error("Operands must be two numbers or two strings.")
                return InterpretResult.INTERPRET_RUNTIME_ERROR

        elif op is OpCode.OP_SUBTRACT:
            if not _binary_op(lambda a, b: a - b):
                return InterpretResult.INTERPRET_RUNTIME_ERROR

        elif op is OpCode.OP_MULTIPLY:
            if not _binary_op(lambda a, b: a * b):
                return InterpretResult.INTERPRET_RUNTIME_ERROR

        elif op is OpCode.OP_DIVIDE:
            if not _binary_op(lambda a, b: a / b):
                return InterpretResult.INTERPRET_RUNTIME_ERROR

        elif op is OpCode.OP_NOT:
            vm.push(BOOL_VAL(_is_falsy(vm.pop())))

        elif op is OpCode.OP_NEGATE:
            if not IS_NUMBER(vm.peek(0)):
                _runtime_error("Operand must be a number.")
                return InterpretResult.INTERPRET_RUNTIME_ERROR
            vm.push(NUMBER_VAL(-vm.pop().as_number()))

        elif op is OpCode.OP_PRINT:
            # Note that we don't push anything else after that.  This is a key
            # difference between expressions and statements in the VM.  Every
            # bytecode instruction has a stack effect that describes how the
            # instruction modifies the stack.  The bytecode for an entire
            # statement has a total stack effect of zero.  [NOTE], each statement
            # is required to have zero stack effect—after the statement is
            # finished executing, the stack should be as tall as it was before.
            print_value(vm.pop())
            print()

        elif op is OpCode.OP_JUMP:
            offset = read_short()
            frame.ip += offset

        elif op is OpCode.OP_JUMP_IF_FALSE:
            offset = read_short()
            # We have to do some more work here to ensure that stack gets cleaned
            # up if we are jumping to a different offset.  The stack that was
            # supposed to get used if the code would have chosen the <if branch>
            # is still there.
            if _is_falsy(vm.peek(0)):
                frame.ip += offset

        elif op is OpCode.OP_LOOP:
            offset = read_short()
            frame.ip -= offset

        elif op is OpCode.OP_CALL:
            arg_count = read_byte()
            # argCount also tells us where to find the function on the stack by
            # counting past the argument slots from the top of the stack.
            if not _call_value(vm.peek(arg_count), arg_count):
                return InterpretResult.INTERPRET_RUNTIME_ERROR
            # If callValue() is successful, there will be a new frame on the
            # CallFrame stack for the called function.  The run() function has
            # its own cached pointer to the current frame, so we need to update
            # that.
            frame = vm.frames[vm.frame_count - 1]

        elif op is OpCode.OP_INVOKE:
            method = read_string()
            arg_count = read_byte()
            if not _invoke(method, arg_count):
                return InterpretResult.INTERPRET_RUNTIME_ERROR
            # There is a new CallFrame on the stack, so we refresh our cached
            # copy of the current frame in frame.
            frame = vm.frames[vm.frame_count - 1]

        elif op is OpCode.OP_SUPER_INVOKE:
            method = read_string()
            arg_count = read_byte()
            superclass = as_class(vm.pop())
            if not _invoke_from_class(superclass, method, arg_count):
                return InterpretResult.INTERPRET_RUNTIME_ERROR
            # We pass the superclass, method name, and argument count to our
            # existing invokeFromClass() function.  That function looks up the
            # given method on the given class and attempts to create a call to
            # it with the given arity.  If a method could not be found, it
            # returns false, and we bail out of the interpreter.  Otherwise,
            # invokeFromClass() pushes a new CallFrame onto the call stack for
            # the method's closure.  That invalidates the interpreter's cached
            # CallFrame pointer, so we refresh frame.
            frame = vm.frames[vm.frame_count - 1]

        elif op is OpCode.OP_CLOSURE:
            fun = as_function(read_constant())
            closure = new_closure(fun)
            # Closures capture [variables].  You can think of them as capturing
            # the place the value lives.  This is important to keep in mind as we
            # deal with closed-over variables that are no longer on the stack.
            # When a variable moves to the heap, we need to ensure that all
            # closures capturing that variable retain a reference to its one new
            # location.  That way, when the variable is mutated, all closures see
            # the change.  We know that local variables always start out on the
            # stack.  This is faster, and lets our single-pass compiler emit code
            # before it discovers the variable has been captured.  We also know
            # that closed-over variables need to move to the heap if the closure
            # outlives the function where the captured variable is declared.
            vm.push(OBJ_VAL(closure))
            for i in range(closure.upvalue_count):
                is_local = read_byte()
                index = read_byte()
                if is_local:
                    closure.upvalues[i] = _capture_upvalue(frame.slots + index)
                else:
                    # MEGA COOL
                    # Otherwise, we capture an upvalue from the surrounding
                    # function.  An OP_CLOSURE instruction is emitted at the end
                    # of a function declaration.  At the moment that we are
                    # executing that declaration, the current function is the
                    # surrounding one.  That means the current function's closure
                    # is stored in the CallFrame at the top of the callstack.
                    # So, to grab an upvalue from the enclosing function, we can
                    # read it right from the frame local variable, which caches
                    # a reference to that CallFrame.
                    closure.upvalues[i] = frame.closure.upvalues[index]

        elif op is OpCode.OP_CLOSE_UPVALUE:
            _close_upvalues(vm.stack_top - 1)
            vm.pop()

        elif op is OpCode.OP_RETURN:
            # When a function returns a value, that value will be on top of the
            # stack.  We're about to discard the called function's entire stack
            # window, so we pop that return value off and hang on to it.
            result = vm.pop()
            # By passing the first slot in the function's stack window, we close
            # every remaining open upvalue owned by the returning function.  And
            # with that, we now have a fully functioning closure implementation.
            # Closed-over variables live as long as they are needed by the
            # functions that capture them.
            _close_upvalues(frame.slots)
            # Then we discard the CallFrame for the returning function.
            vm.frame_count -= 1

            # If that was the very last CallFrame, it means we've finished
            # executing the top-level code.  The entire program is done, so we
            # pop the main script function from the stack and then exit the
            # interpreter.
            if vm.frame_count == 0:
                vm.pop()
                return InterpretResult.INTERPRET_OK

            vm.stack_top = frame.slots
            vm.push(result)
            frame = vm.frames[vm.frame_count - 1]

        elif op is OpCode.OP_CLASS:
            vm.push(OBJ_VAL(new_class(read_string())))

        elif op is OpCode.OP_INHERIT:
            superclass = vm.peek(1)
            if not is_class(superclass):
                _runtime_error("Superclass must be a class.")
                return InterpretResult.INTERPRET_RUNTIME_ERROR
            subclass = as_class(vm.peek(0))
            # The new approach is much faster.  When the subclass is declared, we
            # copy all of the inherited class's methods down into the subclass's
            # own method table.  Later, when calling a method, any method
            # inherited from a superclass will be found right in the subclass's
            # own method table.  There is no extra runtime work needed for
            # inheritance at all.  By the time the class is declared, the work is
            # done.  This means inherited method calls are exactly as fast as
            # normal method calls—a single hash table lookup.
            #
            # What about method overrides?  Won't copying the superclass's
            # methods into the subclass's method table clash with the subclass's
            # own methods?  Fortunately, no.  We emit the OP_INHERIT after the
            # OP_CLASS instruction that creates the subclass but before any
            # method declarations and OP_METHOD instructions have been compiled.
            # At the point that we copy the superclass's methods down, the
            # subclass's method table is empty.  Any methods the subclass
            # overrides will overwrite those inherited entries in the table.
            table_add_all(as_class(superclass).methods, subclass.methods)
            vm.pop()  # Subclass.

        elif op is OpCode.OP_METHOD:
            _define_method(read_string())


def _binary_op(operation, is_comparison: bool = False) -> bool:
    """
    #define BINARY_OP(valueType, op)
    Returns True on success, False on runtime error.
    ``operation`` is a callable (a, b) -> result.
    ``is_comparison``: if True, wrap the result in BOOL_VAL (for < > etc.).
    If False, wrap in NUMBER_VAL (for arithmetic like + - * /).
    """
    if not IS_NUMBER(vm.peek(0)) or not IS_NUMBER(vm.peek(1)):
        _runtime_error("Operands must be numbers.")
        return False
    b = vm.pop().as_number()
    a = vm.pop().as_number()
    result = operation(a, b)
    if is_comparison:
        vm.push(BOOL_VAL(bool(result)))
    else:
        vm.push(NUMBER_VAL(result))
    return True


# --------------------------------------------------------------------------- #
# interpret() — public entry point
# --------------------------------------------------------------------------- #

def interpret(source: str) -> InterpretResult:
    """InterpretResult interpret(const char* source)"""
    from pyvm.compiler import compile as _compile
    # The compiler returns a new ObjFunction containing the compiled top-level
    # code.
    function = _compile(source)
    if function is None:
        return InterpretResult.INTERPRET_COMPILE_ERROR
    closure = new_closure(function)
    # We store the function on the stack and prepare an initial CallFrame to
    # execute its code.
    vm.push(OBJ_VAL(closure))
    _call(closure, 0)
    return _run()