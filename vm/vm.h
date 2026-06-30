// The virtual machine is one part of our interpreter’s internal architecture.
// You hand it a chunk of code—literally a Chunk—and it runs it.
// The code and data structures for the VM reside in a new module.

#ifndef clox_vm_h
#define clox_vm_h

#include "chunk.h"
#include "table.h"
#include "value.h"

#define STACK_MAX 256

typedef struct {
    Chunk* chunk;
    // instruction pointer
    // We haven’t executed that instruction yet, so ip points to the instruction about to be
    // executed.
    uint8_t* ip;
    Value stack[STACK_MAX];
    Value* stackTop;
    // We need a hash-table to store these globals
    Table globals;
    // In order to reliably deduplicate all strings, the VM needs to be able to find every string
    // that’s created
    Table strings;
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
