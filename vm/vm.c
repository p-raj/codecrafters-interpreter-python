#include "vm.h"

#include <stdarg.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>
#include <time.h>

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
// static bool call(ObjFunction* function, int argCount);
static bool call(ObjClosure* closure, int argCount);
static bool callValue(Value callee, int argCount);
static ObjUpvalue* captureUpvalue(Value* local);
static void closeUpvalues(Value* last);
static bool isFalsy(Value value);
static void concatenate();

static Value clockNative(int argCount, Value* args) {
    return NUMBER_VAL((double)clock() / CLOCKS_PER_SEC);
}

static void resetStack() {
    vm.stackTop = vm.stack;
    vm.frameCount = 0;
    vm.openUpvalues = NULL;
}

static void runtimeError(const char* format, ...) {
    va_list args;
    va_start(args, format);
    vfprintf(stderr, format, args);
    va_end(args);
    fputs("\n", stderr);

    // size_t instruction = vm.ip - vm.chunk->code - 1;
    // int line = vm.chunk->lines[instruction];
    // REPLACED with STACK-TRACE
    // CallFrame* frame = &vm.frames[vm.frameCount - 1];
    // size_t instruction = frame->ip - frame->function->chunk.code - 1;
    // int line = frame->function->chunk.lines[instruction];
    // fprintf(stderr, "[line %d] in script\n", line);
    for (int i = vm.frameCount - 1; i >= 0; i--) {
        CallFrame* frame = &vm.frames[i];
        ObjFunction* function = frame->closure->function;
        // The - 1 is because the IP is already sitting on the next instruction to be executed but
        // we want the stack trace to point to the previous failed instruction.
        size_t instruction = frame->ip - function->chunk.code - 1;
        fprintf(stderr, "[line %d] in ", function->chunk.lines[instruction]);
        if (function->name == NULL) {
            fprintf(stderr, "script\n");
        } else {
            fprintf(stderr, "%s()\n", function->name->chars);
        }
    }
    resetStack();
}

// Without something like a foreign function interface, users can’t define their own native
// functions. That’s our job as VM implementers. We’ll start with a helper to define a new native
// function exposed to Lox programs.
static void defineNative(const char* name, NativeFn function) {
    push(OBJ_VAL(copyString(name, (int)strlen(name))));
    push(OBJ_VAL(newNative(function)));
    tableSet(&vm.globals, AS_STRING(vm.stack[0]), vm.stack[1]);
    // why we push and pop the name and function on the stack. This is the kind of stuff you have to
    // worry about when garbage collection gets involved. Both copyString() and newNative()
    // dynamically allocate memory.
    // That means once we have a GC, they can potentially trigger a
    // collection. If that happens, we need to ensure the collector knows we’re not done with the
    // name and ObjFunction so that it doesn’t free them out from under us. Storing them on the
    // value stack accomplishes that.
    pop();
    pop();
}

