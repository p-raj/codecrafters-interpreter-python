#include "compiler.h"

#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "chunk.h"
#include "common.h"
#include "object.h"
#include "scanner.h"
#include "value.h"

#ifdef DEBUG_PRINT_CODE
#include "debug.h"
#endif

typedef struct {
    Token current;
    Token previous;
    bool hadError;
    //  Panic mode ends when the parser reaches a synchronization point. For Lox, we chose statement
    //  boundaries, so when we later add those to our compiler, we’ll clear the flag there.
    bool panicMode;
} Parser;

// If we call parsePrecedence(PREC_ASSIGNMENT), then it will parse the entire expression because +
// has higher precedence than assignment.
// If instead we call parsePrecedence(PREC_UNARY), it will compile the -a.b and stop there. It
// doesn’t keep going through the + because the addition has lower precedence than unary operators.
// GOES TOP -> BOTTOM and not vice-versa.
typedef enum {
    PREC_NONE,
    PREC_ASSIGNMENT,  // =
    PREC_OR,          // or
    PREC_AND,         // and
    PREC_EQUALITY,    // == !=
    PREC_COMPARISON,  // < > <= >=
    PREC_TERM,        // + -
    PREC_FACTOR,      // * /
    PREC_UNARY,       // ! -
    PREC_CALL,        // . ()
    PREC_PRIMARY
} Precedence;

typedef void (*ParseFn)(bool canAssign);

typedef struct {
    // the function to compile a prefix expression starting with a token type,
    ParseFn prefix;
    // the function to compile an infix expression whose left operand is followed by a token type
    ParseFn infix;
    // the precedence of an infix expression that uses that token as an operator.
    Precedence precedence;
} ParseRule;

typedef struct {
    // When we’re resolving an identifier, we compare the identifier’s lexeme with each local’s
    // name to find a match.
    Token name;
    // records the scope depth of the block where the local variable was declared.
    int depth;
    // The compiler already emits an OP_POP instruction when a local variable goes out of scope. If
    // a variable is captured by a closure, we will instead emit a different instruction to hoist
    // that variable out of the stack and into its corresponding upvalue. To do that, the compiler
    // needs to know which locals are closed over.
    bool isCaptured;

} Local;

typedef struct {
    uint8_t index;
    //  Then, when the declaration of inner() executes, its closure grabs the upvalue from the
    //  ObjClosure for middle() that captured x. A function captures—either a local or upvalue—
    // upvalue chaining is possible
    bool isLocal;
} Upvalue;

typedef enum { TYPE_FUNCTION, TYPE_SCRIPT } FunctionType;

typedef struct Compiler {
    // Functions nest by default
    // any function declared would nest under the global "main" function
    // functions behave like stack
    // Each Compiler points back to the Compiler for the function that encloses it, all the way
    // back to the root Compiler for the top-level code.
    struct Compiler* enclosing;

    // HACK: kind of like a main() function
    // there is an implicit top-level function.
    // . It’s as if the entire program is wrapped inside an implicit main() function.
    // Every place in the compiler that was writing to the Chunk now needs to go through that
    // function pointer --> Change how the currentChunk() works and is used
    ObjFunction* function;
    FunctionType type;

    // flat array of all locals that are in scope during each point in the compilation process.
    // ordered in the array in the order that their declarations appear in the code.
    // 1. Since the instruction operand we’ll use to encode a local is a single byte
    // When your compiler translates a local variable access (like reading x), it emits a bytecode
    // instruction followed by an operand that tells the VM which stack slot to look in. For
    // example:OP_GET_LOCAL [slot_index]
    // The author decided to make this slot_index operand exactly 1
    // byte  bits wide. This keeps instructions small, memory usage low, and execution
    // fast.
    // 2. VM has a hard limit on the number of locals that can be in scope at
    // once. Because a single byte can only hold a binary value from 00000000 to 11111111, the
    // maximum number of unique integers it can represent is [2^8 = 256 (values 0 through 255)].As a
    // result, your VM cannot physically address more than 256 local variables simultaneously in the
    // same scope. If a user tries to declare a 257th local variable, a 1-byte operand has no way to
    // point to slot 256.
    Local locals[UINT8_COUNT];
    // tracks how many locals are in scope—how many of those array slots are in use.
    int localCount;
    // for tracking closure captured values
    Upvalue upvalues[UINT8_COUNT];
    // This is the number of blocks surrounding the current bit of code we’re compiling.
    // Zero is the global scope, one is the first top-level block, two is inside that...
    int scopeDepth;
} Compiler;

Parser parser;
Compiler* current = NULL;
Chunk* compilingChunk;

static Chunk* currentChunk() {
    return &current->function->chunk;
    // return compilingChunk;
}

