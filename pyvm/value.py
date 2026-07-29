"""
value.h / value.c — the Lox value system (tagged union) for pyvm.

In the C version, a Value is a tagged union: a struct with a type tag and a
union of bool / double / Obj*. In Python we use a small dataclass-like wrapper
to preserve the same semantics, plus helper functions that mirror the C macros
IS_*, AS_*, and *_VAL.
"""

from __future__ import annotations

import sys
from enum import Enum, auto
from typing import Any, Optional, TextIO, TYPE_CHECKING

if TYPE_CHECKING:
    from pyvm.object import Obj

# --------------------------------------------------------------------------- #
# ValueType  (mirrors the C enum)
# --------------------------------------------------------------------------- #

class ValueType(Enum):
    VAL_BOOL = auto()
    VAL_NIL = auto()
    VAL_NUMBER = auto()
    # Lives on the heap.
    VAL_OBJ = auto()


# --------------------------------------------------------------------------- #
# Value  (tagged union)
# --------------------------------------------------------------------------- #

class Value:
    """
    A Lox value is a tagged union.  The ``type`` field tells us which variant
    of the union is currently active, and ``as_*`` helpers extract the native
    Python value.

    In C this is::

        typedef struct {
            ValueType type;
            union {
                bool   boolean;
                double number;
                Obj*   obj;
            } as;
        } Value;

    In Python we store the raw value in ``self._as`` and guard access through
    the helper functions, just like the AS_* macros do in C.
    """

    __slots__ = ("type", "_as")

    def __init__(self, type: ValueType, as_val: Any) -> None:
        self.type: ValueType = type
        self._as: Any = as_val

    # -- Validations and checks (mirror the IS_* macros) ---------------------

    @property
    def is_bool(self) -> bool:   # IS_BOOL(value)
        return self.type is ValueType.VAL_BOOL

    @property
    def is_nil(self) -> bool:    # IS_NIL(value)
        return self.type is ValueType.VAL_NIL

    @property
    def is_number(self) -> bool:  # IS_NUMBER(value)
        return self.type is ValueType.VAL_NUMBER

    @property
    def is_obj(self) -> bool:    # IS_OBJ(value)
        return self.type is ValueType.VAL_OBJ

    # -- Conversion helpers (mirror the AS_* macros) -------------------------

    def as_bool(self) -> bool:            # AS_BOOL(value)
        return bool(self._as)

    def as_number(self) -> float:         # AS_NUMBER(value)
        return float(self._as)

    def as_obj(self) -> "Obj":            # AS_OBJ(value)
        from pyvm.object import Obj
        return self._as  # type: ignore[return-value]

    # -- Convenience constructors (mirror the *_VAL macros) ------------------

    @staticmethod
    def bool_val(value: bool) -> "Value":        # BOOL_VAL(value)
        return Value(ValueType.VAL_BOOL, value)

    @staticmethod
    def nil_val() -> "Value":                    # NIL_VAL
        return Value(ValueType.VAL_NIL, 0.0)

    @staticmethod
    def number_val(value: float) -> "Value":     # NUMBER_VAL(value)
        return Value(ValueType.VAL_NUMBER, float(value))

    @staticmethod
    def obj_val(obj: "Obj") -> "Value":          # OBJ_VAL(object)
        return Value(ValueType.VAL_OBJ, obj)

    # -- Equality -------------------------------------------------------------

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, Value):
            return NotImplemented
        return values_equal(self, other)

    def __hash__(self) -> int:
        return hash((self.type, self._as))

    def __repr__(self) -> str:
        return f"Value({self.type.name}, {self._as!r})"


# --------------------------------------------------------------------------- #
# ValueArray  (dynamic array of Values — the constant pool)
# --------------------------------------------------------------------------- #

