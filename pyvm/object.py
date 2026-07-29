"""
object.h / object.c — heap-allocated Obj types for pyvm.

In the C version, every heap-allocated Lox object (string, function, closure,
class, instance, etc.) begins with an ``Obj`` header struct containing a type
tag, a GC mark bit, and a ``next`` pointer for the GC's object linked list.
This is achieved through struct embedding.

In Python we use inheritance: ``Obj`` is the base class and each specific type
extends it.  Because Python has its own garbage collector, the manual memory
management (``reallocate``, ``free``) is handled by Python, but we preserve the
GC infrastructure (mark bits, linked list) for structural fidelity.
"""

from __future__ import annotations

import sys
from enum import Enum, auto
from typing import Callable, Optional, TYPE_CHECKING

from pyvm.chunk import Chunk, init_chunk
from pyvm.value import Value
from pyvm.table import Table

if TYPE_CHECKING:
    pass

# A native function takes (argCount, args) and returns a Value.
NativeFn = Callable[[int, list[Value]], Value]


# --------------------------------------------------------------------------- #
# ObjType
# --------------------------------------------------------------------------- #

class ObjType(Enum):
    OBJ_BOUND_METHOD = auto()
    OBJ_CLASS = auto()
    OBJ_CLOSURE = auto()
    OBJ_FUNCTION = auto()
    OBJ_INSTANCE = auto()
    OBJ_NATIVE = auto()
    OBJ_STRING = auto()
    OBJ_UPVALUE = auto()


# --------------------------------------------------------------------------- #
# Obj  (base class — mirrors the C struct Obj header)
# --------------------------------------------------------------------------- #

# C specifies that struct fields are arranged in memory in the order that they
# are declared.  Also, when you nest structs, the inner struct's fields are
# expanded right in place.  In Python we use inheritance instead.
class Obj:
    """Base class for all heap-allocated Lox objects."""

    def __init__(self, obj_type: ObjType) -> None:
        self.type: ObjType = obj_type
        # GC — mark phase.
        self.is_marked: bool = False
        # Intrusive linked list of all objects, used by the GC.
        self.next: Optional[Obj] = None

    @property
    def is_marked_prop(self) -> bool:
        return self.is_marked


# --------------------------------------------------------------------------- #
# ObjNative
# --------------------------------------------------------------------------- #

class ObjNative(Obj):
    """Obj header and a pointer to the function that implements the native."""

    def __init__(self, function: NativeFn) -> None:
        super().__init__(ObjType.OBJ_NATIVE)
        self.function: NativeFn = function


# --------------------------------------------------------------------------- #
# ObjString
# --------------------------------------------------------------------------- #

class ObjString(Obj):
    def __init__(self, chars: str, length: int, hash_val: int) -> None:
        super().__init__(ObjType.OBJ_STRING)
        self.length: int = length
        self.chars: str = chars
        self.hash: int = hash_val


# --------------------------------------------------------------------------- #
# ObjUpvalue
# --------------------------------------------------------------------------- #

# Each OP_CLOSURE instruction is now followed by the series of bytes that
# specify the upvalues the ObjClosure should own.  We know upvalues must manage
# closed-over variables that no longer live on the stack, which implies some
# amount of dynamic allocation.
class ObjUpvalue(Obj):
    """
    In C, ``location`` is a ``Value*`` — a pointer to a variable on the VM
    stack, not a value itself.  This is important because it means that when we
    assign to the variable the upvalue captures, we're assigning to the actual
    variable, not a copy.

    In Python we don't have pointers.  We store ``_stack_index``: an index into
    the VM's stack array (when the upvalue is open).  When the upvalue is closed
    (the variable leaves scope), the value is copied into ``closed`` and
    ``_stack_index`` is set to None.
    """

    def __init__(self, stack_index: int) -> None:
        super().__init__(ObjType.OBJ_UPVALUE)
        # Pointer to the current value location (simulated via stack index).
        self._stack_index: Optional[int] = stack_index
        # The closed-over value (used after the upvalue is closed).
        self.closed: Value = Value.nil_val()
        # Intrusive linked list of open upvalues, ordered by stack slot.
        self.next: Optional[ObjUpvalue] = None  # type: ignore[assignment]

    def get_location_value(self) -> Value:
        """Read the value the upvalue currently points to (mirrors *location)."""
        if self._stack_index is not None:
            from pyvm.vm import vm
            return vm.stack[self._stack_index]
        return self.closed

    def set_location_value(self, value: Value) -> None:
        """Write to the variable the upvalue captures (mirrors *location = v)."""
        if self._stack_index is not None:
            from pyvm.vm import vm
            vm.stack[self._stack_index] = value
        else:
            self.closed = value

    def close(self) -> None:
        """Hoist the captured value from the stack to the heap."""
        if self._stack_index is not None:
            from pyvm.vm import vm
            self.closed = vm.stack[self._stack_index]
            self._stack_index = None