static void errorAt(Token* token, const char* message) {
    // keep compiling, but stop complaining
    if (parser.panicMode) return;
    parser.panicMode = true;
    fprintf(stderr, "[line %d] Error", token->line);

    if (token->type == TOKEN_EOF) {
        fprintf(stderr, " at the end");
    } else if (token->type == TOKEN_ERROR) {
        // pass
    } else {
        fprintf(stderr, " at '%.*s'", token->length, token->start);
    }

    fprintf(stderr, ": %s\n", message);
    parser.hadError = true;
}
static void error(const char* message) { errorAt(&parser.current, message); }
static void errorAtCurrent(const char* message) { errorAt(&parser.current, message); }

static void advance() {
    // It asks the scanner for the next token and stores it for later use.
    parser.previous = parser.current;

    for (;;) {
        // The code to read the next token is wrapped in a loop. Remember, clox’s scanner
        // doesn’t report lexical errors. Instead, it creates special error tokens and leaves it
        // up to the parser to report them. We do that here.
        parser.current = scanToken();
        if (parser.current.type != TOKEN_ERROR) break;

        errorAtCurrent(parser.current.start);
    }
}

static void consume(TokenType type, const char* message) {
    if (parser.current.type == type) {
        advance();
        return;
    }
    errorAtCurrent(message);
}

static bool check(TokenType type) { return parser.current.type == type; }

static bool match(TokenType type) {
    if (!check(type)) return false;
    advance();
    return true;
}

// After we parse and understand a piece of the user’s program, the next step is to translate that
// to a series of bytecode instructions. It starts with the easiest possible step: appending a
// single byte to the chunk.
static void emitByte(uint8_t byte) { writeChunk(currentChunk(), byte, parser.previous.line); }

static void emitBytes(uint8_t byte1, uint8_t byte2) {
    emitByte(byte1);
    emitByte(byte2);
}

static void emitLoop(int loopStart) {
    emitByte(OP_LOOP);
    int offset = currentChunk()->count - loopStart + 2;
    if (offset > UINT16_MAX) error("Loop body too large");
    emitByte((offset >> 8) & 0xff);
    emitByte(offset & 0xff);
}

static int emitJump(uint8_t instruction) {
    // The first emits a bytecode instruction and writes a placeholder operand for the jump offset.
    emitByte(instruction);
    // We use two bytes for the jump offset operand. A 16-bit offset lets us jump over up to 65,535
    // bytes of code, which should be plenty for our needs.
    emitByte(0XFF);
    emitByte(0XFF);
    return currentChunk()->count - 2;
}

static void emitReturn() {
    // Note that we assume here that the function did actually return a value
    // but thats not always the case
    // so the implicit return is NIL VALUE
    emitByte(OP_NIL);
    emitByte(OP_RETURN);
}

static uint8_t makeConstant(Value value) {
    int constant = addConstant(currentChunk(), value);
    if (constant > UINT8_MAX) {
        error("Too many constants in one chunk.");
        return 0;
    }
    return (uint8_t)constant;
}

static void emitConstant(Value value) { emitBytes(OP_CONSTANT, makeConstant(value)); }

static void patchJump(int offset) {
    int jump = currentChunk()->count - offset - 2;
    if (jump > UINT16_MAX) {
        error("Too much code to jump over.");
    }
    currentChunk()->code[offset] = (jump >> 8) & 0XFF;
    currentChunk()->code[offset + 1] = jump & 0XFF;
}

static void initCompiler(Compiler* compiler, FunctionType type) {
    compiler->enclosing = current;
    compiler->function = NULL;
    compiler->type = type;
    compiler->localCount = 0;
    compiler->scopeDepth = 0;
    compiler->function = newFunction();
    current = compiler;

    if (type != TYPE_SCRIPT) {
        current->function->name = copyString(parser.previous.start, parser.previous.length);
    }

    // Remember that the compiler’s locals array keeps track of which stack slots are associated
    // with which local variables or temporaries. From now on, the compiler implicitly claims stack
    // slot zero for the VM’s own internal use. We give it an empty name so that the user can’t
    // write an identifier that refers to it.
    Local* local = &current->locals[current->localCount++];
    local->depth = 0;
    local->isCaptured = false;
    local->name.start = "";
    local->name.length = 0;
}

static ObjFunction* endCompiler() {
    emitReturn();
    ObjFunction* function = current->function;

#ifdef DEBUG_PRINT_CODE
    if (!parser.hadError) {
        disassembleChunk(currentChunk(),
                         function->name != NULL ? function->name->chars : "<script>");
    }
#endif
    // pop back to the enclosing compiler
    current = current->enclosing;
    return function;
}

static void beginScope() { current->scopeDepth++; }
static void endScope() {
    current->scopeDepth--;
    // Discard local variables
    while (current->localCount > 0 &&
           current->locals[current->localCount - 1].depth > current->scopeDepth) {
        if (current->locals[current->localCount - 1].isCaptured) {
            emitByte(OP_CLOSE_UPVALUE);
        } else {
            emitByte(OP_POP);
        }
        current->localCount--;
    }
}

// forward declarations
static void expression();
static void block();
static void statement();
static void declaration();
static void funDeclaration();
static void varDeclaration();
static ParseRule* getRule(TokenType type);
static void parsePrecedence(Precedence precedence);