# Each chunk will carry with it a list of the values that appear as literals in
# the program.  To keep things simpler, we'll put all constants in there, even
# simple integers.  The constant pool is an array of values.  The instruction to
# load a constant looks up the value by index in that array.
class ValueArray:
    """A growable array of Values."""

    def __init__(self) -> None:
        # In Python we can just use a list, but we keep the same field names as
        # the C struct for clarity.
        self.capacity: int = 0
        self.count: int = 0
        self.values: list[Value] = []

    def write(self, value: Value) -> None:
        # In C this grows the capacity; in Python lists grow automatically.
        self.capacity = max(self.capacity, len(self.values) + 1)
        self.values.append(value)
        self.count = len(self.values)

    def free(self) -> None:
        self.__init__()

    def __getitem__(self, index: int) -> Value:
        return self.values[index]

    def __len__(self) -> int:
        return self.count


# --------------------------------------------------------------------------- #
# Module-level macro equivalents (IS_* / AS_* / *_VAL)
# --------------------------------------------------------------------------- #
#
# In C these are preprocessor macros.  In Python we provide module-level
# functions with the same names so call sites read almost identically to the C
# source.

# -- Validations and checks (mirror the IS_* macros) -----------------------

def IS_BOOL(value: Value) -> bool:
    return value.type is ValueType.VAL_BOOL


def IS_NIL(value: Value) -> bool:
    return value.type is ValueType.VAL_NIL


def IS_NUMBER(value: Value) -> bool:
    return value.type is ValueType.VAL_NUMBER


def IS_OBJ(value: Value) -> bool:
    return value.type is ValueType.VAL_OBJ


# -- Conversion helpers (mirror the AS_* macros) ---------------------------

def AS_BOOL(value: Value) -> bool:
    return value.as_bool()


def AS_NUMBER(value: Value) -> float:
    return value.as_number()


def AS_OBJ(value: Value):
    return value.as_obj()


# -- Value constructors (mirror the *_VAL macros) -------------------------

def BOOL_VAL(b: bool) -> Value:
    return Value(ValueType.VAL_BOOL, b)


def NUMBER_VAL(n: float) -> Value:
    return Value(ValueType.VAL_NUMBER, float(n))


def OBJ_VAL(obj) -> Value:
    return Value(ValueType.VAL_OBJ, obj)


# A shared NIL value constant — nil is immutable so this is safe.
def NIL_VAL() -> Value:
    return Value(ValueType.VAL_NIL, 0.0)


# --------------------------------------------------------------------------- #
# Module-level functions (mirrors value.c)
# --------------------------------------------------------------------------- #

def values_equal(a: Value, b: Value) -> bool:
    """bool valuesEqual(Value a, Value b)"""
    if a.type is not b.type:
        return False
    if a.type is ValueType.VAL_BOOL:
        return a.as_bool() == b.as_bool()
    if a.type is ValueType.VAL_NIL:
        return True
    if a.type is ValueType.VAL_NUMBER:
        return a.as_number() == b.as_number()
    if a.type is ValueType.VAL_OBJ:
        # In fact, now that we've interned all the strings, we can take
        # advantage of it in the bytecode interpreter.  When a user does == on
        # two objects that happen to be strings, we don't need to test the
        # characters any more.
        return a.as_obj() is b.as_obj()
    return False  # Unreachable.


def init_value_array() -> ValueArray:
    """void initValueArray(ValueArray* array)"""
    return ValueArray()


def write_value_array(array: ValueArray, value: Value) -> None:
    """void writeValueArray(ValueArray* array, Value value)"""
    array.write(value)


def free_value_array(array: ValueArray) -> None:
    """void freeValueArray(ValueArray* array)"""
    array.free()


def print_value(value: Value, file: TextIO = sys.stdout) -> None:
    """void printValue(Value value)"""
    if value.type is ValueType.VAL_BOOL:
        print("true" if value.as_bool() else "false", end="", file=file)
    elif value.type is ValueType.VAL_NIL:
        print("nil", end="", file=file)
    elif value.type is ValueType.VAL_NUMBER:
        # %g format: strip trailing zeros, use scientific notation when needed.
        num = value.as_number()
        if num == int(num) and abs(num) < 1e16:
            print(int(num), end="", file=file)
        else:
            print(repr(num), end="", file=file)
    elif value.type is ValueType.VAL_OBJ:
        from pyvm.object import print_object
        print_object(value, file=file)