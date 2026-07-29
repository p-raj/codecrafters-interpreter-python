"""
memory.h / memory.c — the garbage collector for pyvm.

The C version implements a mark-and-sweep garbage collector because C has no
automatic memory management.  Every ``reallocate()`` call updates a byte
counter and may trigger a collection.

Python has its own garbage collector, so we don't *need* manual GC.  However,
we preserve the full structure (mark roots, trace references, sweep) and all
the comments for educational fidelity.  "Sweeping" here means removing the
object from our intrusive linked list; Python's own GC reclaims the actual
memory once no references remain.
"""

from __future__ import annotations

import sys
from typing import Optional, TYPE_CHECKING

from pyvm.common import DEBUG_STRESS_GC, DEBUG_LOG_GC

if TYPE_CHECKING:
    from pyvm.object import Obj
    from pyvm.value import Value, ValueArray
    from pyvm.table import Table


# The heap grows by this factor after each collection.
GC_HEAP_GROW_FACTOR: int = 2


# --------------------------------------------------------------------------- #
# reallocate / maybe_collect
# --------------------------------------------------------------------------- #

# In the C version, ``reallocate()`` is the single choke-point for all memory
# allocation, growth, and freeing.  It updates ``bytesAllocated`` and triggers
# the GC.  In Python we don't manage raw memory, but we keep a hook so the GC
# can still run for stress-testing / debugging.

def maybe_collect() -> None:
    """Hook called on every Obj allocation (mirrors the GC trigger in reallocate)."""
    from pyvm.vm import vm
    if DEBUG_STRESS_GC:
        collect_garbage()
        return
    if vm.bytes_allocated > vm.next_gc:
        collect_garbage()


# --------------------------------------------------------------------------- #
# markObject / markValue
# --------------------------------------------------------------------------- #

def mark_object(object: Optional["Obj"]) -> None:
    """void markObject(Obj* object)"""
    if object is None:
        return
    # We need to ensure our collector doesn't get stuck in an infinite loop as
    # it continually re-adds the same series of objects to the gray stack.
    if object.is_marked:
        return
    from pyvm.vm import vm
    if vm.debug_log_gc:
        from pyvm.value import Value
        from pyvm.object import print_object
        print(f"{id(object):#x} mark ", end="")
        print_object(Value.obj_val(object))
        print()

    object.is_marked = True

    # 3-color worklist to track marked, to-be-marked, unmarked.
    vm.gray_stack.append(object)
    vm.gray_count = len(vm.gray_stack)


def mark_value(value: "Value") -> None:
    """void markValue(Value value)"""
    from pyvm.value import Value as V
    if value.is_obj:
        mark_object(value.as_obj())


def mark_array(array: "ValueArray") -> None:
    """static void markArray(ValueArray* array)"""
    for i in range(array.count):
        mark_value(array.values[i])


# --------------------------------------------------------------------------- #
# blackenObject
# --------------------------------------------------------------------------- #

def _blacken_object(object: "Obj") -> None:
    """static void blackenObject(Obj* object)"""
    from pyvm.vm import vm
    from pyvm.object import (
        ObjType, ObjBoundMethod, ObjClass, ObjInstance, ObjUpvalue,
        ObjClosure, ObjFunction,
    )
    if vm.debug_log_gc:
        from pyvm.value import Value
        from pyvm.object import print_object
        print(f"{id(object):#x} blacken ", end="")
        print_object(Value.obj_val(object))
        print()

    # Note that we don't set any state in the traversed object itself.  There is
    # no direct encoding of "black" in the object's state.  A black object is
    # any object whose isMarked field is set and that is no longer in the gray
    # stack.
    if object.type is ObjType.OBJ_BOUND_METHOD:
        bound: ObjBoundMethod = object  # type: ignore[assignment]
        # This ensures that a handle to a method keeps the receiver around in
        # memory so that this can still find the object when you invoke the
        # handle later.  We also trace the method closure.
        mark_value(bound.receiver)
        mark_object(bound.method)
    elif object.type is ObjType.OBJ_CLASS:
        klass: ObjClass = object  # type: ignore[assignment]
        mark_object(klass.name)
        from pyvm.table import mark_table
        mark_table(klass.methods)
    elif object.type is ObjType.OBJ_INSTANCE:
        instance: ObjInstance = object  # type: ignore[assignment]
        mark_object(instance.klass)
        from pyvm.table import mark_table
        mark_table(instance.fields)
    elif object.type is ObjType.OBJ_UPVALUE:
        upvalue: ObjUpvalue = object  # type: ignore[assignment]
        # When an upvalue is closed, it contains a reference to the closed-over
        # value.  Since the value is no longer on the stack, we need to make
        # sure we trace the reference to it from the upvalue.
        mark_value(upvalue.closed)
    elif object.type is ObjType.OBJ_CLOSURE:
        closure: ObjClosure = object  # type: ignore[assignment]
        mark_object(closure.function)
        for i in range(closure.upvalue_count):
            mark_object(closure.upvalues[i])
    elif object.type is ObjType.OBJ_FUNCTION:
        function: ObjFunction = object  # type: ignore[assignment]
        mark_object(function.name)
        mark_array(function.chunk.constants)
    # OBJ_NATIVE and OBJ_STRING have no references to trace.
    elif object.type in (ObjType.OBJ_NATIVE, ObjType.OBJ_STRING):
        pass