// Global variables are looked up by name at runtime. That means the VM—the bytecode interpreter
// loop—needs access to the name. A whole string is too big to stuff into the bytecode stream as an
// operand. Instead, we store the string in the constant table and the instruction then refers to
// the name by its index in the table.
static uint8_t identifierConstant(Token* name) {
    // return the index of the global VAR;
    return makeConstant(OBJ_VAL(copyString(name->start, name->length)));
}

static bool identifiersEqual(Token* a, Token* b) {
    if (a->length == b->length) {
        return memcmp(a->start, b->start, a->length) == 0;
    }
    return false;
}

static int resolveLocal(Compiler* compiler, Token* name) {
    for (int i = compiler->localCount - 1; i >= 0; i--) {
        Local* local = &compiler->locals[i];
        // We walk the array backward so that we find the last declared variable with the
        // identifier. That ensures that inner local variables correctly shadow locals with the same
        // name in surrounding scopes.
        if (identifiersEqual(name, &local->name)) {
            // When we resolve a reference to a local variable, we check the scope depth to see if
            // it’s fully defined.
            if (local->depth == -1) {
                error("Can't read local variable in its own initializer.");
            }
            return i;
        }
    }
    return -1;
}

static int addUpvalue(Compiler* compiler, uint8_t index, bool isLocal) {
    int upvalueCount = compiler->function->upvalueCount;
    // A closure may reference the same variable in a surrounding function multiple times
    for (int i = 0; i < upvalueCount; i++) {
        Upvalue* upvalue = &compiler->upvalues[i];
        if (upvalue->index == index && upvalue->isLocal == isLocal) {
            return i;
        }
    }
    // we can only store a limited number of values
    // the restriction put in by the 2bytecode instruction set that we have
    if (upvalueCount == UINT8_COUNT) {
        error("Too many closure variables in function.");
        return 0;
    }
    compiler->upvalues[upvalueCount].isLocal = isLocal;
    // The index field tracks the closed-over local variable’s slot index. That way the compiler
    // knows which variable in the enclosing function needs to be captured.
    compiler->upvalues[upvalueCount].index = index;
    return compiler->function->upvalueCount++;
}

static int resolveUpvalue(Compiler* compiler, Token* name) {
    // Global case
    if (compiler->enclosing == NULL) return -1;
    int local = resolveLocal(compiler->enclosing, name);
    if (local != -1) {
        // When resolving an identifier, if we end up creating an upvalue for a local variable, we
        // mark it as captured.
        // Why this matters at runtime
        // When the outer function finishes executing and is about to pop its local variables off
        // the stack, it checks each local's isCaptured flag:
        // If isCaptured is false, the compiler emits a cheap OP_POP instruction to discard the
        // variable.
        // If isCaptured is true, the compiler emits an OP_CLOSE_UPVALUE instruction instead. This
        // tells the VM at runtime to move that variable off the stack and onto the heap so the
        // closure can keep accessing it.
        compiler->enclosing->locals[local].isCaptured = true;
        return addUpvalue(compiler, (uint8_t)local, true);
    }
    // Most recursive functions either do all their work before the recursive call (a pre-order
    // traversal, or “on the way down”), or they do all the work after the recursive call (a
    // post-order traversal, or “on the way back up”). This function does both. The recursive call
    // is right in the middle.
    int upvalue = resolveUpvalue(compiler->enclosing, name);
    if (upvalue != -1) {
        return addUpvalue(compiler, (uint8_t)upvalue, false);
    }
    return -1;
}

static void addLocal(Token name) {
    if (current->localCount == UINT8_COUNT) {
        error("Too many local variables in function.");
        return;
    }
    Local* local = &current->locals[current->localCount++];
    local->name = name;
    // local->depth = current->scopeDepth;
    /**
     * handle the case below
     * {
       var a = "outer";
       {
         var a = a;
       }
     }
     */
    // -1 means uninitialized
    local->depth = -1;
    local->isCaptured = false;
}

static void declareVariable() {
    // 0 means global
    if (current->scopeDepth == 0) return;

    Token* name = &parser.previous;
    /**
     * Shadowing is an ERROR in LOX
     * {
         var a = "first";
         var a = "second";
     }
     */
    for (int i = current->localCount - 1; i >= 0; i--) {
        Local* local = &current->locals[i];
        /**
         * This is fine
         * {
           var a = "outer";
           {
             var a = "inner";
           }
         }
         */
        if (local->depth != -1 && local->depth < current->scopeDepth) {
            break;
        }
        if (identifiersEqual(name, &local->name)) {
            error("Already a variable with this name in this scope.");
        }
    }
    addLocal(*name);
}

static uint8_t parseVariable(const char* errorMessage) {
    consume(TOKEN_IDENTIFIER, errorMessage);
    // Adding support for local-variables
    declareVariable();
    // exit the function if we’re in a local scope. At runtime, locals aren’t looked up by name.
    // There’s no need to stuff the variable’s name into the constant table, so if the declaration
    // is inside a local scope, we return a dummy table index instead.
    if (current->scopeDepth > 0) return 0;
    return identifierConstant(&parser.previous);
}

