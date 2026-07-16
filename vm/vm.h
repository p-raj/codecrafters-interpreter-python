// The virtual machine is one part of our interpreter’s internal architecture.
// You hand it a chunk of code—literally a Chunk—and it runs it.
// The code and data structures for the VM reside in a new module.

#ifndef clox_vm_h
#define clox_vm_h

#include "chunk.h"
#include "object.h"
#include "table.h"
#include "value.h"

#define FRAMES_MAX 64
#define STACK_MAX (FRAMES_MAX * UINT8_COUNT)

// each call that hasn’t returned yet—we need to track where on the stack that function’s locals
// begin, and where the caller should resume.
// A CallFrame represents a single ongoing function call.
typedef struct {
    ObjClosure* closure;
    // pointer to the function being called in here. We’ll use that to look up constants and for a
    // few other things.
    // ObjFunction* function;
    uint8_t* ip;
    // slots field points into the [[[VM’s value stack]]] at the [[[first slot]]] that
    // [[[this-function]]] can use.
    Value* slots;
} CallFrame;
// Instead of storing the return address in the callee’s frame, the caller stores its own ip.
// When we return from a function, the VM will jump to the [[[ip of the caller’s CallFrame]]] and
// resume from there.

typedef struct {
    // Introducting function based stack & call stacks
    // we dont have chunk executing, now its callers and callees
    // Chunk* chunk;
    // // instruction pointer
    // // We haven’t executed that instruction yet, so ip points to the instruction about to be
    // // executed.
    // uint8_t* ip;
    CallFrame frames[FRAMES_MAX];
    int frameCount;

    Value stack[STACK_MAX];
    Value* stackTop;
    // We need a hash-table to store these globals
    Table globals;
    // In order to reliably deduplicate all strings, the VM needs to be able to find every string
    // that’s created
    Table strings;
    // to make sure all the defined closure close over VARIABLE and not VALUE
    // SHARE VARIABLES
    ObjUpvalue* openUpvalues;
    // reference of all the objects that are heap allocated
    Obj* objects;
} VM;

typedef enum { INTERPRET_OK, INTERPRET_COMPILE_ERROR, INTERPRET_RUNTIME_ERROR } InterpretResult;

InterpretResult interpret_chunk(Chunk* chunk);
InterpretResult interpret(const char* source);
void push(Value value);
Value pop();

extern VM vm;

void initVM();
void freeVM();

#endif