# --------------------------------------------------------------------------- #
# ObjFunction
# --------------------------------------------------------------------------- #

class ObjFunction(Obj):
    """For the functions."""

    def __init__(self) -> None:
        super().__init__(ObjType.OBJ_FUNCTION)
        self.arity: int = 0
        self.chunk: Chunk = Chunk()
        init_chunk(self.chunk)
        self.upvalue_count: int = 0
        self.name: Optional[ObjString] = None


# --------------------------------------------------------------------------- #
# ObjClosure
# --------------------------------------------------------------------------- #

# Wrap the <fn>.
class ObjClosure(Obj):
    """
    Different closures may have different numbers of upvalues, so we need a
    dynamic array.  The upvalues themselves are dynamically allocated too, so
    we end up with a double pointer — a pointer to a dynamically allocated
    array of pointers to upvalues.

    Storing the upvalue count in the closure is redundant because the
    ObjFunction that the ObjClosure references also keeps that count.  As usual,
    this weird code is to appease the GC.  The collector may need to know an
    ObjClosure's upvalue array size after the closure's corresponding
    ObjFunction has already been freed.
    """

    def __init__(self, function: ObjFunction) -> None:
        super().__init__(ObjType.OBJ_CLOSURE)
        self.function: ObjFunction = function
        self.upvalues: list[Optional[ObjUpvalue]] = [None] * function.upvalue_count
        self.upvalue_count: int = function.upvalue_count


# --------------------------------------------------------------------------- #
# ObjClass
# --------------------------------------------------------------------------- #

class ObjClass(Obj):
    def __init__(self, name: ObjString) -> None:
        super().__init__(ObjType.OBJ_CLASS)
        self.name: ObjString = name
        self.methods: Table = Table()


# --------------------------------------------------------------------------- #
# ObjInstance
# --------------------------------------------------------------------------- #

class ObjInstance(Obj):
    def __init__(self, klass: "ObjClass") -> None:
        super().__init__(ObjType.OBJ_INSTANCE)
        self.klass: ObjClass = klass
        self.fields: Table = Table()


# --------------------------------------------------------------------------- #
# ObjBoundMethod
# --------------------------------------------------------------------------- #

# When the user executes a method access, we'll find the closure for that method
# and wrap it in a new "bound method" object that tracks the instance that the
# method was accessed from.  This bound object can be called later like a
# function.  When invoked, the VM will do some shenanigans to wire up ``this``
# to point to the receiver inside the method's body.
#
# It wraps the receiver and the method closure together.  The receiver's type is
# Value even though methods can be called only on ObjInstances.  Since the VM
# doesn't care what kind of receiver it has anyway, using Value means we don't
# have to keep converting the pointer back to a Value when it gets passed to
# more general functions.
class ObjBoundMethod(Obj):
    def __init__(self, receiver: Value, method: ObjClosure) -> None:
        super().__init__(ObjType.OBJ_BOUND_METHOD)
        self.receiver: Value = receiver
        self.method: ObjClosure = method


# --------------------------------------------------------------------------- #
# Helper predicates (mirror the IS_* macros)
# --------------------------------------------------------------------------- #

# Pop quiz: Why not just put the body of this function right in the macro?
# What's different about this one compared to the others?  Right, it's because
# the body uses value twice.  A macro is expanded by inserting the argument
# expression every place the parameter name appears in the body.  If a macro
# uses a parameter more than once, that expression gets evaluated multiple
# times.  IS_STRING(POP()) -> would be POP() and then POP() again.

def obj_type(value: Value) -> ObjType:
    """#define OBJ_TYPE(value) (AS_OBJ(value)->type)"""
    return value.as_obj().type


def is_bound_method(value: Value) -> bool:
    """#define IS_BOUND_METHOD(value) isObjType(value, OBJ_BOUND_METHOD)"""
    return value.is_obj and value.as_obj().type is ObjType.OBJ_BOUND_METHOD