static void markInitialized() {
    // Before, we called markInitialized() only when we already knew we were in a local scope. Now,
    // a top-level function declaration will also call this function. When that happens, there is no
    // local variable to mark initialized—the function is bound to a global variable.
    if (current->scopeDepth == 0) return;
    current->locals[current->localCount - 1].depth = current->scopeDepth;
}

static void defineVariable(uint8_t global) {
    // exit the function if we’re in a local scope. At runtime, locals aren’t looked up by name.
    // There’s no need to stuff the variable’s name into the constant table, so if the declaration
    // is inside a local scope, we return a dummy table index instead.
    // It has already executed the code for the variable’s initializer (or the implicit nil if the
    // user omitted an initializer), and that value is sitting right on top of the stack as the only
    // remaining temporary.
    // We also know that new locals are allocated at the top of the stack, right where that
    // value already is.
    if (current->scopeDepth > 0) {
        // move the local var depth from -1 => current depth
        markInitialized();
        return;
    }
    emitBytes(OP_DEFINE_GLOBAL, global);
}

static uint8_t argumentList() {
    uint8_t argCount = 0;
    if (!check(TOKEN_RIGHT_PAREN)) {
        do {
            expression();
            if (argCount == 255) {
                error("Can't have more than 255 arguments.");
            }
            argCount++;
        } while (match(TOKEN_COMMA));
    }
    consume(TOKEN_RIGHT_PAREN, "Expect ')' after arguments.");
    return argCount;
}

static void and_(bool canAssign) {
    int endJump = emitJump(OP_JUMP_IF_FALSE);
    emitByte(OP_POP);
    parsePrecedence(PREC_AND);
    patchJump(endJump);
}

static void grouping(bool canAssign) {
    expression();
    consume(TOKEN_RIGHT_PAREN, "Expect ')' after expression.");
}

// We define a function for each expression that outputs the appropriate bytecode.
// Then we build an array of function pointers. The indexes in the array correspond to the TokenType
// enum values, and the function at each index is the code to compile an expression of that token
// type.
// To compile number literals, we store a pointer to the following function at the TOKEN_NUMBER
// index in the array.
static void number(bool canAssign) {
    // The strtod function is a built-in utility in the C and C++ standard libraries used to convert
    // a character string into a double-precision floating-point number
    double value = strtod(parser.previous.start, NULL);
    emitConstant(NUMBER_VAL(value));
}

static void or_(bool canAssign) {
    int elseJump = emitJump(OP_JUMP_IF_FALSE);
    int endJump = emitJump(OP_JUMP);

    patchJump(elseJump);
    emitByte(OP_POP);

    parsePrecedence(PREC_OR);
    patchJump(endJump);
}

// The + 1 and - 2 parts trim the leading and trailing quotation marks.
// If Lox supported string escape sequences like \n, we’d translate those here. Since it
// doesn’t, we can take the characters as they are.
static void string(bool canAssign) {
    emitConstant(OBJ_VAL(copyString(parser.previous.start + 1, parser.previous.length - 2)));
}

static void namedVariable(Token name, bool canAssign) {
    uint8_t getOp, setOp;

    int arg = resolveLocal(current, &name);
    if (arg != -1) {
        getOp = OP_GET_LOCAL;
        setOp = OP_SET_LOCAL;
    }
    // before simply ignoring the enclosing functions
    // and jumping directly to assuming that variables were declared globally
    // we try to resolve variables in the enclosing functions now
    else if ((arg = resolveUpvalue(current, &name)) != -1) {
        getOp = OP_GET_UPVALUE;
        setOp = OP_SET_UPVALUE;
    } else {
        arg = identifierConstant(&name);
        getOp = OP_GET_GLOBAL;
        setOp = OP_SET_GLOBAL;
    }

    if (canAssign && match(TOKEN_EQUAL)) {
        expression();
        emitBytes(setOp, (uint8_t)arg);
    } else {
        emitBytes(getOp, (uint8_t)arg);
    }
}

static void variable(bool canAssign) { namedVariable(parser.previous, canAssign); }

static void unary(bool canAssign) {
    TokenType operatorType = parser.previous.type;

    // Compile the operand.
    // expression();
    parsePrecedence(PREC_UNARY);

    // appears on the left, but think about it in terms of order of execution:
    // We evaluate the operand first which leaves its value on the stack.
    // Then we pop that value, negate it, and push the result.
    // So the OP_NEGATE instruction should be emitted last. This is part of the compiler’s
    // job—parsing the program in the order it appears in the source code and rearranging it into
    // the order that execution happens.
    switch (operatorType) {
        case TOKEN_BANG:
            emitByte(OP_NOT);
            break;
        case TOKEN_MINUS:
            emitByte(OP_NEGATE);
            break;
        default:
            return;
    }
}