static InterpretResult run() {
    CallFrame* frame = &vm.frames[vm.frameCount - 1];

// #define READ_BYTE() (*vm.ip++)
#define READ_BYTE() (*frame->ip++)

// #define READ_SHORT() (vm.ip += 2, (uint16_t)((vm.ip[-2] << 8) | vm.ip[-1]))
#define READ_SHORT() (frame->ip += 2, (uint16_t)((frame->ip[-2] << 8) | frame->ip[-1]))

// READ_CONSTANT() reads the next byte from the bytecode,
// treats the resulting number as an index,
// and looks up the corresponding Value in the chunk’s constant table.
// #define READ_CONSTANT() (vm.chunk->constants.values[READ_BYTE()])
// #define READ_CONSTANT() (frame->function->chunk.constants.values[READ_BYTE()])
#define READ_CONSTANT() (frame->closure->function->chunk.constants.values[READ_BYTE()])

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
        // disassembleInstruction(vm.chunk, (int)(vm.ip - vm.chunk->code));
        disassembleInstruction(&frame->closure->function->chunk,
                               (int)(frame->ip - frame->closure->function->chunk.code));
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
                // OP_GET_LOCAL read the given local slot directly from the VM’s stack array, which
                // meant it indexed the slot starting from the bottom of the stack
                // push(vm.stack[slot]);
                // now it accesses the current frame’s slots array, which means it accesses the
                // given numbered slot relative to the beginning of that frame.
                push(frame->slots[slot]);
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
                // vm.stack[slot] = peek(0);
                frame->slots[slot] = peek(0);
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
            case OP_GET_UPVALUE: {
                uint8_t slot = READ_BYTE();
                push(*frame->closure->upvalues[slot]->location);
                break;
            }
            case OP_SET_UPVALUE: {
                uint8_t slot = READ_BYTE();
                *frame->closure->upvalues[slot]->location = peek(0);
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
                // [NOTE], each statement is required to have zero stack effect—after the
                // statement is finished executing, the stack should be as tall as it was before.
                printValue(pop());
                printf("\n");
                break;
            }
            case OP_JUMP: {
                uint16_t offset = READ_SHORT();
                // vm.ip += offset;
                frame->ip += offset;
                break;
            }
            case OP_JUMP_IF_FALSE: {
                uint16_t offset = READ_SHORT();
                // we have to do some more work here to ensure that stack gets cleaned up
                // if we are jumping to a different offset
                // the stack that was supposed to get used if the code would have chosen the
                // <if branch> is still there
                if (isFalsy(peek(0))) {
                    // vm.ip += offset;
                    frame->ip += offset;
                }
                break;
            }
            case OP_LOOP: {
                uint16_t offset = READ_SHORT();
                // vm.ip -= offset;
                frame->ip -= offset;
                break;
            }
            case OP_CALL: {
                int argCount = READ_BYTE();
                // argCount also tells us where to find the function on the stack by counting past
                // the argument slots from the top of the stack.
                if (!callValue(peek(argCount), argCount)) {
                    return INTERPRET_RUNTIME_ERROR;
                }
                // If callValue() is successful, there will be a new frame on the CallFrame stack
                // for the called function. The run() function has its own cached pointer to the
                // current frame, so we need to update that.
                frame = &vm.frames[vm.frameCount - 1];
                break;
            }
            case OP_CLOSURE: {
                ObjFunction* fun = AS_FUNCTION(READ_CONSTANT());
                ObjClosure* closure = newClosure(fun);
                // Closures capture [variables]. You can think of them as capturing the
                // place the value lives. This is important to keep in mind as we deal with
                // closed-over variables that are no longer on the stack. When a variable moves to
                // the heap, we need to ensure that all closures capturing that variable retain a
                // reference to its one new location. That way, when the variable is mutated, all
                // closures see the change.
                // We know that local variables always start out on the stack. This is faster, and
                // lets our single-pass compiler emit code before it discovers the variable has been
                // captured. We also know that closed-over variables need to move to the heap if the
                // closure outlives the function where the captured variable is declared.
                push(OBJ_VAL(closure));
                for (int i = 0; i < closure->upvalueCount; i++) {
                    uint8_t isLocal = READ_BYTE();
                    uint8_t index = READ_BYTE();
                    if (isLocal) {
                        closure->upvalues[i] = captureUpvalue(frame->slots + index);
                    } else {
                        // MEGA COOL
                        // Otherwise, we capture an upvalue from the surrounding function. An
                        // OP_CLOSURE instruction is emitted at the end of a function declaration.
                        // At the moment that we are executing that declaration, the current
                        // function is the surrounding one. That means the current function’s
                        // closure is stored in the CallFrame at the top of the callstack. So, to
                        // grab an upvalue from the enclosing function, we can read it right from
                        // the frame local variable, which caches a reference to that CallFrame.
                        closure->upvalues[i] = frame->closure->upvalues[index];
                    }
                }
                break;
            }
            case OP_CLOSE_UPVALUE: {
                closeUpvalues(vm.stackTop - 1);
                pop();
                break;
            }
            case OP_RETURN: {
                // When a function returns a value, that value will be on top of the stack. We’re
                // about to discard the called function’s entire stack window, so we pop that return
                // value off and hang on to it.
                Value result = pop();
                // By passing the first slot in the function’s stack window, we close every
                // remaining open upvalue owned by the returning function. And with that, we now
                // have a fully functioning closure implementation. Closed-over variables live as
                // long as they are needed by the functions that capture them.
                closeUpvalues(frame->slots);
                // Then we discard the CallFrame for the returning function.
                vm.frameCount--;

                // If that was the very last CallFrame, it means we’ve finished executing the
                // top-level code. The entire program is done, so we pop the main script function
                // from the stack and then exit the interpreter.
                if (vm.frameCount == 0) {
                    pop();
                    return INTERPRET_OK;
                }

                vm.stackTop = frame->slots;
                push(result);
                frame = &vm.frames[vm.frameCount - 1];
                break;
            }
        }
    }

#undef READ_BYTE
#undef READ_CONSTANT
#undef READ_SHORT
#undef READ_STRING
#undef BINARY_OP
}

// InterpretResult interpret_chunk(Chunk* chunk) {
//     vm.chunk = chunk;
//     vm.ip = vm.chunk->code;
//     return run();
// }