def is_class(value: Value) -> bool:
    """#define IS_CLASS(value) isObjType(value, OBJ_CLASS)"""
    return value.is_obj and value.as_obj().type is ObjType.OBJ_CLASS


def is_closure(value: Value) -> bool:
    """#define IS_CLOSURE(value) isObjType(value, OBJ_CLOSURE)"""
    return value.is_obj and value.as_obj().type is ObjType.OBJ_CLOSURE


def is_function(value: Value) -> bool:
    """#define IS_FUNCTION(value) isObjType(value, OBJ_FUNCTION)"""
    return value.is_obj and value.as_obj().type is ObjType.OBJ_FUNCTION


def is_instance(value: Value) -> bool:
    """#define IS_INSTANCE(value) isObjType(value, OBJ_INSTANCE)"""
    return value.is_obj and value.as_obj().type is ObjType.OBJ_INSTANCE


def is_native(value: Value) -> bool:
    """#define IS_NATIVE(value) isObjType(value, OBJ_NATIVE)"""
    return value.is_obj and value.as_obj().type is ObjType.OBJ_NATIVE


def is_string(value: Value) -> bool:
    """#define IS_STRING(value) isObjType(value, OBJ_STRING)"""
    return value.is_obj and value.as_obj().type is ObjType.OBJ_STRING


def is_obj_type(value: Value, t: ObjType) -> bool:
    """static inline bool isObjType(Value value, ObjType type)"""
    return value.is_obj and value.as_obj().type is t


# --------------------------------------------------------------------------- #
# Casting helpers (mirror the AS_* macros)
# --------------------------------------------------------------------------- #

def as_bound_method(value: Value) -> ObjBoundMethod:
    return value.as_obj()  # type: ignore[return-value]


def as_class(value: Value) -> ObjClass:
    return value.as_obj()  # type: ignore[return-value]


def as_closure(value: Value) -> ObjClosure:
    return value.as_obj()  # type: ignore[return-value]


def as_function(value: Value) -> ObjFunction:
    return value.as_obj()  # type: ignore[return-value]


def as_instance(value: Value) -> ObjInstance:
    return value.as_obj()  # type: ignore[return-value]


def as_native(value: Value) -> NativeFn:
    """#define AS_NATIVE(value) (((ObjNative*)AS_OBJ(value))->function)"""
    return value.as_obj().function  # type: ignore[union-attr]


def as_string(value: Value) -> ObjString:
    return value.as_obj()  # type: ignore[return-value]


def as_c_string(value: Value) -> str:
    """#define AS_CSTRING(value) (((ObjString*)AS_OBJ(value))->chars)"""
    return value.as_obj().chars  # type: ignore[union-attr]


# --------------------------------------------------------------------------- #
# Allocation functions (mirror object.c)
# --------------------------------------------------------------------------- #

def _allocate_object(obj: Obj) -> Obj:
    """static Obj* allocateObject(size_t size, ObjType type)

    Registers the new object in the VM's object linked list and runs GC if
    needed.
    """
    from pyvm.vm import vm
    from pyvm.memory import maybe_collect
    obj.is_marked = False
    # Populate VM (extern object from vm.h).
    obj.next = vm.objects
    vm.objects = obj
    maybe_collect()
    if vm.debug_log_gc:
        print(f"{id(obj):#x} allocate for {obj.type.name}")
    return obj


def new_bound_method(receiver: Value, method: ObjClosure) -> ObjBoundMethod:
    """ObjBoundMethod* newBoundMethod(Value receiver, ObjClosure* method)"""
    bound = ObjBoundMethod(receiver, method)
    _allocate_object(bound)
    return bound


def new_class(name: ObjString) -> ObjClass:
    """ObjClass* newClass(ObjString* name)"""
    klass = ObjClass(name)
    _allocate_object(klass)
    return klass


def new_closure(function: ObjFunction) -> ObjClosure:
    """ObjClosure* newClosure(ObjFunction* function)"""
    closure = ObjClosure(function)
    _allocate_object(closure)
    return closure


def new_function() -> ObjFunction:
    """ObjFunction* newFunction()"""
    function = ObjFunction()
    _allocate_object(function)
    return function


def new_instance(klass: ObjClass) -> ObjInstance:
    """ObjInstance* newInstance(ObjClass* klass)"""
    instance = ObjInstance(klass)
    _allocate_object(instance)
    return instance