// Binary operators are different from the previous expressions because they are infix.
// With infix expressions, we don’t know we’re in the middle of a binary operator until after we’ve
// parsed its left operand and then stumbled onto the operator token in the middle.
// eg:  1 + 2
// 1.> We call expression(). That in turn calls parsePrecedence(PREC_ASSIGNMENT).
// 2.> That function (once we implement it) sees the leading number token and recognizes it is
// parsing a number literal. 3.> It hands off control to number().
// 4.>number() creates a constant, emits an OP_CONSTANT, and returns back to parsePrecedence().
// Now that we’ve compiled the leading number expression, the next token is +. That’s the exact
// token that parsePrecedence() needs to detect that we’re in the middle of an infix expression and
// to realize that the expression we already compiled is actually an operand to that.
static void binary(bool canAssign) {
    TokenType operatorType = parser.previous.type;
    // We use {{one higher level of precedence}} for the right operand because the binary operators
    // are {{ left-associative }}. Given a series of the same operator, like:
    // 1 + 2 + 3 + 4 --> We want to parse it like --> ((1 + 2) + 3) + 4
    ParseRule* rule = getRule(operatorType);
    parsePrecedence((Precedence)(rule->precedence + 1));

    // The fact that the left operand gets compiled first works out fine. It means at runtime, that
    // code gets executed first. When it runs, the value it produces will end up on the stack.
    // That’s right where the infix operator is going to need it.
    // When run, the VM will execute the left and right operand code, in that order, leaving their
    // values on the stack. Then it executes the instruction for the operator. That pops the two
    // values, computes the operation, and pushes the result.
    switch (operatorType) {
        // The expression a != b has the same semantics as !(a == b), so the compiler is free to
        // compile the former as if it were the latter. Instead of a dedicated OP_NOT_EQUAL
        // instruction, it can output an OP_EQUAL followed by an OP_NOT. Likewise, a <= b is the
        // same as !(a > b) and a >= b is !(a < b). Thus, we only need three new instructions.
        case TOKEN_BANG_EQUAL:
            emitBytes(OP_EQUAL, OP_NOT);
            break;
        case TOKEN_EQUAL_EQUAL:
            emitByte(OP_EQUAL);
            break;
        case TOKEN_GREATER:
            emitByte(OP_GREATER);
            break;
        case TOKEN_GREATER_EQUAL:
            emitBytes(OP_LESS, OP_NOT);
            break;
        case TOKEN_LESS:
            emitByte(OP_LESS);
            break;
        case TOKEN_LESS_EQUAL:
            emitBytes(OP_GREATER, OP_NOT);
            break;
        case TOKEN_PLUS:
            emitByte(OP_ADD);
            break;
        case TOKEN_MINUS:
            emitByte(OP_SUBTRACT);
            break;
        case TOKEN_STAR:
            emitByte(OP_MULTIPLY);
            break;
        case TOKEN_SLASH:
            emitByte(OP_DIVIDE);
            break;
        default:
            return;  // Unreachable.
    }
}

static void call(bool canAssign) {
    uint8_t argCount = argumentList();
    emitBytes(OP_CALL, argCount);
}

static void literal(bool canAssign) {
    switch (parser.previous.type) {
        case TOKEN_FALSE:
            emitByte(OP_FALSE);
            break;
        case TOKEN_NIL:
            emitByte(OP_NIL);
            break;
        case TOKEN_TRUE:
            emitByte(OP_TRUE);
            break;
        default:
            return;  // Unreachable.
    }
}