InterpretResult interpret(const char* source) {
    // printf("%s", source);
    // // We create a new empty chunk and pass it over to the compiler.
    // Chunk chunk;
    // initChunk(&chunk);

    // // The compiler will take the user’s program and fill up the chunk with bytecode.
    // if (!compile(source, &chunk)) {
    //     // If it does encounter an error, compile() returns false and we discard the unusable
    //     chunk. freeChunk(&chunk); return INTERPRET_COMPILE_ERROR;
    // }

    // vm.chunk = &chunk;
    // vm.ip = vm.chunk->code;
    //

    // compiler: It returns us a new ObjFunction containing the compiled top-level code.
    ObjFunction* function = compile(source);
    ObjClosure* closure = newClosure(function);
    if (function == NULL) return INTERPRET_COMPILE_ERROR;
    // we store the function on the stack and prepare an initial CallFrame to execute its code.
    push(OBJ_VAL(closure));
    call(closure, 0);
    // CallFrame* frame = &vm.frames[vm.frameCount++];
    // frame->function = function;
    // frame->ip = function->chunk.code;
    // frame->slots = vm.stack;

    // InterpretResult result = run();
    // return result;
    return run();
}

void initVM() {
    resetStack();
    vm.objects = NULL;

    vm.bytesAllocated = 0;
    vm.nextGC = 1024 * 1024;

    vm.grayCount = 0;
    vm.grayCapacity = 0;
    vm.grayStack = NULL;

    initTable(&vm.globals);
    initTable(&vm.strings);
    defineNative("clock", clockNative);
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

// static bool call(ObjFunction* function, int argCount) {
static bool call(ObjClosure* closure, int argCount) {
    if (argCount != closure->function->arity) {
        runtimeError("Expected %d arguments but got %d.", closure->function->arity, argCount);
        return false;
    }
    if (vm.frameCount == FRAMES_MAX) {
        runtimeError("Stack overflow.");
        return false;
    }
    CallFrame* frame = &vm.frames[vm.frameCount++];
    // frame->function = function;
    frame->closure = closure;
    frame->ip = closure->function->chunk.code;
    frame->slots = vm.stackTop - argCount - 1;
    return true;
}

static bool callValue(Value callee, int argCount) {
    if (IS_OBJ(callee)) {
        switch (OBJ_TYPE(callee)) {
                // case OBJ_FUNCTION:
                //     return call(AS_FUNCTION(callee), argCount);
                // [NOTE] Since we wrap all functions in ObjClosures, the runtime will never try to
                // invoke a bare ObjFunction anymore. Those objects live only in constant tables and
                // get immediately wrapped in closures before anything else sees them.
            case OBJ_CLOSURE: {
                return call(AS_CLOSURE(callee), argCount);
            }
            case OBJ_NATIVE: {
                NativeFn native = AS_NATIVE(callee);
                Value result = native(argCount, vm.stackTop - argCount);
                vm.stackTop -= argCount + 1;
                push(result);
                return true;
            }
            default:
                break;  // Non-callable object type.
        }
    }
    runtimeError("Can only call functions and classes.");
    return false;
}

static ObjUpvalue* captureUpvalue(Value* local) {
    ObjUpvalue* prevUpvalue = NULL;
    ObjUpvalue* upvalue = vm.openUpvalues;
    // trace the linked list
    // Even better, we can order the list of open upvalues by the stack slot index they point to.
    // The common case is that a slot has not already been captured—sharing variables between
    // closures is uncommon—and closures tend to capture locals near the top of the stack. If we
    // store the open upvalue array in stack slot order, as soon as we step past the slot where the
    // local we’re capturing lives, we know it won’t be found. When that local is near the top of
    // the stack, we can exit the loop pretty early.
    while (upvalue != NULL && upvalue->location > local) {
        prevUpvalue = upvalue;
        upvalue = upvalue->next;
    }
    if (upvalue != NULL && upvalue->location == local) {
        return upvalue;
    }
    ObjUpvalue* createdUpvalue = newUpvalue(local);
    createdUpvalue->next = upvalue;

    if (prevUpvalue == NULL) {
        vm.openUpvalues = createdUpvalue;
    } else {
        prevUpvalue->next = createdUpvalue;
    }
    return createdUpvalue;
}

static bool isFalsy(Value value) { return IS_NIL(value) || (IS_BOOL(value) && !AS_BOOL(value)); }

static void closeUpvalues(Value* last) {
    while (vm.openUpvalues != NULL && vm.openUpvalues->location >= last) {
        ObjUpvalue* upvalue = vm.openUpvalues;
        upvalue->closed = *upvalue->location;
        upvalue->location = &upvalue->closed;
        vm.openUpvalues = upvalue->next;
    }
}

static void concatenate() {
    // If we pop these, now with GC these could very well be sweeped
    // ObjString* b = AS_STRING(pop());
    // ObjString* a = AS_STRING(pop());
    ObjString* b = AS_STRING(peek(0));
    ObjString* a = AS_STRING(peek(1));

    int length = a->length + b->length;
    char* chars = ALLOCATE(char, length + 1);
    memcpy(chars, a->chars, a->length);
    memcpy(chars + a->length, b->chars, b->length);
    chars[length] = '\0';

    ObjString* result = takeString(chars, length);
    pop();
    pop();
    push(OBJ_VAL(result));
}