# --------------------------------------------------------------------------- #
# collectGarbage
# --------------------------------------------------------------------------- #

def collect_garbage() -> None:
    """void collectGarbage()"""
    from pyvm.vm import vm
    if vm.debug_log_gc:
        print("-- gc begin")
        before = vm.bytes_allocated

    mark_roots()
    trace_references()

    # The VM strings we have made "intern", that is a common hash for all the
    # same strings.  This is a major performance boost.  But those string
    # objects could be cleared and the vm.strings would point to dangling
    # pointers.  This particular set of semantics comes up frequently enough
    # that it has a name: a weak reference.
    from pyvm.table import table_remove_white
    table_remove_white(vm.strings)

    sweep()

    # Now, finally, our garbage collector actually does something when the user
    # runs a program without our hidden diagnostic flag enabled.  The sweep
    # phase frees objects by calling reallocate(), which lowers the value of
    # bytesAllocated, so after the collection completes, we know how many live
    # bytes remain.  We adjust the threshold of the next GC based on that.
    # Make the GC run dynamically and not statically.
    vm.next_gc = vm.bytes_allocated * GC_HEAP_GROW_FACTOR

    if vm.debug_log_gc:
        print("-- gc end")
        print(
            f"   collected {before - vm.bytes_allocated} bytes "
            f"(from {before} to {vm.bytes_allocated}) next at {vm.next_gc}"
        )


# --------------------------------------------------------------------------- #
# freeObject
# --------------------------------------------------------------------------- #

def free_object(object: "Obj") -> None:
    """static void freeObject(Obj* object)"""
    from pyvm.vm import vm
    from pyvm.object import (
        ObjType, ObjClass, ObjClosure, ObjFunction, ObjInstance, ObjString,
    )
    if vm.debug_log_gc:
        print(f"{id(object):#x} free type {object.type.name}")

    # In Python we don't free memory manually — we simply let the object go out
    # of scope and Python's own GC handles reclamation.  We still clear any
    # owned sub-resources for parity with the C version.
    if object.type is ObjType.OBJ_BOUND_METHOD:
        pass  # ObjBoundMethod owns nothing extra.
    elif object.type is ObjType.OBJ_CLASS:
        klass: ObjClass = object  # type: ignore[assignment]
        from pyvm.table import free_table
        free_table(klass.methods)
    elif object.type is ObjType.OBJ_CLOSURE:
        # We free only the ObjClosure itself, not the ObjFunction.  That's
        # because the closure doesn't own the function.
        closure: ObjClosure = object  # type: ignore[assignment]
        # ObjClosure does not own the ObjUpvalue objects themselves, but it
        # does own the array containing pointers to those upvalues.
        closure.upvalues = []
    elif object.type is ObjType.OBJ_FUNCTION:
        fn: ObjFunction = object  # type: ignore[assignment]
        from pyvm.chunk import free_chunk
        free_chunk(fn.chunk)
    elif object.type is ObjType.OBJ_INSTANCE:
        instance: ObjInstance = object  # type: ignore[assignment]
        from pyvm.table import free_table
        free_table(instance.fields)
    # OBJ_NATIVE, OBJ_STRING, OBJ_UPVALUE own no extra resources.
    elif object.type in (ObjType.OBJ_NATIVE, ObjType.OBJ_STRING, ObjType.OBJ_UPVALUE):
        pass


# --------------------------------------------------------------------------- #
# markRoots / traceReferences / sweep
# --------------------------------------------------------------------------- #

def mark_roots() -> None:
    """static void markRoots()"""
    from pyvm.vm import vm
    # Mark every value currently on the VM's stack.
    for slot in range(vm.stack_top):
        mark_value(vm.stack[slot])
    # Mark every active call frame's closure.
    for i in range(vm.frame_count):
        mark_object(vm.frames[i].closure)
    # Mark the chain of open upvalues.
    upvalue = vm.open_upvalues
    while upvalue is not None:
        mark_object(upvalue)
        upvalue = upvalue.next
    # Mark the globals table.
    from pyvm.table import mark_table
    mark_table(vm.globals)
    # Mark the compiler's roots (functions being compiled).
    from pyvm.compiler import mark_compiler_roots
    mark_compiler_roots()
    # Mark the special "init" string.
    mark_object(vm.init_string)


def trace_references() -> None:
    """static void traceReferences()"""
    from pyvm.vm import vm
    while vm.gray_count > 0:
        object = vm.gray_stack.pop()
        vm.gray_count = len(vm.gray_stack)
        _blacken_object(object)


def sweep() -> None:
    """static void sweep()"""
    from pyvm.vm import vm
    previous: Optional["Obj"] = None
    object: Optional["Obj"] = vm.objects
    while object is not None:
        if object.is_marked:
            # After sweep() completes, the only remaining objects are the live
            # black ones with their mark bits set.  That's correct, but when the
            # next collection cycle starts, we need every object to be white.
            # So whenever we reach a black object, we go ahead and clear the bit
            # now in anticipation of the next run.
            object.is_marked = False
            previous = object
            object = object.next
        else:
            unreached = object
            object = object.next
            if previous is not None:
                previous.next = object
            else:
                vm.objects = object
            free_object(unreached)


def free_objects() -> None:
    """void freeObjects()"""
    from pyvm.vm import vm
    object = vm.objects
    while object is not None:
        nxt = object.next
        free_object(object)
        object = nxt
    vm.gray_stack = []
    vm.gray_count = 0