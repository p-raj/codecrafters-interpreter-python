#include "memory.h"

#include <stdlib.h>

#include "chunk.h"
#include "compiler.h"
#include "object.h"
#include "value.h"
#include "vm.h"

#ifndef DEBUG_LOG_GC
#include <stdio.h>

#include "debug.h"
#endif

#define GC_HEAP_GROW_FACTOR 2

// definitions
static void markRoots();
static void traceReferences();
static void sweep();

void* reallocate(void* pointer, size_t oldSize, size_t newSize) {
    vm.bytesAllocated += (newSize - oldSize);
    if (newSize > oldSize) {
#ifdef DEBUG_STRESS_GC
        collectGarbage();
#endif
    }

    if (vm.bytesAllocated > vm.nextGC) {
        collectGarbage();
    }

    if (newSize == 0) {
        free(pointer);
        return NULL;
    }

    void* result = realloc(pointer, newSize);
    // failed to alloc
    if (result == NULL) exit(1);
    return result;
}

void markObject(Obj* object) {
    if (object == NULL) return;
    // we need to ensure our collector doesn’t get stuck in an infinite loop as it continually
    // re-adds the same series of objects to the gray stack.
    if (object->isMarked) return;
#ifndef DEBUG_LOG_GC
    printf("%p mark ", (void*)object);
    printValue(OBJ_VAL(object));
    printf("\n");
#endif
    object->isMarked = true;

    // 3 color worklist to track marked, to be marked, unmarked
    if (vm.grayCapacity < vm.grayCount + 1) {
        vm.grayCapacity = GROW_CAPACITY(vm.grayCapacity);
        // The memory for the gray stack itself is not managed by the garbage collector. We don’t
        // want growing the gray stack during a GC to cause the GC to recursively start a new GC.
        vm.grayStack = (Obj**)realloc(vm.grayStack, sizeof(Obj*) * vm.grayCapacity);
        if (vm.grayStack == NULL) exit(1);
    }
    vm.grayStack[vm.grayCount++] = object;
}

void markValue(Value value) {
    if (IS_OBJ(value)) markObject(AS_OBJ(value));
}

static void markArray(ValueArray* array) {
    for (int i = 0; i < array->count; i++) {
        markValue(array->values[i]);
    }
}

static void blackenObject(Obj* object) {
#ifndef DEBUG_LOG_GC
    printf("%p blacken ", (void*)object);
    printValue(OBJ_VAL(object));
    printf("\n");
#endif
    // Note that we don’t set any state in the traversed object itself. There is no direct encoding
    // of “black” in the object’s state. A black object is any object whose isMarked field is set
    // and that is no longer in the gray stack.
    switch (object->type) {
        case OBJ_UPVALUE: {
            // When an upvalue is closed, it contains a reference to the closed-over value. Since
            // the value is no longer on the stack, we need to make sure we trace the reference to
            // it from the upvalue.
            markValue(((ObjUpvalue*)object)->closed);
            break;
        }
        case OBJ_CLOSURE: {
            ObjClosure* closure = (ObjClosure*)object;
            markObject((Obj*)closure->function);
            for (int i = 0; i < closure->upvalueCount; i++) {
                markObject((Obj*)closure->upvalues[i]);
            }
            break;
        }
        case OBJ_FUNCTION: {
            ObjFunction* function = (ObjFunction*)object;
            markObject((Obj*)function->name);
            markArray(&function->chunk.constants);
            break;
        }
        case OBJ_NATIVE:
        case OBJ_STRING:
            break;
    }
}

void collectGarbage() {
#ifndef DEBUG_LOG_GC
    printf("-- gc begin\n");
    size_t before = vm.bytesAllocated;
#endif
    markRoots();
    traceReferences();
    // the VM strings we have made "intern", that is a common hash for all the same strings
    // this is a major performance boost
    // but those string objects could be cleared
    // and the vm.strings would point to dangling pointers
    // This particular set of semantics comes up frequently enough that it has a name:
    // a weak reference.
    tableRemoveWhite(&vm.strings);
    sweep();
    // Now, finally, our garbage collector actually does something when the user runs a program
    // without our hidden diagnostic flag enabled. The sweep phase frees objects by calling
    // reallocate(), which lowers the value of bytesAllocated, so after the collection completes, we
    // know how many live bytes remain. We adjust the threshold of the next GC based on that.
    // Make the GC run dynamically and not statically
    vm.nextGC = vm.bytesAllocated * GC_HEAP_GROW_FACTOR;
#ifndef DEBUG_LOG_GC
    printf("-- gc end\n");
    printf("   collected %zu bytes (from %zu to %zu) next at %zu\n", before - vm.bytesAllocated,
           before, vm.bytesAllocated, vm.nextGC);
#endif
}

static void freeObject(Obj* object) {
#ifndef DEBUG_LOG_GC
    printf("%p free type %d\n", (void*)object, object->type);
#endif
    switch (object->type) {
        case OBJ_CLOSURE: {
            // We free only the ObjClosure itself, not the ObjFunction. That’s because the closure
            // doesn’t own the function
            ObjClosure* closure = (ObjClosure*)object;
            // ObjClosure does not own the ObjUpvalue objects themselves, but it does own the array
            // containing pointers to those upvalues.
            FREE_ARRAY(ObjUpvalue*, closure->upvalues, closure->upvalueCount);
            FREE(ObjClosure, object);
            break;
        }
        case OBJ_FUNCTION: {
            ObjFunction* fn = (ObjFunction*)object;
            freeChunk(&fn->chunk);
            FREE(ObjFunction, object);
            break;
        }
        case OBJ_NATIVE: {
            FREE(ObjNative, object);
            break;
        }
        case OBJ_STRING: {
            ObjString* string = (ObjString*)object;
            FREE_ARRAY(char, string->chars, string->length + 1);
            FREE(ObjString, object);
            break;
        }
        case OBJ_UPVALUE: {
            // Multiple closures can close over the same variable, so ObjUpvalue does not own the
            // variable it references. Thus, the only thing to free is the ObjUpvalue itself.
            FREE(ObjUpvalue, object);
            break;
        }
    }
}

static void markRoots() {
    for (Value* slot = vm.stack; slot < vm.stackTop; slot++) {
        markValue(*slot);
    }
    for (int i = 0; i < vm.frameCount; i++) {
        markObject((Obj*)vm.frames[i].closure);
    }
    for (ObjUpvalue* upvalue = vm.openUpvalues; upvalue != NULL; upvalue = upvalue->next) {
        markObject((Obj*)upvalue);
    }
    markTable(&vm.globals);
    markCompilerRoots();
}

static void traceReferences() {
    while (vm.grayCount > 0) {
        Obj* object = vm.grayStack[--vm.grayCount];
        blackenObject(object);
    }
}

static void sweep() {
    Obj* previous = NULL;
    Obj* object = vm.objects;
    while (object != NULL) {
        if (object->isMarked) {
            // After sweep() completes, the only remaining objects are the live black ones with
            // their mark bits set. That’s correct, but when the next collection cycle starts, we
            // need every object to be white. So whenever we reach a black object, we go ahead and
            // clear the bit now in anticipation of the next run.
            object->isMarked = false;
            previous = object;
            object = object->next;
        } else {
            Obj* unreached = object;
            object = object->next;
            if (previous != NULL) {
                previous->next = object;
            } else {
                vm.objects = object;
            }

            freeObject(unreached);
        }
    }
}

void freeObjects() {
    Obj* object = vm.objects;
    while (object != NULL) {
        Obj* next = object->next;
        freeObject(object);
        object = next;
    }
    free(vm.grayStack);
}
