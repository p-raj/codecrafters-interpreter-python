#include "vm.h"

#include <stdarg.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>

#include "chunk.h"
#include "common.h"
#include "compiler.h"
#include "debug.h"
#include "memory.h"
#include "object.h"
#include "table.h"
#include "value.h"

// declarations
VM vm;
static Value peek(int distance);
static bool isFalsy(Value value);
static void concatenate();

static void resetStack() { vm.stackTop = vm.stack; }

static void runtimeError(const char* format, ...) {
    va_list args;
    va_start(args, format);
    vfprintf(stderr, format, args);
    va_end(args);
    fputs("\n", stderr);

    size_t instruction = vm.ip - vm.chunk->code - 1;
    int line = vm.chunk->lines[instruction];
    fprintf(stderr, "[line %d] in script\n", line);
    resetStack();
}

static InterpretResult run() {
#define READ_BYTE() (*vm.ip++)
// READ_CONSTANT() reads the next byte from the bytecode,
// treats the resulting number as an index,
// and looks up the corresponding Value in the chunk’s constant table.
#define READ_CONSTANT() (vm.chunk->constants.values[READ_BYTE()])

// It reads a one-byte operand from the bytecode chunk. It treats that as an index into the chunk’s
// constant table and returns the string at that index. It doesn’t check that the value is a
// string—it just indiscriminately casts it. That’s safe because the compiler never emits an
// instruction that refers to a non-string constant.
#define READ_STRING() AS_STRING(READ_CONSTANT())

// Now you get a compile error on the else because of that trailing ; after the macro’s block.
// Using a do while loop in the macro looks funny,
// but it gives you a way to contain multiple statements inside a block that also permits a
// semicolon at the end.
#define BINARY_OP(valueType, op)                          \
    do {                                                  \
        if (!IS_NUMBER(peek(0)) || !IS_NUMBER(peek(1))) { \
            runtimeError("Operands must be numbers.");    \
            return INTERPRET_RUNTIME_ERROR;               \
        }                                                 \
        double b = AS_NUMBER(pop());                      \
        double a = AS_NUMBER(pop());                      \
        push(valueType(a op b));                          \
    } while (false)

    for (;;) {
#ifdef DEBUG_TRACE_EXECUTION
        printf("\t\t");
        for (Value* slot = vm.stack; slot < vm.stackTop; slot++) {
            printf("[ ");
            printValue(*slot);
            printf(" ]");
        }
        printf("\n");
        disassembleInstruction(vm.chunk, (int)(vm.ip - vm.chunk->code));
#endif
        // Given a numeric opcode,
        // we need to get to the right C code that implements that instruction’s semantics.
        // This process is called decoding or dispatching the instruction.
        uint8_t instruction;
        switch (instruction = READ_BYTE()) {
            case OP_CONSTANT: {
                Value constant = READ_CONSTANT();
                push(constant);
                break;
            }
            case OP_NIL:
                push(NIL_VAL);
                break;
            case OP_TRUE:
                push(BOOL_VAL(true));
                break;
            case OP_FALSE:
                push(BOOL_VAL(false));
                break;
            case OP_POP: {
                pop();
                break;
            }
            case OP_GET_LOCAL: {
                // It takes a single-byte operand for the stack slot where the local lives. It loads
                // the value from that index and then pushes it on top of the stack where later
                // instructions can find it.
                uint8_t slot = READ_BYTE();
                push(vm.stack[slot]);
                break;
            }
            case OP_GET_GLOBAL: {
                ObjString* name = READ_STRING();
                Value value;
                // We pull the constant table index from the instruction’s operand and get the
                // variable name. Then we use that as a key to look up the variable’s value in the
                // globals hash table.
                if (!tableGet(&vm.globals, name, &value)) {
                    runtimeError("Undefined variable '%s'.", name->chars);
                    return INTERPRET_RUNTIME_ERROR;
                }
                push(value);
                break;
            }
            case OP_DEFINE_GLOBAL: {
                // We get the name of the variable from the constant table. Then we take the value
                // from the top of the stack and store it in a hash table with that name as the key.
                ObjString* name = READ_STRING();
                tableSet(&vm.globals, name, peek(0));
                pop();
                break;
            }
            case OP_SET_LOCAL: {
                uint8_t slot = READ_BYTE();
                // Remember, assignment is an expression, and every expression produces a value.
                // The value of an assignment expression is the assigned value itself, so the VM
                // just leaves the value on the stack.
                vm.stack[slot] = peek(0);
                break;
            }
            case OP_SET_GLOBAL: {
                ObjString* name = READ_STRING();
                if (tableSet(&vm.globals, name, peek(0))) {
                    // if set and is a new key
                    // we will mark that as an error
                    // If the variable hasn’t been defined yet, it’s a runtime error to try to
                    // assign to it. Lox doesn’t do implicit variable declaration.
                    tableDelete(&vm.globals, name);
                    runtimeError("Undefined variable '%s'.", name->chars);
                    return INTERPRET_RUNTIME_ERROR;
                }
                // The other difference is that setting a variable doesn’t pop the value off the
                // stack. Remember, assignment is an expression, so it needs to leave that value
                // there in case the assignment is nested inside some larger expression.
                break;
            }
            case OP_EQUAL: {
                Value b = pop();
                Value a = pop();
                push(BOOL_VAL(valuesEqual(a, b)));
                break;
            }
            case OP_GREATER:
                BINARY_OP(BOOL_VAL, >);
                break;
            case OP_LESS:
                BINARY_OP(BOOL_VAL, <);
                break;
            case OP_ADD: {
                if (IS_STRING(peek(0)) && IS_STRING(peek(1))) {
                    concatenate();
                } else if (IS_NUMBER(peek(0)) && IS_NUMBER(peek(1))) {
                    double b = AS_NUMBER(pop());
                    double a = AS_NUMBER(pop());
                    push(NUMBER_VAL(a + b));
                } else {
                    runtimeError("Operands must be two numbers or two strings.");
                    return INTERPRET_RUNTIME_ERROR;
                }
                break;
            }
            case OP_SUBTRACT: {
                BINARY_OP(NUMBER_VAL, -);
                break;
            }
            case OP_MULTIPLY: {
                BINARY_OP(NUMBER_VAL, *);
                break;
            }
            case OP_DIVIDE: {
                BINARY_OP(NUMBER_VAL, /);
                break;
            }
            case OP_NOT: {
                push(BOOL_VAL(isFalsy(pop())));
                break;
            }
            case OP_NEGATE: {
                if (!IS_NUMBER(peek(0))) {
                    runtimeError("Operand must be a number.");
                    return INTERPRET_RUNTIME_ERROR;
                }
                push(NUMBER_VAL(-(AS_NUMBER(pop()))));
                break;
            }
            case OP_PRINT: {
                // Note that we don’t push anything else after that.
                // This is a key difference between expressions and statements in the VM.
                // Every bytecode instruction has a stack effect that describes how the instruction
                // modifies the stack.
                // The bytecode for an entire statement has a total stack effect of zero.
                printValue(pop());
                printf("\n");
                break;
            }
            case OP_RETURN: {
                return INTERPRET_OK;
            }
        }
    }

#undef READ_BYTE
#undef READ_CONSTANT
#undef READ_STRING
#undef BINARY_OP
}