// clang-format off
ParseRule rules[] = {
  [TOKEN_LEFT_PAREN]    = {grouping, call,   PREC_CALL},
  [TOKEN_RIGHT_PAREN]   = {NULL,     NULL,   PREC_NONE},
  [TOKEN_LEFT_BRACE]    = {NULL,     NULL,   PREC_NONE},
  [TOKEN_RIGHT_BRACE]   = {NULL,     NULL,   PREC_NONE},
  [TOKEN_COMMA]         = {NULL,     NULL,   PREC_NONE},
  [TOKEN_DOT]           = {NULL,     NULL,   PREC_NONE},
  [TOKEN_MINUS]         = {unary,    binary, PREC_TERM},
  [TOKEN_PLUS]          = {NULL,     binary, PREC_TERM},
  [TOKEN_SEMICOLON]     = {NULL,     NULL,   PREC_NONE},
  [TOKEN_SLASH]         = {NULL,     binary, PREC_FACTOR},
  [TOKEN_STAR]          = {NULL,     binary, PREC_FACTOR},
  [TOKEN_BANG]          = {unary,     NULL,   PREC_NONE},
  [TOKEN_BANG_EQUAL]    = {NULL,     binary,   PREC_EQUALITY},
  [TOKEN_EQUAL]         = {NULL,     NULL,   PREC_NONE},
  [TOKEN_EQUAL_EQUAL]   = {NULL,     binary, PREC_EQUALITY},
  [TOKEN_GREATER]       = {NULL,     binary, PREC_COMPARISON},
  [TOKEN_GREATER_EQUAL] = {NULL,     binary, PREC_COMPARISON},
  [TOKEN_LESS]          = {NULL,     binary, PREC_COMPARISON},
  [TOKEN_LESS_EQUAL]    = {NULL,     binary, PREC_COMPARISON},
  [TOKEN_IDENTIFIER]    = {variable,     NULL,   PREC_NONE},
  [TOKEN_STRING]        = {string,     NULL,   PREC_NONE},
  [TOKEN_NUMBER]        = {number,   NULL,   PREC_NONE},
  [TOKEN_AND]           = {NULL,     and_,   PREC_AND},
  [TOKEN_CLASS]         = {NULL,     NULL,   PREC_NONE},
  [TOKEN_ELSE]          = {NULL,     NULL,   PREC_NONE},
  [TOKEN_FALSE]         = {literal,     NULL,   PREC_NONE},
  [TOKEN_FOR]           = {NULL,     NULL,   PREC_NONE},
  [TOKEN_FUN]           = {NULL,     NULL,   PREC_NONE},
  [TOKEN_IF]            = {NULL,     NULL,   PREC_NONE},
  [TOKEN_NIL]           = {literal,     NULL,   PREC_NONE},
  [TOKEN_OR]            = {NULL,     or_,   PREC_OR},
  [TOKEN_PRINT]         = {NULL,     NULL,   PREC_NONE},
  [TOKEN_RETURN]        = {NULL,     NULL,   PREC_NONE},
  [TOKEN_SUPER]         = {NULL,     NULL,   PREC_NONE},
  [TOKEN_THIS]          = {NULL,     NULL,   PREC_NONE},
  [TOKEN_TRUE]          = {literal,     NULL,   PREC_NONE},
  [TOKEN_VAR]           = {NULL,     NULL,   PREC_NONE},
  [TOKEN_WHILE]         = {NULL,     NULL,   PREC_NONE},
  [TOKEN_ERROR]         = {NULL,     NULL,   PREC_NONE},
  [TOKEN_EOF]           = {NULL,     NULL,   PREC_NONE},
};
// clang-format on

// The parsing functions like number() and unary() here in clox are different. Each only parses
// exactly one type of expression.
// This function—once we implement it—starts at the current token and parses any expression at the
// given precedence level or higher.
static void parsePrecedence(Precedence precedence) {
    advance();
    // At the beginning of parsePrecedence(), we look up a prefix parser for the current token.
    // The first token is always going to belong to some kind of prefix expression, by definition.
    //  It may turn out to be nested as an operand inside one or more infix expressions, but as you
    //  read the code from left to right, the first token you hit always belongs to a prefix
    //  expression.
    ParseFn prefixRule = getRule(parser.previous.type)->prefix;
    if (prefixRule == NULL) {
        error("Expect expression.");
        return;
    }

    bool canAssign = precedence <= PREC_ASSIGNMENT;
    prefixRule(canAssign);

    while (precedence <= getRule(parser.current.type)->precedence) {
        advance();
        ParseFn infixRule = getRule(parser.previous.type)->infix;
        infixRule(canAssign);
    }

    if (canAssign && match(TOKEN_EQUAL)) {
        error("Invalid assignment target.");
    }
}

static ParseRule* getRule(TokenType type) { return &rules[type]; }

static void expression() { parsePrecedence(PREC_ASSIGNMENT); }

static void varDeclaration() {
    uint8_t global = parseVariable("Expect variable name");
    if (match(TOKEN_EQUAL)) {
        expression();
    } else {
        // desugaring of declaration
        // var a;
        // -->
        // var a = nil;
        emitByte(OP_NIL);
    }
    consume(TOKEN_SEMICOLON, "Expect ';' after variable declaration.");
    defineVariable(global);
}

static void expressionStatement() {
    // An “expression statement” is simply an expression followed by a semicolon. They’re how you
    // write an expression in a context where a statement is expected. Usually, it’s so that you can
    // call a function or evaluate an assignment for its side effect, like this:
    expression();
    consume(TOKEN_SEMICOLON, "Expect ';' after value.");
    emitByte(OP_POP);
}