def new_native(function: NativeFn) -> ObjNative:
    """ObjNative* newNative(NativeFn function)"""
    native = ObjNative(function)
    _allocate_object(native)
    return native


# --------------------------------------------------------------------------- #
# String allocation + interning
# --------------------------------------------------------------------------- #

def _allocate_string(chars: str, length: int, hash_val: int) -> ObjString:
    """static ObjString* allocateString(char* chars, int length, uint32_t hash)"""
    from pyvm.vm import vm, push, pop
    from pyvm.table import table_set
    from pyvm.value import NIL_VAL
    string = ObjString(chars, length, hash_val)
    _allocate_object(string)
    # Save it from GC: move to stack from C-stack.
    push(Value.obj_val(string))
    # We're using the table more like a hash set than a hash table.  The keys are
    # the strings and those are all we care about, so we just use nil for the
    # values.
    table_set(vm.strings, string, NIL_VAL())
    pop()
    return string


def _hash_string(key: str) -> int:
    """static uint32_t hashString(const char* key, int length)  (FNV-1a)"""
    hash_val = 2166136261
    for c in key:
        hash_val ^= ord(c)
        # Multiply and mask to 32 bits, mirroring uint32_t overflow.
        hash_val = (hash_val * 16777619) & 0xFFFFFFFF
    return hash_val


def take_string(chars: str, length: int) -> ObjString:
    """ObjString* takeString(char* chars, int length)

    But, for concatenation, we've already dynamically allocated a character
    array on the heap.  Making another copy of that would be redundant (and
    would mean ``concatenate()`` has to remember to free its copy).  Instead,
    this function claims ownership of the string you give it.
    """
    from pyvm.vm import vm
    from pyvm.table import table_find_string
    hash_val = _hash_string(chars)
    interned = table_find_string(vm.strings, chars, length, hash_val)
    if interned is not None:
        return interned
    return _allocate_string(chars, length, hash_val)


def copy_string(chars: str, length: int = -1) -> ObjString:
    """ObjString* copyString(const char* chars, int length)

    ``copyString()`` function assumes it cannot take ownership of the characters
    you pass in.  Instead, it conservatively creates a copy of the characters on
    the heap that the ObjString can own.  That's the right thing for string
    literals where the passed-in characters are in the middle of the source
    string.
    """
    from pyvm.vm import vm
    from pyvm.table import table_find_string
    if length < 0:
        length = len(chars)
    chars = chars[:length]
    hash_val = _hash_string(chars)
    interned = table_find_string(vm.strings, chars, length, hash_val)
    if interned is not None:
        return interned
    return _allocate_string(chars, length, hash_val)


def new_upvalue(stack_index: int) -> ObjUpvalue:
    """ObjUpvalue* newUpvalue(Value* slot)"""
    from pyvm.value import NIL_VAL
    upvalue = ObjUpvalue(stack_index)
    _allocate_object(upvalue)
    upvalue.closed = NIL_VAL()
    upvalue._stack_index = stack_index
    upvalue.next = None
    return upvalue


# --------------------------------------------------------------------------- #
# printObject / printFunction
# --------------------------------------------------------------------------- #

def _print_function(function: ObjFunction, file=sys.stdout) -> None:
    """static void printFunction(ObjFunction* function)"""
    if function.name is None:
        print("<script>", end="", file=file)
        return
    print(f"<fn {function.name.chars}>", end="", file=file)


def print_object(value: Value, file=sys.stdout) -> None:
    """void printObject(Value value)"""
    obj = value.as_obj()
    if obj.type is ObjType.OBJ_BOUND_METHOD:
        _print_function(as_bound_method(value).method.function, file)
    elif obj.type is ObjType.OBJ_CLASS:
        print(as_class(value).name.chars, end="", file=file)
    elif obj.type is ObjType.OBJ_CLOSURE:
        _print_function(as_closure(value).function, file)
    elif obj.type is ObjType.OBJ_FUNCTION:
        _print_function(as_function(value), file)
    elif obj.type is ObjType.OBJ_INSTANCE:
        print(f"{as_instance(value).klass.name.chars} instance", end="", file=file)
    elif obj.type is ObjType.OBJ_NATIVE:
        print("<native fn>", end="", file=file)
    elif obj.type is ObjType.OBJ_STRING:
        print(as_c_string(value), end="", file=file)
    elif obj.type is ObjType.OBJ_UPVALUE:
        print("upvalue", end="", file=file)