InterpretResult interpret_chunk(Chunk* chunk) {
    vm.chunk = chunk;
    vm.ip = vm.chunk->code;
    return run();
}

InterpretResult interpret(const char* source) {
    printf("%s", source);
    // We create a new empty chunk and pass it over to the compiler.
    Chunk chunk;
    initChunk(&chunk);

    // The compiler will take the user’s program and fill up the chunk with bytecode.
    if (!compile(source, &chunk)) {
        // If it does encounter an error, compile() returns false and we discard the unusable chunk.
        freeChunk(&chunk);
        return INTERPRET_COMPILE_ERROR;
    }

    vm.chunk = &chunk;
    vm.ip = vm.chunk->code;

    InterpretResult result = run();
    return result;
}

void initVM() {
    resetStack();
    vm.objects = NULL;
    initTable(&vm.globals);
    initTable(&vm.strings);
}

void freeVM() {
    freeTable(&vm.globals);
    freeTable(&vm.strings);
    freeObjects();
}

void push(Value value) {
    *vm.stackTop = value;
    vm.stackTop++;
}

Value pop() {
    vm.stackTop--;
    return *vm.stackTop;
}

static Value peek(int distance) { return vm.stackTop[-1 - distance]; }

static bool isFalsy(Value value) { return IS_NIL(value) || (IS_BOOL(value) && !AS_BOOL(value)); }

static void concatenate() {
    ObjString* b = AS_STRING(pop());
    ObjString* a = AS_STRING(pop());

    int length = a->length + b->length;
    char* chars = ALLOCATE(char, length + 1);
    memcpy(chars, a->chars, a->length);
    memcpy(chars + a->length, b->chars, b->length);
    chars[length] = '\0';

    ObjString* result = takeString(chars, length);
    push(OBJ_VAL(result));
}