static void forStatement() {
    beginScope();
    consume(TOKEN_LEFT_PAREN, "Expect '(' after 'for'.");
    // consume(TOKEN_SEMICOLON, "Expect ';'."); -> INITIALIZER
    if (match(TOKEN_SEMICOLON)) {
        // no initializer
    } else if (match(TOKEN_VAR)) {
        varDeclaration();
    } else {
        expressionStatement();
    }
    // We don’t want the initializer to leave anything on the stack.

    // here is the expression we need to evaluate multiple times
    int loopStart = currentChunk()->count;
    int exitJump = -1;
    // this isnt an infinite loop
    // like (for int i; <condition empty> ; i+=1)
    // consume(TOKEN_SEMICOLON, "Expect ';'."); -> CONDITION
    if (!match(TOKEN_SEMICOLON)) {
        expression();
        consume(TOKEN_SEMICOLON, "Expect ';' after loop condition.");
        // Jump out of the loop if the condition is false.
        exitJump = emitJump(OP_JUMP_IF_FALSE);
        emitByte(OP_POP);  // Condition.
    }

    // the increment clause. It’s pretty convoluted. It appears
    // textually before the body, but executes after it. If we parsed to an AST and generated code
    // in a separate pass, we could simply traverse into and compile the for statement AST’s body
    // field before its increment clause.
    // , since our compiler only makes a single pass over the code. Instead, we’ll jump over the
    // increment, run the body, jump back up to the increment, run it, and then go to the next
    // iteration.
    if (!match(TOKEN_RIGHT_PAREN)) {
        int bodyJump = emitJump(OP_JUMP);
        int incrementStart = currentChunk()->count;
        expression();
        emitByte(OP_POP);
        consume(TOKEN_RIGHT_PAREN, "Expect ')' after for clauses.");
        emitLoop(loopStart);
        loopStart = incrementStart;
        patchJump(bodyJump);
    }

    consume(TOKEN_RIGHT_PAREN, "Expect ')' after for clauses.");

    statement();
    emitLoop(loopStart);
    if (exitJump != -1) {
        patchJump(exitJump);
        emitByte(OP_POP);
    }
    endScope();
}

static void ifStatement() {
    consume(TOKEN_LEFT_PAREN, "Expect '(' after 'if'.");
    expression();
    consume(TOKEN_RIGHT_PAREN, "Expect ')' after 'if'.");

    int thenJump = emitJump(OP_JUMP_IF_FALSE);
    // The setup on the stack
    // 1> Evaluation: When the if statement begins, the compiler runs expression(). At runtime, this
    // evaluates your condition (e.g., x > 5) and pushes either [true or false] onto the top of the
    // stack.
    // 2> The jump check: Next, OP_JUMP_IF_FALSE looks at that top value to decide whether it needs
    // to skip the code block. As noted in the text, OP_JUMP_IF_FALSE intentionally does not pop the
    // value because the VM wants to reuse that exact same instruction later for short-circuiting
    // logical operators (like and and or).
    // 3> The leftover value: Because the jump instruction left it behind, the condition value is
    // still sitting on top of the stack when the VM enters the then branch.

    // to clear up the TRUE value on the stack
    emitByte(OP_POP);
    statement();

    // we have to have the else jumps as well because if the <if> branch is taken
    // we once that branch is done, we have to skip over <else> branch and continue
    // from a new location
    int elseJump = emitJump(OP_JUMP);

    patchJump(thenJump);
    // to clear up the FALSE value on the stack
    // lands here on OP_JUMP_IF_FALSE
    emitByte(OP_POP);

    // Adding support for else branch
    if (match(TOKEN_ELSE)) {
        statement();
    }
    // After executing the then branch, this jumps to the next statement after the else branch.
    // Unlike the other jump, this jump is unconditional.
    patchJump(elseJump);
}

static void printStatement() {
    expression();
    consume(TOKEN_SEMICOLON, "Expect ';' after value.");
    emitByte(OP_PRINT);
}

static void returnStatement() {
    if (current->type == TYPE_SCRIPT) {
        // This is one of the reasons we added that FunctionType enum to the compiler.
        error("Can't return from top-level code.");
    }
    if (match(TOKEN_SEMICOLON)) {
        // this sets up the NIL value on the stack
        emitReturn();
    } else {
        // The return value expression is optional, so the parser looks for a semicolon token to
        // tell if a value was provided. If there is no return value, the statement implicitly
        // returns nil. We implement that by calling emitReturn(), which emits an OP_NIL
        // instruction. Otherwise, we compile the return value expression and return it with an
        // OP_RETURN instruction.
        expression();
        consume(TOKEN_SEMICOLON, "Expect ';' after return value.");
        emitByte(OP_RETURN);
    }
}

static void whileStatement() {
    int loopStart = currentChunk()->count;
    consume(TOKEN_LEFT_PAREN, "Expect '(' after 'while'.");
    expression();
    consume(TOKEN_RIGHT_PAREN, "Expect ')' after condition.");

    int exitJump = emitJump(OP_JUMP_IF_FALSE);
    emitByte(OP_POP);
    statement();
    // once statement is done
    // we might want to loop back
    emitLoop(loopStart);

    patchJump(exitJump);
    emitByte(OP_POP);
}

// If we hit a compile error while parsing the previous statement, we enter panic mode. When that
// happens, after the statement we start synchronizing.
static void synchronize() {
    parser.panicMode = false;
    // We skip tokens indiscriminately until we reach something that looks like a statement
    // boundary. We recognize the boundary by looking for a preceding token that can end a
    // statement, like a semicolon. Or we’ll look for a subsequent token that begins a statement,
    // usually one of the control flow or declaration keywords.
    while (parser.current.type != TOKEN_EOF) {
        if (parser.previous.type == TOKEN_SEMICOLON) return;
        switch (parser.current.type) {
            case TOKEN_CLASS:
            case TOKEN_FUN:
            case TOKEN_VAR:
            case TOKEN_FOR:
            case TOKEN_IF:
            case TOKEN_WHILE:
            case TOKEN_PRINT:
            case TOKEN_RETURN:
                return;
            default:;  // Do nothing.
        }
        advance();
    }
}

