#include <stdlib.h>

#include "chunk.h"
#include "memory.h"

// This reduction is a key reason why our new interpreter will be faster than jlox. 
// You can think of bytecode as a sort of compact serialization of the AST
// highly optimized for how the interpreter will deserialize it in the order it needs as it executes. 
void initChunk(Chunk* chunk) {
    // how many are there
    chunk -> count = 0;
    // how many it can hold
    chunk -> capacity = 0;
    // line number support
    // Every time we touch the code array
    // we make a corresponding change to the line number array
    // starting with initialization.
    // In the chunk, we store a separate array of integers that parallels the bytecode
    // When a runtime error occurs, we look up the line number at the same index as 
    // the current instruction’s offset in the code array.
    chunk -> lines = NULL;
    // code
    chunk -> code = NULL;
    // value array
    initValueArray(&chunk->constants);
}

void freeChunk(Chunk* chunk) {
    FREE_ARRAY(uint8_t, chunk -> code, chunk -> capacity);
    FREE_ARRAY(int, chunk -> lines, chunk -> capacity);
    freeValueArray(&chunk->constants);
    initChunk(chunk);
}

void writeChunk(Chunk* chunk, uint8_t byte, int line) {
    // can it hold one more?
    if (chunk -> capacity < chunk -> count + 1) {
        // nope
        int oldCapacity = chunk -> capacity;
        chunk -> capacity = GROW_CAPACITY(oldCapacity);
        chunk -> code = GROW_ARRAY(uint8_t, chunk -> code, oldCapacity, chunk -> capacity);
        chunk -> lines = GROW_ARRAY(int, chunk -> lines, oldCapacity, chunk -> capacity);
    }
    
    // get over here!
    chunk -> code[chunk -> count] = byte;
    chunk -> lines[chunk -> count] = line;
    chunk -> count++;
}

int addConstant(Chunk* chunk, Value value) {
    writeValueArray(&chunk->constants, value);
    return chunk -> constants.count - 1;
}