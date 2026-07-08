#ifndef clox_chunk_h
#define clox_chunk_h

#include "common.h"
#include "value.h"

// In our bytecode format
// each instruction has a one-byte operation code | opcode
// That number controls what kind of instruction we’re dealing with
// Each opcode determines how many operand bytes it has and what they mean.
// Each time we add a new opcode to clox, we specify what its operands look like (the instruction
// format)
typedef enum {
    // The compiled chunk needs to not only contain the values 1 and 2,
    // but know when to produce them so that they are printed in the right order.
    // we need an instruction that produces a particular constant.
    // OP-CODE OPERAND(VALUE-INDEX) => 2 bytes
    OP_CONSTANT,
    // having OP CODES in bytecode makes the VM go faster
    // than having the value be accessed via index
    OP_NIL,
    OP_TRUE,
    OP_FALSE,
    // evaluate expression for assignment
    OP_POP,
    // local var
    OP_GET_LOCAL,
    // read global var
    OP_GET_GLOBAL,
    // define global variables
    OP_DEFINE_GLOBAL,
    OP_SET_LOCAL,
    // assignment
    OP_SET_GLOBAL,
    // ==, !=, <, >, <=, and >=
    // The expression a != b has the same semantics as !(a == b), so the compiler is free to compile
    // the former as if it were the latter. Instead of a dedicated OP_NOT_EQUAL instruction, it can
    // output an OP_EQUAL followed by an OP_NOT. Likewise, a <= b is the same as !(a > b) and a >= b
    // is !(a < b). Thus, we only need three new instructions.
    OP_EQUAL,
    OP_GREATER,
    OP_LESS,
    // OP-CODE => 1 byte
    // Binary Ops
    // Arithmetic operations
    OP_ADD,
    OP_SUBTRACT,
    OP_MULTIPLY,
    OP_DIVIDE,
    OP_NOT,
    // Unary Ops
    // var a = 1.2; print -a => -1.2
    OP_NEGATE,
    OP_PRINT,
    OP_JUMP,
    OP_JUMP_IF_FALSE,
    OP_LOOP,
    // function call
    OP_CALL,
    // pops off the last stack value and returns
    OP_RETURN,
} OpCode;

// Bytecode is a series of instructions.
// We’ll store some other data along with the instructions,
// create a struct to hold it all.
// this is simply a wrapper around an array of bytes.
// dynamic array
typedef struct {
    int count;
    int capacity;
    uint8_t* code;
    // support for line number
    int* lines;
    // Each chunk will carry with it a list of the values that appear as literals in the program.
    // To keep things simpler, we’ll put all constants in there, even simple integers.
    ValueArray constants;
} Chunk;

void initChunk(Chunk* chunk);
void freeChunk(Chunk* chunk);
// To append a byte to the end of the chunk
void writeChunk(Chunk* chunk, uint8_t byte, int line);
// convenience method to add a new constant to the chunk.
int addConstant(Chunk* chunk, Value value);

#endif