// # GRAMMAR
// statement        → exprStmt
//                  | printStmt
//                  | block
//
// block            -> "{" declaration* "}"
//
// declaration      → varDecl
//                  | statement

static void declaration() {
    if (match(TOKEN_FUN)) {
        funDeclaration();
    } else if (match(TOKEN_VAR)) {
        varDeclaration();
    } else {
        statement();
    }
    if (parser.panicMode) synchronize();
}

static void block() {
    while (!check(TOKEN_RIGHT_BRACE) && !check(TOKEN_EOF)) {
        declaration();
    }
    consume(TOKEN_RIGHT_BRACE, "Expect '}' after block");
}

static void function(FunctionType type) {
    Compiler compiler;
    // [TRICK] sets the "current compiler" to this function
    // Then, as we compile the body, all of the functions that emit bytecode write to the chunk
    // owned by the new Compiler’s function.
    initCompiler(&compiler, type);
    beginScope();

    consume(TOKEN_LEFT_PAREN, "Expect '(' after function name.");
    // paramters
    if (!check(TOKEN_RIGHT_PAREN)) {
        do {
            current->function->arity++;
            if (current->function->arity > 255) {
                errorAtCurrent("Can't have more than 255 parameters.");
            }
            uint8_t constant = parseVariable("Expect parameter name.");
            defineVariable(constant);
        } while (match(TOKEN_COMMA));
    }
    consume(TOKEN_RIGHT_PAREN, "Expect ')' after parameters.");
    consume(TOKEN_LEFT_BRACE, "Expect '{' before function body.");
    block();

    // compiler yields the newly compiled function object,
    ObjFunction* function = endCompiler();
    // which we store as a constant in the
    // surrounding function’s constant table.
    // emitBytes(OP_CONSTANT, makeConstant(OBJ_VAL(function)));
    // Introduce: Closures
    emitBytes(OP_CLOSURE, makeConstant(OBJ_VAL(function)));

    // VM and Compiler work together here to make sure\
    // the closure captured varaibles live long enough
    for (int i = 0; i < function->upvalueCount; i++) {
        emitByte(compiler.upvalues[i].isLocal ? 1 : 0);
        emitByte(compiler.upvalues[i].index);
    }
}

static void funDeclaration() {
    //  A function declaration at the top level will bind the function to a global variable. Inside
    //  a block or other function, a function declaration creates a local variable.
    uint8_t global = parseVariable("Expect function name");
    // It’s safe for a function to refer to its own name
    // inside its body. You can’t call the function and execute the body until after it’s fully
    // defined, so you’ll never see the variable in an uninitialized state. Practically speaking,
    // it’s useful to allow this in order to support recursive local functions.
    markInitialized();
    function(TYPE_FUNCTION);
    defineVariable(global);
}

static void statement() {
    if (match(TOKEN_PRINT)) {
        printStatement();
    } else if (match(TOKEN_FOR)) {
        forStatement();
    } else if (match(TOKEN_IF)) {
        ifStatement();
    } else if (match(TOKEN_RETURN)) {
        returnStatement();
    } else if (match(TOKEN_WHILE)) {
        whileStatement();
    }
    // Blocks are a kind of statement, so the rule for them goes in the statement production.
    else if (match(TOKEN_LEFT_BRACE)) {
        beginScope();
        block();
        endScope();
    } else {
        expressionStatement();
    }
}

// usually the compilation is a two (a minumum of two) step process
// parser -> generates AST
// code generator -> reads AST -> generates machine code
// for LOX, we will build one pass compiler
ObjFunction* compile(const char* source) {
    initScanner(source);
    Compiler compiler;
    initCompiler(&compiler, TYPE_SCRIPT);
    // compilingChunk = chunk;

    parser.panicMode = false;
    parser.hadError = false;

    // start scanner
    advance();
    // Then we parse a single expression.
    // expression();
    // consume(TOKEN_EOF, "Expect end of expression.");
    // Add support for statements
    while (!match(TOKEN_EOF)) {
        declaration();
    }
    ObjFunction* function = endCompiler();
    // return !(parser.hadError);
    return parser.hadError ? NULL : function;
    /** CHAPTER 16 */
    // here for testing purposes
    // int line = -1;
    // for(;;) {
    //     Token token = scanToken();
    //     if ((token.line) != line) {
    //         printf("%4d ", token.line);
    //         line = token.line;
    //     } else {
    //         printf("\t| ");
    //     }
    //     printf("%2d '%.*s'\n", token.type, token.length, token.start);

    //     if (token.type == TOKEN_EOF) break;
    // }
    // return true;
    /** CHAPTER 16 */
}
