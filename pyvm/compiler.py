"""
compiler.h / compiler.c — the single-pass bytecode compiler for pyvm.

Usually compilation is a two (a minimum of two) step process:
  parser -> generates AST
  code generator -> reads AST -> generates machine code
For Lox, we will build a one-pass compiler.

The compiler is a Pratt (precedence-climbing) parser that directly emits
bytecode.  It handles locals, upvalues/closures, classes, inheritance, control
flow, and more.
"""

from __future__ import annotations

from enum import Enum, auto
from typing import Callable, Optional

from pyvm.chunk import (
    Chunk, OpCode, write_chunk, add_constant,
)
from pyvm.common import UINT8_COUNT, DEBUG_PRINT_CODE
from pyvm.scanner import (
    Token, TokenType, init_scanner, scan_token,
)
from pyvm.value import Value, NUMBER_VAL, OBJ_VAL, BOOL_VAL
from pyvm.object import (
    ObjFunction, ObjString, copy_string,
)


# --------------------------------------------------------------------------- #
# Parser
# --------------------------------------------------------------------------- #

class Parser:
    def __init__(self) -> None:
        self.current: Token = Token(TokenType.TOKEN_EOF, "", 0, 0)
        self.previous: Token = Token(TokenType.TOKEN_EOF, "", 0, 0)
        self.had_error: bool = False
        # Panic mode ends when the parser reaches a synchronization point.  For
        # Lox, we chose statement boundaries, so when we later add those to our
        # compiler, we'll clear the flag there.
        self.panic_mode: bool = False


# --------------------------------------------------------------------------- #
# Precedence
# --------------------------------------------------------------------------- #

# If we call parsePrecedence(PREC_ASSIGNMENT), then it will parse the entire
# expression because + has higher precedence than assignment.
# If instead we call parsePrecedence(PREC_UNARY), it will compile the -a.b and
# stop there.  It doesn't keep going through the + because the addition has
# lower precedence than unary operators.
# GOES TOP -> BOTTOM and not vice-versa.
class Precedence(Enum):
    PREC_NONE = auto()
    PREC_ASSIGNMENT = auto()   # =
    PREC_OR = auto()           # or
    PREC_AND = auto()          # and
    PREC_EQUALITY = auto()     # == !=
    PREC_COMPARISON = auto()   # < > <= >=
    PREC_TERM = auto()         # + -
    PREC_FACTOR = auto()       # * /
    PREC_UNARY = auto()        # ! -
    PREC_CALL = auto()         # . ()
    PREC_PRIMARY = auto()


# --------------------------------------------------------------------------- #
# Local / Upvalue / FunctionType
# --------------------------------------------------------------------------- #

class Local:
    def __init__(self, name: Token, depth: int) -> None:
        # When we're resolving an identifier, we compare the identifier's lexeme
        # with each local's name to find a match.
        self.name: Token = name
        # Records the scope depth of the block where the local variable was
        # declared.
        self.depth: int = depth
        # The compiler already emits an OP_POP instruction when a local variable
        # goes out of scope.  If a variable is captured by a closure, we will
        # instead emit a different instruction to hoist that variable out of the
        # stack and into its corresponding upvalue.  To do that, the compiler
        # needs to know which locals are closed over.
        self.is_captured: bool = False


class Upvalue:
    def __init__(self, index: int, is_local: bool) -> None:
        self.index: int = index
        # Then, when the declaration of inner() executes, its closure grabs the
        # upvalue from the ObjClosure for middle() that captured x.  A function
        # captures—either a local or upvalue—upvalue chaining is possible.
        self.is_local: bool = is_local


class FunctionType(Enum):
    TYPE_FUNCTION = auto()
    TYPE_INITIALIZER = auto()
    TYPE_METHOD = auto()
    TYPE_SCRIPT = auto()


# --------------------------------------------------------------------------- #
# Compiler
# --------------------------------------------------------------------------- #

# Functions nest by default.  Any function declared would nest under the global
# "main" function.  Functions behave like a stack.  Each Compiler points back to
# the Compiler for the function that encloses it, all the way back to the root
# Compiler for the top-level code.
class Compiler:
    def __init__(self, enclosing: Optional["Compiler"], type: FunctionType) -> None:
        self.enclosing: Optional[Compiler] = enclosing
        # HACK: kind of like a main() function.  There is an implicit top-level
        # function.  It's as if the entire program is wrapped inside an implicit
        # main() function.  Every place in the compiler that was writing to the
        # Chunk now needs to go through that function pointer.
        self.function: Optional[ObjFunction] = None
        self.type: FunctionType = type
        # Flat array of all locals that are in scope during each point in the
        # compilation process.  Ordered in the array in the order that their
        # declarations appear in the code.
        #
        # 1. Since the instruction operand we'll use to encode a local is a
        #    single byte.  When your compiler translates a local variable access
        #    (like reading x), it emits a bytecode instruction followed by an
        #    operand that tells the VM which stack slot to look in.  For example:
        #    OP_GET_LOCAL [slot_index].  The author decided to make this
        #    slot_index operand exactly 1 byte (8 bits) wide.  This keeps
        #    instructions small, memory usage low, and execution fast.
        # 2. VM has a hard limit on the number of locals that can be in scope at
        #    once.  Because a single byte can only hold a binary value from
        #    00000000 to 11111111, the maximum number of unique integers it can
        #    represent is [2^8 = 256 (values 0 through 255)].  As a result, your
        #    VM cannot physically address more than 256 local variables
        #    simultaneously in the same scope.
        self.locals: list[Local] = []
        self.local_count: int = 0
        # For tracking closure captured values.
        self.upvalues: list[Upvalue] = []
        # This is the number of blocks surrounding the current bit of code we're
        # compiling.  Zero is the global scope, one is the first top-level block,
        # two is inside that...
        self.scope_depth: int = 0


# Right now we store only a pointer to the ClassCompiler for the enclosing class,
# if any.  Nesting a class declaration inside a method in some other class is an
# uncommon thing to do, but Lox supports it.  Just like the Compiler struct, this
# means ClassCompiler forms a linked list from the current innermost class being
# compiled out through all of the enclosing classes.
class ClassCompiler:
    def __init__(self, enclosing: Optional["ClassCompiler"]) -> None:
        self.enclosing: Optional[ClassCompiler] = enclosing
        self.has_superclass: bool = False


# --------------------------------------------------------------------------- #
# Module-level state (mirrors the C globals)
# --------------------------------------------------------------------------- #

_parser: Parser = Parser()
_current: Optional[Compiler] = None
# Resolving this when Nested or when not inside an instance.
# This module variable points to a struct representing the current, innermost
# class being compiled.
_current_class: Optional[ClassCompiler] = None

# Type alias for parse functions: ParseFn = void (*)(bool canAssign)
ParseFn = Callable[[bool], None]


class ParseRule:
    def __init__(self, prefix: Optional[ParseFn], infix: Optional[ParseFn], precedence: Precedence) -> None:
        # The function to compile a prefix expression starting with a token type.
        self.prefix: Optional[ParseFn] = prefix
        # The function to compile an infix expression whose left operand is
        # followed by a token type.
        self.infix: Optional[ParseFn] = infix
        # The precedence of an infix expression that uses that token as an
        # operator.
        self.precedence: Precedence = precedence


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #

def _current_chunk() -> Chunk:
    """static Chunk* currentChunk()"""
    assert _current is not None and _current.function is not None
    return _current.function.chunk


def _error_at(token: Token, message: str) -> None:
    """static void errorAt(Token* token, const char* message)"""
    # Keep compiling, but stop complaining.
    if _parser.panic_mode:
        return
    _parser.panic_mode = True
    import sys
    print(f"[line {token.line}] Error", end="", file=sys.stderr)

    if token.type is TokenType.TOKEN_EOF:
        print(" at the end", end="", file=sys.stderr)
    elif token.type is TokenType.TOKEN_ERROR:
        pass
    else:
        print(f" at '{token.lexeme}'", end="", file=sys.stderr)

    print(f": {message}", file=sys.stderr)
    _parser.had_error = True


def _error(message: str) -> None:
    """static void error(const char* message)"""
    _error_at(_parser.current, message)


def _error_at_current(message: str) -> None:
    """static void errorAtCurrent(const char* message)"""
    _error_at(_parser.current, message)


def _advance() -> None:
    """static void advance()

    It asks the scanner for the next token and stores it for later use.
    """
    _parser.previous = _parser.current

    while True:
        # The code to read the next token is wrapped in a loop.  Remember,
        # clox's scanner doesn't report lexical errors.  Instead, it creates
        # special error tokens and leaves it up to the parser to report them.
        # We do that here.
        _parser.current = scan_token()
        if _parser.current.type is not TokenType.TOKEN_ERROR:
            break
        _error_at_current(_parser.current.start)


def _consume(type: TokenType, message: str) -> None:
    """static void consume(TokenType type, const char* message)"""
    if _parser.current.type is type:
        _advance()
        return
    _error_at_current(message)


def _check(type: TokenType) -> bool:
    """static bool check(TokenType type)"""
    return _parser.current.type is type


def _match(type: TokenType) -> bool:
    """static bool match(TokenType type)"""
    if not _check(type):
        return False
    _advance()
    return True


# --------------------------------------------------------------------------- #
# Emit helpers
# --------------------------------------------------------------------------- #

# After we parse and understand a piece of the user's program, the next step is
# to translate that to a series of bytecode instructions.  It starts with the
# easiest possible step: appending a single byte to the chunk.
def _emit_byte(byte: int) -> None:
    write_chunk(_current_chunk(), byte, _parser.previous.line)


def _emit_bytes(byte1: int, byte2: int) -> None:
    _emit_byte(byte1)
    _emit_byte(byte2)


def _emit_loop(loop_start: int) -> None:
    """static void emitLoop(int loopStart)"""
    _emit_byte(OpCode.OP_LOOP)
    offset = _current_chunk().count - loop_start + 2
    if offset > 0xFFFF:
        _error("Loop body too large")
    _emit_byte((offset >> 8) & 0xFF)
    _emit_byte(offset & 0xFF)


def _emit_jump(instruction: int) -> int:
    """static int emitJump(uint8_t instruction)"""
    # The first emits a bytecode instruction and writes a placeholder operand
    # for the jump offset.
    _emit_byte(instruction)
    # We use two bytes for the jump offset operand.  A 16-bit offset lets us
    # jump over up to 65,535 bytes of code, which should be plenty for our needs.
    _emit_byte(0xFF)
    _emit_byte(0xFF)
    return _current_chunk().count - 2


def _emit_return() -> None:
    """static void emitReturn()

    Note that we assume here that the function did actually return a value,
    but that's not always the case.  So the implicit return is NIL VALUE.
    """
    if _current is not None and _current.type is FunctionType.TYPE_INITIALIZER:
        _emit_bytes(OpCode.OP_GET_LOCAL, 0)
    else:
        _emit_byte(OpCode.OP_NIL)
    _emit_byte(OpCode.OP_RETURN)


def _make_constant(value: Value) -> int:
    """static uint8_t makeConstant(Value value)"""
    constant = add_constant(_current_chunk(), value)
    if constant > 255:
        _error("Too many constants in one chunk.")
        return 0
    return constant


def _emit_constant(value: Value) -> None:
    """static void emitConstant(Value value)"""
    _emit_bytes(OpCode.OP_CONSTANT, _make_constant(value))


def _patch_jump(offset: int) -> None:
    """static void patchJump(int offset)"""
    jump = _current_chunk().count - offset - 2
    if jump > 0xFFFF:
        _error("Too much code to jump over.")
    _current_chunk().code[offset] = (jump >> 8) & 0xFF
    _current_chunk().code[offset + 1] = jump & 0xFF


# --------------------------------------------------------------------------- #
# Compiler init / end
# --------------------------------------------------------------------------- #

def _init_compiler(compiler: Compiler, type: FunctionType) -> None:
    """static void initCompiler(Compiler* compiler, FunctionType type)"""
    global _current
    compiler.enclosing = _current
    compiler.function = None
    compiler.type = type
    compiler.local_count = 0
    compiler.scope_depth = 0
    compiler.function = _new_function()
    compiler.locals = []
    compiler.upvalues = []
    _current = compiler

    if type is not FunctionType.TYPE_SCRIPT:
        compiler.function.name = copy_string(_parser.previous.lexeme)

    # Remember that the compiler's locals array keeps track of which stack slots
    # are associated with which local variables or temporaries.  From now on,
    # the compiler implicitly claims stack slot zero for the VM's own internal
    # use.  We give it an empty name so that the user can't write an identifier
    # that refers to it.
    # For function calls, that slot ends up holding the function being called.
    # Since the slot has no name, the function body never accesses it.  You can
    # guess where this is going.  For method calls, we can repurpose that slot
    # to store the receiver.  Slot zero will store the instance that this is
    # bound to.  In order to compile this expressions, the compiler simply needs
    # to give the correct name to that local variable.
    if type is not FunctionType.TYPE_FUNCTION:
        local = Local(Token(TokenType.TOKEN_IDENTIFIER, "this", 4, 0), 0)
    else:
        # We want to do this only for methods.  Function declarations don't have
        # a this.  And, in fact, they must not declare a variable named "this",
        # so that if you write a this expression inside a function declaration
        # which is itself inside a method, the this correctly resolves to the
        # outer method's receiver.
        local = Local(Token(TokenType.TOKEN_IDENTIFIER, "", 0, 0), 0)
    local.is_captured = False
    compiler.locals.append(local)
    compiler.local_count = 1


def _end_compiler() -> ObjFunction:
    """static ObjFunction* endCompiler()"""
    global _current
    _emit_return()
    function = _current.function
    assert function is not None

    if DEBUG_PRINT_CODE and not _parser.had_error:
        from pyvm.debug import disassemble_chunk
        name = function.name.chars if function.name is not None else "<script>"
        disassemble_chunk(_current_chunk(), name)

    # Pop back to the enclosing compiler.
    _current = _current.enclosing
    return function


def _begin_scope() -> None:
    """static void beginScope()"""
    _current.scope_depth += 1


def _end_scope() -> None:
    """static void endScope()"""
    _current.scope_depth -= 1
    # Discard local variables.
    while (
        _current.local_count > 0
        and _current.locals[_current.local_count - 1].depth > _current.scope_depth
    ):
        if _current.locals[_current.local_count - 1].is_captured:
            _emit_byte(OpCode.OP_CLOSE_UPVALUE)
        else:
            _emit_byte(OpCode.OP_POP)
        _current.local_count -= 1
        _current.locals.pop()


# --------------------------------------------------------------------------- #
# Forward declarations
# --------------------------------------------------------------------------- #

def _expression() -> None: ...
def _block() -> None: ...
def _statement() -> None: ...
def _declaration() -> None: ...
def _class_declaration() -> None: ...
def _fun_declaration() -> None: ...
def _var_declaration() -> None: ...
def _parse_precedence(precedence: Precedence) -> None: ...
def _get_rule(type: TokenType) -> ParseRule: ...


# --------------------------------------------------------------------------- #
# Variables / Locals / Upvalues
# --------------------------------------------------------------------------- #

# Global variables are looked up by name at runtime.  That means the VM—the
# bytecode interpreter loop—needs access to the name.  A whole string is too big
# to stuff into the bytecode stream as an operand.  Instead, we store the string
# in the constant table and the instruction then refers to the name by its index
# in the table.
def _identifier_constant(name: Token) -> int:
    """static uint8_t identifierConstant(Token* name) — returns the index of the global VAR."""
    return _make_constant(OBJ_VAL(copy_string(name.lexeme)))


def _identifiers_equal(a: Token, b: Token) -> bool:
    """static bool identifiersEqual(Token* a, Token* b)"""
    return a.lexeme == b.lexeme


def _resolve_local(compiler: Compiler, name: Token) -> int:
    """static int resolveLocal(Compiler* compiler, Token* name)"""
    for i in range(compiler.local_count - 1, -1, -1):
        local = compiler.locals[i]
        # We walk the array backward so that we find the last declared variable
        # with the identifier.  That ensures that inner local variables
        # correctly shadow locals with the same name in surrounding scopes.
        if _identifiers_equal(name, local.name):
            # When we resolve a reference to a local variable, we check the scope
            # depth to see if it's fully defined.
            if local.depth == -1:
                _error("Can't read local variable in its own initializer.")
            return i
    return -1


def _add_upvalue(compiler: Compiler, index: int, is_local: bool) -> int:
    """static int addUpvalue(Compiler* compiler, uint8_t index, bool isLocal)

    The C code does ``return compiler->function->upvalueCount++;`` so the return
    value is the *old* count, and then it increments.
    """
    upvalue_count = compiler.function.upvalue_count
    # A closure may reference the same variable in a surrounding function
    # multiple times.
    for i in range(upvalue_count):
        upvalue = compiler.upvalues[i]
        if upvalue.index == index and upvalue.is_local == is_local:
            return i
    # We can only store a limited number of values — the restriction put in by
    # the bytecode instruction set that we have.
    if upvalue_count == UINT8_COUNT:
        _error("Too many closure variables in function.")
        return 0
    compiler.upvalues.append(Upvalue(index, is_local))
    result = compiler.function.upvalue_count
    compiler.function.upvalue_count += 1
    return result


def _resolve_upvalue(compiler: Compiler, name: Token) -> int:
    """static int resolveUpvalue(Compiler* compiler, Token* name)"""
    # Global case.
    if compiler.enclosing is None:
        return -1
    local = _resolve_local(compiler.enclosing, name)
    if local != -1:
        # When resolving an identifier, if we end up creating an upvalue for a
        # local variable, we mark it as captured.
        # Why this matters at runtime: When the outer function finishes
        # executing and is about to pop its local variables off the stack, it
        # checks each local's isCaptured flag:
        #   If isCaptured is false -> emit OP_POP (cheap discard).
        #   If isCaptured is true  -> emit OP_CLOSE_UPVALUE (move to heap so the
        #   closure can keep accessing it).
        compiler.enclosing.locals[local].is_captured = True
        return _add_upvalue(compiler, local, True)
    # Most recursive functions either do all their work before the recursive
    # call (a pre-order traversal, or "on the way down"), or they do all the
    # work after the recursive call (a post-order traversal, or "on the way
    # back up").  This function does both.  The recursive call is right in the
    # middle.
    upvalue = _resolve_upvalue(compiler.enclosing, name)
    if upvalue != -1:
        return _add_upvalue(compiler, upvalue, False)
    return -1


def _add_local(name: Token) -> None:
    """static void addLocal(Token name)"""
    if _current.local_count == UINT8_COUNT:
        _error("Too many local variables in function.")
        return
    local = Local(name, -1)
    local.is_captured = False
    _current.locals.append(local)
    _current.local_count += 1


def _declare_variable() -> None:
    """static void declareVariable()"""
    # 0 means global.
    if _current.scope_depth == 0:
        return

    name = _parser.previous
    # Shadowing is an ERROR in LOX:
    #   { var a = "first"; var a = "second"; }  // error
    # But this is fine:
    #   { var a = "outer"; { var a = "inner"; } }
    for i in range(_current.local_count - 1, -1, -1):
        local = _current.locals[i]
        if local.depth != -1 and local.depth < _current.scope_depth:
            break
        if _identifiers_equal(name, local.name):
            _error("Already a variable with this name in this scope.")
    _add_local(name)


def _parse_variable(error_message: str) -> int:
    """static uint8_t parseVariable(const char* errorMessage)"""
    _consume(TokenType.TOKEN_IDENTIFIER, error_message)
    _declare_variable()
    # Exit the function if we're in a local scope.  At runtime, locals aren't
    # looked up by name.  There's no need to stuff the variable's name into the
    # constant table, so if the declaration is inside a local scope, we return a
    # dummy table index instead.
    if _current.scope_depth > 0:
        return 0
    return _identifier_constant(_parser.previous)


def _mark_initialized() -> None:
    """static void markInitialized()"""
    # Before, we called markInitialized() only when we already knew we were in a
    # local scope.  Now, a top-level function declaration will also call this
    # function.  When that happens, there is no local variable to mark
    # initialized—the function is bound to a global variable.
    if _current.scope_depth == 0:
        return
    _current.locals[_current.local_count - 1].depth = _current.scope_depth


def _define_variable(global_idx: int) -> None:
    """static void defineVariable(uint8_t global)"""
    # Exit the function if we're in a local scope.  At runtime, locals aren't
    # looked up by name.  There's no need to stuff the variable's name into the
    # constant table, so if the declaration is inside a local scope, we return a
    # dummy table index instead.
    # It has already executed the code for the variable's initializer (or the
    # implicit nil if the user omitted an initializer), and that value is
    # sitting right on top of the stack as the only remaining temporary.
    # We also know that new locals are allocated at the top of the stack, right
    # where that value already is.
    if _current.scope_depth > 0:
        # Move the local var depth from -1 => current depth.
        _mark_initialized()
        return
    _emit_bytes(OpCode.OP_DEFINE_GLOBAL, global_idx)


def _argument_list() -> int:
    """static uint8_t argumentList()"""
    arg_count = 0
    if not _check(TokenType.TOKEN_RIGHT_PAREN):
        while True:
            _expression()
            if arg_count == 255:
                _error_at_current("Can't have more than 255 arguments.")
            arg_count += 1
            if not _match(TokenType.TOKEN_COMMA):
                break
    _consume(TokenType.TOKEN_RIGHT_PAREN, "Expect ')' after arguments.")
    return arg_count


# --------------------------------------------------------------------------- #
# Parse functions (prefix / infix)
# --------------------------------------------------------------------------- #

def _and_(can_assign: bool) -> None:
    """static void and_(bool canAssign)"""
    end_jump = _emit_jump(OpCode.OP_JUMP_IF_FALSE)
    _emit_byte(OpCode.OP_POP)
    _parse_precedence(Precedence.PREC_AND)
    _patch_jump(end_jump)


def _grouping(can_assign: bool) -> None:
    """static void grouping(bool canAssign)"""
    _expression()
    _consume(TokenType.TOKEN_RIGHT_PAREN, "Expect ')' after expression.")


# We define a function for each expression that outputs the appropriate
# bytecode.  Then we build an array of function pointers.  The indexes in the
# array correspond to the TokenType enum values, and the function at each index
# is the code to compile an expression of that token type.
# To compile number literals, we store a pointer to the following function at the
# TOKEN_NUMBER index in the array.
def _number(can_assign: bool) -> None:
    """static void number(bool canAssign)"""
    value = float(_parser.previous.lexeme)
    _emit_constant(NUMBER_VAL(value))


def _or_(can_assign: bool) -> None:
    """static void or_(bool canAssign)"""
    else_jump = _emit_jump(OpCode.OP_JUMP_IF_FALSE)
    end_jump = _emit_jump(OpCode.OP_JUMP)

    _patch_jump(else_jump)
    _emit_byte(OpCode.OP_POP)

    _parse_precedence(Precedence.PREC_OR)
    _patch_jump(end_jump)


# The +1 and -2 parts trim the leading and trailing quotation marks.
# If Lox supported string escape sequences like \n, we'd translate those here.
# Since it doesn't, we can take the characters as they are.
def _string(can_assign: bool) -> None:
    """static void string(bool canAssign)"""
    lexeme = _parser.previous.lexeme
    # Trim the surrounding quotes.
    inner = lexeme[1:-1]
    _emit_constant(OBJ_VAL(copy_string(inner)))


def _named_variable(name: Token, can_assign: bool) -> None:
    """static void namedVariable(Token name, bool canAssign)"""
    arg = _resolve_local(_current, name)
    if arg != -1:
        get_op = OpCode.OP_GET_LOCAL
        set_op = OpCode.OP_SET_LOCAL
    else:
        # Before simply ignoring the enclosing functions and jumping directly
        # to assuming that variables were declared globally, we try to resolve
        # variables in the enclosing functions now.
        arg = _resolve_upvalue(_current, name)
        if arg != -1:
            get_op = OpCode.OP_GET_UPVALUE
            set_op = OpCode.OP_SET_UPVALUE
        else:
            arg = _identifier_constant(name)
            get_op = OpCode.OP_GET_GLOBAL
            set_op = OpCode.OP_SET_GLOBAL

    if can_assign and _match(TokenType.TOKEN_EQUAL):
        _expression()
        _emit_bytes(set_op, arg)
    else:
        _emit_bytes(get_op, arg)


def _variable(can_assign: bool) -> None:
    """static void variable(bool canAssign)"""
    _named_variable(_parser.previous, can_assign)


def _synthetic_token(text: str) -> Token:
    """static Token syntheticToken(const char* text)"""
    return Token(TokenType.TOKEN_IDENTIFIER, text, len(text), 0)


def _super_(can_assign: bool) -> None:
    """static void super_(bool canAssign)"""
    if _current_class is None:
        _error("Can't use 'super' outside of a class.")
    elif not _current_class.has_superclass:
        _error("Can't use 'super' in a class with no superclass.")

    _consume(TokenType.TOKEN_DOT, "Expect '.' after 'super'.")
    _consume(TokenType.TOKEN_IDENTIFIER, "Expect superclass method name.")
    name = _identifier_constant(_parser.previous)
    # In other words, Lox doesn't really have super call expressions, it has
    # super access expressions, which you can choose to immediately invoke if
    # you want.  So when the compiler hits a super token, we consume the
    # subsequent . token and then look for a method name.  Methods are looked up
    # dynamically, so we use identifierConstant() to take the lexeme of the
    # method name token and store it in the constant table just like we do for
    # property access expressions.
    _named_variable(_synthetic_token("this"), False)
    if _match(TokenType.TOKEN_LEFT_PAREN):
        # Now before we emit anything, we look for a parenthesized argument
        # list.  If we find one, we compile that.  Then we load the superclass.
        # After that, we emit a new OP_SUPER_INVOKE instruction.  This
        # superinstruction combines the behavior of OP_GET_SUPER and OP_CALL, so
        # it takes two operands: the constant table index of the method name to
        # look up and the number of arguments to pass to it.
        arg_count = _argument_list()
        _named_variable(_synthetic_token("super"), False)
        _emit_bytes(OpCode.OP_SUPER_INVOKE, name)
        _emit_byte(arg_count)
    else:
        _named_variable(_synthetic_token("super"), False)
        _emit_bytes(OpCode.OP_GET_SUPER, name)


def _this_(can_assign: bool) -> None:
    """static void this_(bool canAssign)"""
    # print this; // At top level.
    # fun notMethod() { print this; } // In a function.
    if _current_class is None:
        _error("Can't use 'this' outside of a class.")
        return
    # We'll apply the same implementation technique for this in clox that we
    # used in jlox.  We treat this as a lexically scoped local variable whose
    # value gets magically initialized.  Compiling it like a local variable
    # means we get a lot of behavior for free.  In particular, closures inside a
    # method that reference this will do the right thing and capture the
    # receiver in an upvalue.  When the parser function is called, the this
    # token has just been consumed and is stored as the previous token.  We call
    # our existing variable() function which compiles identifier expressions as
    # variable accesses.  It takes a single Boolean parameter for whether the
    # compiler should look for a following = operator and parse a setter.  You
    # can't assign to this, so we pass false to disallow that.
    _variable(False)


def _unary(can_assign: bool) -> None:
    """static void unary(bool canAssign)"""
    operator_type = _parser.previous.type

    # Compile the operand.
    _parse_precedence(Precedence.PREC_UNARY)

    # The operator appears on the left, but think about it in terms of order of
    # execution: We evaluate the operand first which leaves its value on the
    # stack.  Then we pop that value, negate it, and push the result.  So the
    # OP_NEGATE instruction should be emitted last.  This is part of the
    # compiler's job—parsing the program in the order it appears in the source
    # code and rearranging it into the order that execution happens.
    if operator_type is TokenType.TOKEN_BANG:
        _emit_byte(OpCode.OP_NOT)
    elif operator_type is TokenType.TOKEN_MINUS:
        _emit_byte(OpCode.OP_NEGATE)


# Binary operators are different from the previous expressions because they are
# infix.  With infix expressions, we don't know we're in the middle of a binary
# operator until after we've parsed its left operand and then stumbled onto the
# operator token in the middle.
# e.g.:  1 + 2
# 1.> We call expression().  That in turn calls parsePrecedence(PREC_ASSIGNMENT).
# 2.> That function sees the leading number token and recognizes it is parsing a
#     number literal.
# 3.> It hands off control to number().
# 4.> number() creates a constant, emits an OP_CONSTANT, and returns back to
#     parsePrecedence().  Now that we've compiled the leading number expression,
#     the next token is +.  That's the exact token that parsePrecedence() needs
#     to detect that we're in the middle of an infix expression and to realize
#     that the expression we already compiled is actually an operand to that.
def _binary(can_assign: bool) -> None:
    """static void binary(bool canAssign)"""
    operator_type = _parser.previous.type
    # We use {{one higher level of precedence}} for the right operand because the
    # binary operators are {{left-associative}}.  Given a series of the same
    # operator, like:
    #   1 + 2 + 3 + 4  -->  We want to parse it like  -->  ((1 + 2) + 3) + 4
    rule = _get_rule(operator_type)
    _parse_precedence(Precedence(rule.precedence.value + 1))

    # The fact that the left operand gets compiled first works out fine.  It
    # means at runtime, that code gets executed first.  When it runs, the value
    # it produces will end up on the stack.  That's right where the infix
    # operator is going to need it.  When run, the VM will execute the left and
    # right operand code, in that order, leaving their values on the stack.  Then
    # it executes the instruction for the operator.  That pops the two values,
    # computes the operation, and pushes the result.
    if operator_type is TokenType.TOKEN_BANG_EQUAL:
        _emit_bytes(OpCode.OP_EQUAL, OpCode.OP_NOT)
    elif operator_type is TokenType.TOKEN_EQUAL_EQUAL:
        _emit_byte(OpCode.OP_EQUAL)
    elif operator_type is TokenType.TOKEN_GREATER:
        _emit_byte(OpCode.OP_GREATER)
    elif operator_type is TokenType.TOKEN_GREATER_EQUAL:
        _emit_bytes(OpCode.OP_LESS, OpCode.OP_NOT)
    elif operator_type is TokenType.TOKEN_LESS:
        _emit_byte(OpCode.OP_LESS)
    elif operator_type is TokenType.TOKEN_LESS_EQUAL:
        _emit_bytes(OpCode.OP_GREATER, OpCode.OP_NOT)
    elif operator_type is TokenType.TOKEN_PLUS:
        _emit_byte(OpCode.OP_ADD)
    elif operator_type is TokenType.TOKEN_MINUS:
        _emit_byte(OpCode.OP_SUBTRACT)
    elif operator_type is TokenType.TOKEN_STAR:
        _emit_byte(OpCode.OP_MULTIPLY)
    elif operator_type is TokenType.TOKEN_SLASH:
        _emit_byte(OpCode.OP_DIVIDE)


def _call(can_assign: bool) -> None:
    """static void call(bool canAssign)"""
    arg_count = _argument_list()
    _emit_bytes(OpCode.OP_CALL, arg_count)


def _dot(can_assign: bool) -> None:
    """static void dot(bool canAssign)"""
    _consume(TokenType.TOKEN_IDENTIFIER, "Expect property name after '.'.")
    name = _identifier_constant(_parser.previous)

    if can_assign and _match(TokenType.TOKEN_EQUAL):
        _expression()
        _emit_bytes(OpCode.OP_SET_PROPERTY, name)
    elif _match(TokenType.TOKEN_LEFT_PAREN):
        # Lox's semantics define a method invocation as two operations—accessing
        # the method and then calling the result.  Our VM must support those as
        # separate operations because the user can separate them.  You can access
        # a method without calling it and then invoke the bound method later.
        # Nothing we've implemented so far is unnecessary.
        #
        # But always executing those as separate operations has a significant
        # cost.  Every single time a Lox program accesses and invokes a method,
        # the runtime heap allocates a new ObjBoundMethod, initializes its
        # fields, then pulls them right back out.  Later, the GC has to spend
        # time freeing all of those ephemeral bound methods.
        #
        # Most of the time, a Lox program accesses a method and then immediately
        # calls it.  The bound method is created by one bytecode instruction and
        # then consumed by the very next one.  In fact, it's so immediate that
        # the compiler can even textually see that it's happening—a dotted
        # property access followed by an opening parenthesis is most likely a
        # method call.
        #
        # Since we can recognize this pair of operations at compile time, we have
        # the opportunity to emit a new, special instruction that performs an
        # optimized method call.  If you spend enough time watching your
        # bytecode VM run, you'll notice it often executes the same series of
        # bytecode instructions one after the other.  A classic optimization
        # technique is to define a new single instruction called a
        # superinstruction that fuses those into a single instruction with the
        # same behavior as the entire sequence.  One of the largest performance
        # drains in a bytecode VM is the overhead of decoding and dispatching
        # each instruction.  Fusing several instructions into one eliminates
        # some of that.  The challenge is determining which instruction sequences
        # are common enough to benefit from this optimization.  Every new
        # superinstruction claims an opcode for its own use and there are only so
        # many of those to go around.  Add too many, and you'll need a larger
        # encoding for opcodes, which then increases code size and makes decoding
        # all instructions slower.
        arg_count = _argument_list()
        # In other words, this single instruction combines the operands of the
        # OP_GET_PROPERTY and OP_CALL instructions it replaces, in that order.
        # It really is a fusion of those two instructions.  Let's define it.
        _emit_bytes(OpCode.OP_INVOKE, name)
        _emit_byte(arg_count)
    else:
        _emit_bytes(OpCode.OP_GET_PROPERTY, name)


def _literal(can_assign: bool) -> None:
    """static void literal(bool canAssign)"""
    if _parser.previous.type is TokenType.TOKEN_FALSE:
        _emit_byte(OpCode.OP_FALSE)
    elif _parser.previous.type is TokenType.TOKEN_NIL:
        _emit_byte(OpCode.OP_NIL)
    elif _parser.previous.type is TokenType.TOKEN_TRUE:
        _emit_byte(OpCode.OP_TRUE)


# --------------------------------------------------------------------------- #
# Parse rules table
# --------------------------------------------------------------------------- #

# We build a dict mapping TokenType -> ParseRule.  In C this is an array indexed
# by the TokenType enum values; here we use a dict for the same purpose.
def _build_rules() -> dict[TokenType, ParseRule]:
    return {
        TokenType.TOKEN_LEFT_PAREN:    ParseRule(_grouping, _call,   Precedence.PREC_CALL),
        TokenType.TOKEN_RIGHT_PAREN:   ParseRule(None,     None,    Precedence.PREC_NONE),
        TokenType.TOKEN_LEFT_BRACE:    ParseRule(None,     None,    Precedence.PREC_NONE),
        TokenType.TOKEN_RIGHT_BRACE:   ParseRule(None,     None,    Precedence.PREC_NONE),
        TokenType.TOKEN_COMMA:         ParseRule(None,     None,    Precedence.PREC_NONE),
        TokenType.TOKEN_DOT:           ParseRule(None,     _dot,    Precedence.PREC_CALL),
        TokenType.TOKEN_MINUS:         ParseRule(_unary,   _binary, Precedence.PREC_TERM),
        TokenType.TOKEN_PLUS:          ParseRule(None,     _binary, Precedence.PREC_TERM),
        TokenType.TOKEN_SEMICOLON:     ParseRule(None,     None,    Precedence.PREC_NONE),
        TokenType.TOKEN_SLASH:         ParseRule(None,     _binary, Precedence.PREC_FACTOR),
        TokenType.TOKEN_STAR:          ParseRule(None,     _binary, Precedence.PREC_FACTOR),
        TokenType.TOKEN_BANG:          ParseRule(_unary,   None,    Precedence.PREC_NONE),
        TokenType.TOKEN_BANG_EQUAL:    ParseRule(None,     _binary, Precedence.PREC_EQUALITY),
        TokenType.TOKEN_EQUAL:         ParseRule(None,     None,    Precedence.PREC_NONE),
        TokenType.TOKEN_EQUAL_EQUAL:   ParseRule(None,     _binary, Precedence.PREC_EQUALITY),
        TokenType.TOKEN_GREATER:       ParseRule(None,     _binary, Precedence.PREC_COMPARISON),
        TokenType.TOKEN_GREATER_EQUAL: ParseRule(None,     _binary, Precedence.PREC_COMPARISON),
        TokenType.TOKEN_LESS:          ParseRule(None,     _binary, Precedence.PREC_COMPARISON),
        TokenType.TOKEN_LESS_EQUAL:    ParseRule(None,     _binary, Precedence.PREC_COMPARISON),
        TokenType.TOKEN_IDENTIFIER:    ParseRule(_variable, None,   Precedence.PREC_NONE),
        TokenType.TOKEN_STRING:        ParseRule(_string,  None,    Precedence.PREC_NONE),
        TokenType.TOKEN_NUMBER:        ParseRule(_number,  None,    Precedence.PREC_NONE),
        TokenType.TOKEN_AND:           ParseRule(None,     _and_,   Precedence.PREC_AND),
        TokenType.TOKEN_CLASS:         ParseRule(None,     None,    Precedence.PREC_NONE),
        TokenType.TOKEN_ELSE:          ParseRule(None,     None,    Precedence.PREC_NONE),
        TokenType.TOKEN_FALSE:         ParseRule(_literal, None,    Precedence.PREC_NONE),
        TokenType.TOKEN_FOR:           ParseRule(None,     None,    Precedence.PREC_NONE),
        TokenType.TOKEN_FUN:           ParseRule(None,     None,    Precedence.PREC_NONE),
        TokenType.TOKEN_IF:            ParseRule(None,     None,    Precedence.PREC_NONE),
        TokenType.TOKEN_NIL:           ParseRule(_literal, None,    Precedence.PREC_NONE),
        TokenType.TOKEN_OR:            ParseRule(None,     _or_,    Precedence.PREC_OR),
        TokenType.TOKEN_PRINT:         ParseRule(None,     None,    Precedence.PREC_NONE),
        TokenType.TOKEN_RETURN:        ParseRule(None,     None,    Precedence.PREC_NONE),
        TokenType.TOKEN_SUPER:         ParseRule(_super_,  None,    Precedence.PREC_NONE),
        # The underscore at the end of the name of the parser function is
        # because this is a reserved word in C++ and we support compiling clox
        # as C++.  Same as class -> klass.
        TokenType.TOKEN_THIS:          ParseRule(_this_,   None,    Precedence.PREC_NONE),
        TokenType.TOKEN_TRUE:          ParseRule(_literal, None,    Precedence.PREC_NONE),
        TokenType.TOKEN_VAR:           ParseRule(None,     None,    Precedence.PREC_NONE),
        TokenType.TOKEN_WHILE:         ParseRule(None,     None,    Precedence.PREC_NONE),
        TokenType.TOKEN_ERROR:         ParseRule(None,     None,    Precedence.PREC_NONE),
        TokenType.TOKEN_EOF:           ParseRule(None,     None,    Precedence.PREC_NONE),
    }


_rules: dict[TokenType, ParseRule] = {}


# --------------------------------------------------------------------------- #
# parsePrecedence / getRule / expression
# --------------------------------------------------------------------------- #

# The parsing functions like number() and unary() here in clox are different.
# Each only parses exactly one type of expression.
# This function—once we implement it—starts at the current token and parses any
# expression at the given precedence level or higher.
def _parse_precedence(precedence: Precedence) -> None:
    """static void parsePrecedence(Precedence precedence)"""
    _advance()
    # At the beginning of parsePrecedence(), we look up a prefix parser for the
    # current token.  The first token is always going to belong to some kind of
    # prefix expression, by definition.  It may turn out to be nested as an
    # operand inside one or more infix expressions, but as you read the code from
    # left to right, the first token you hit always belongs to a prefix
    # expression.
    prefix_rule = _get_rule(_parser.previous.type).prefix
    if prefix_rule is None:
        _error("Expect expression.")
        return

    can_assign = precedence.value <= Precedence.PREC_ASSIGNMENT.value
    prefix_rule(can_assign)

    while precedence.value <= _get_rule(_parser.current.type).precedence.value:
        _advance()
        infix_rule = _get_rule(_parser.previous.type).infix
        assert infix_rule is not None
        infix_rule(can_assign)

    if can_assign and _match(TokenType.TOKEN_EQUAL):
        _error("Invalid assignment target.")


def _get_rule(type: TokenType) -> ParseRule:
    """static ParseRule* getRule(TokenType type)"""
    return _rules[type]


def _expression() -> None:
    """static void expression()"""
    _parse_precedence(Precedence.PREC_ASSIGNMENT)


# --------------------------------------------------------------------------- #
# Declarations & statements
# --------------------------------------------------------------------------- #

def _var_declaration() -> None:
    """static void varDeclaration()"""
    global_idx = _parse_variable("Expect variable name")
    if _match(TokenType.TOKEN_EQUAL):
        _expression()
    else:
        # Desugaring of declaration:
        #   var a;  -->  var a = nil;
        _emit_byte(OpCode.OP_NIL)
    _consume(TokenType.TOKEN_SEMICOLON, "Expect ';' after variable declaration.")
    _define_variable(global_idx)


def _expression_statement() -> None:
    """static void expressionStatement()

    An "expression statement" is simply an expression followed by a semicolon.
    They're how you write an expression in a context where a statement is
    expected.  Usually, it's so that you can call a function or evaluate an
    assignment for its side effect.
    """
    _expression()
    _consume(TokenType.TOKEN_SEMICOLON, "Expect ';' after value.")
    _emit_byte(OpCode.OP_POP)


def _for_statement() -> None:
    """static void forStatement()"""
    _begin_scope()
    _consume(TokenType.TOKEN_LEFT_PAREN, "Expect '(' after 'for'.")
    # INITIALIZER
    if _match(TokenType.TOKEN_SEMICOLON):
        pass  # no initializer
    elif _match(TokenType.TOKEN_VAR):
        _var_declaration()
    else:
        _expression_statement()
    # We don't want the initializer to leave anything on the stack.

    # Here is the expression we need to evaluate multiple times.
    loop_start = _current_chunk().count
    exit_jump = -1
    # This isn't an infinite loop, like:  for (int i; <condition empty>; i+=1)
    # CONDITION
    if not _match(TokenType.TOKEN_SEMICOLON):
        _expression()
        _consume(TokenType.TOKEN_SEMICOLON, "Expect ';' after loop condition.")
        # Jump out of the loop if the condition is false.
        exit_jump = _emit_jump(OpCode.OP_JUMP_IF_FALSE)
        _emit_byte(OpCode.OP_POP)  # Condition.

    # The increment clause.  It's pretty convoluted.  It appears textually before
    # the body, but executes after it.  If we parsed to an AST and generated
    # code in a separate pass, we could simply traverse into and compile the for
    # statement AST's body field before its increment clause.  But since our
    # compiler only makes a single pass over the code, instead we'll jump over
    # the increment, run the body, jump back up to the increment, run it, and
    # then go to the next iteration.
    if not _match(TokenType.TOKEN_RIGHT_PAREN):
        body_jump = _emit_jump(OpCode.OP_JUMP)
        increment_start = _current_chunk().count
        _expression()
        _emit_byte(OpCode.OP_POP)
        _consume(TokenType.TOKEN_RIGHT_PAREN, "Expect ')' after for clauses.")
        _emit_loop(loop_start)
        loop_start = increment_start
        _patch_jump(body_jump)

    _statement()
    _emit_loop(loop_start)
    if exit_jump != -1:
        _patch_jump(exit_jump)
        _emit_byte(OpCode.OP_POP)
    _end_scope()


def _if_statement() -> None:
    """static void ifStatement()"""
    _consume(TokenType.TOKEN_LEFT_PAREN, "Expect '(' after 'if'.")
    _expression()
    _consume(TokenType.TOKEN_RIGHT_PAREN, "Expect ')' after 'if'.")

    then_jump = _emit_jump(OpCode.OP_JUMP_IF_FALSE)
    # The setup on the stack:
    # 1> Evaluation: When the if statement begins, the compiler runs
    #    expression().  At runtime, this evaluates your condition (e.g., x > 5)
    #    and pushes either [true or false] onto the top of the stack.
    # 2> The jump check: Next, OP_JUMP_IF_FALSE looks at that top value to
    #    decide whether it needs to skip the code block.  As noted in the text,
    #    OP_JUMP_IF_FALSE intentionally does not pop the value because the VM
    #    wants to reuse that exact same instruction later for short-circuiting
    #    logical operators (like and and or).
    # 3> The leftover value: Because the jump instruction left it behind, the
    #    condition value is still sitting on top of the stack when the VM enters
    #    the then branch.

    # To clear up the TRUE value on the stack.
    _emit_byte(OpCode.OP_POP)
    _statement()

    # We have to have the else jumps as well because if the <if> branch is taken,
    # once that branch is done, we have to skip over <else> branch and continue
    # from a new location.
    else_jump = _emit_jump(OpCode.OP_JUMP)

    _patch_jump(then_jump)
    # To clear up the FALSE value on the stack.  Lands here on OP_JUMP_IF_FALSE.
    _emit_byte(OpCode.OP_POP)

    # Adding support for else branch.
    if _match(TokenType.TOKEN_ELSE):
        _statement()
    # After executing the then branch, this jumps to the next statement after
    # the else branch.  Unlike the other jump, this jump is unconditional.
    _patch_jump(else_jump)


def _print_statement() -> None:
    """static void printStatement()"""
    _expression()
    _consume(TokenType.TOKEN_SEMICOLON, "Expect ';' after value.")
    _emit_byte(OpCode.OP_PRINT)


def _return_statement() -> None:
    """static void returnStatement()"""
    if _current.type is FunctionType.TYPE_SCRIPT:
        # This is one of the reasons we added that FunctionType enum to the
        # compiler.
        _error("Can't return from top-level code.")
    if _match(TokenType.TOKEN_SEMICOLON):
        # This sets up the NIL value on the stack.
        _emit_return()
    else:
        if _current.type is FunctionType.TYPE_INITIALIZER:
            _error("Can't return a value from an initializer.")
        # The return value expression is optional, so the parser looks for a
        # semicolon token to tell if a value was provided.  If there is no
        # return value, the statement implicitly returns nil.  We implement that
        # by calling emitReturn(), which emits an OP_NIL instruction.  Otherwise,
        # we compile the return value expression and return it with an
        # OP_RETURN instruction.
        _expression()
        _consume(TokenType.TOKEN_SEMICOLON, "Expect ';' after return value.")
        _emit_byte(OpCode.OP_RETURN)


def _while_statement() -> None:
    """static void whileStatement()"""
    loop_start = _current_chunk().count
    _consume(TokenType.TOKEN_LEFT_PAREN, "Expect '(' after 'while'.")
    _expression()
    _consume(TokenType.TOKEN_RIGHT_PAREN, "Expect ')' after condition.")

    exit_jump = _emit_jump(OpCode.OP_JUMP_IF_FALSE)
    _emit_byte(OpCode.OP_POP)
    _statement()
    # Once statement is done, we might want to loop back.
    _emit_loop(loop_start)

    _patch_jump(exit_jump)
    _emit_byte(OpCode.OP_POP)


# If we hit a compile error while parsing the previous statement, we enter panic
# mode.  When that happens, after the statement we start synchronizing.
def _synchronize() -> None:
    """static void synchronize()"""
    _parser.panic_mode = False
    # We skip tokens indiscriminately until we reach something that looks like a
    # statement boundary.  We recognize the boundary by looking for a preceding
    # token that can end a statement, like a semicolon.  Or we'll look for a
    # subsequent token that begins a statement, usually one of the control flow
    # or declaration keywords.
    while _parser.current.type is not TokenType.TOKEN_EOF:
        if _parser.previous.type is TokenType.TOKEN_SEMICOLON:
            return
        if _parser.current.type in (
            TokenType.TOKEN_CLASS, TokenType.TOKEN_FUN, TokenType.TOKEN_VAR,
            TokenType.TOKEN_FOR, TokenType.TOKEN_IF, TokenType.TOKEN_WHILE,
            TokenType.TOKEN_PRINT, TokenType.TOKEN_RETURN,
        ):
            return
        _advance()


# # GRAMMAR
# statement        → exprStmt
#                  | printStmt
#                  | block
#
# block            -> "{" declaration* "}"
#
# declaration      → varDecl
#                  | statement

def _declaration() -> None:
    """static void declaration()"""
    if _match(TokenType.TOKEN_CLASS):
        _class_declaration()
    elif _match(TokenType.TOKEN_FUN):
        _fun_declaration()
    elif _match(TokenType.TOKEN_VAR):
        _var_declaration()
    else:
        _statement()
    if _parser.panic_mode:
        _synchronize()


def _block() -> None:
    """static void block()"""
    while not _check(TokenType.TOKEN_RIGHT_BRACE) and not _check(TokenType.TOKEN_EOF):
        _declaration()
    _consume(TokenType.TOKEN_RIGHT_BRACE, "Expect '}' after block")


def _function(type: FunctionType) -> None:
    """static void function(FunctionType type)"""
    compiler = Compiler(_current, type)
    _init_compiler(compiler, type)
    _begin_scope()

    _consume(TokenType.TOKEN_LEFT_PAREN, "Expect '(' after function name.")
    # Parameters.
    if not _check(TokenType.TOKEN_RIGHT_PAREN):
        while True:
            _current.function.arity += 1
            if _current.function.arity > 255:
                _error_at_current("Can't have more than 255 parameters.")
            constant = _parse_variable("Expect parameter name.")
            _define_variable(constant)
            if not _match(TokenType.TOKEN_COMMA):
                break
    _consume(TokenType.TOKEN_RIGHT_PAREN, "Expect ')' after parameters.")
    _consume(TokenType.TOKEN_LEFT_BRACE, "Expect '{' before function body.")
    _block()

    # The compiler yields the newly compiled function object,
    function = _end_compiler()
    # which we store as a constant in the surrounding function's constant table.
    _emit_bytes(OpCode.OP_CLOSURE, _make_constant(OBJ_VAL(function)))

    # VM and Compiler work together here to make sure the closure captured
    # variables live long enough.
    for i in range(function.upvalue_count):
        _emit_byte(1 if compiler.upvalues[i].is_local else 0)
        _emit_byte(compiler.upvalues[i].index)


def _method() -> None:
    """static void method()"""
    _consume(TokenType.TOKEN_IDENTIFIER, "Expect method name.")
    constant = _identifier_constant(_parser.previous)
    type = FunctionType.TYPE_METHOD
    # The user's invocation on the class to create the instance will complete
    # whenever that initializer method returns, and will leave on the stack
    # whatever value the initializer puts there.  That means that unless the
    # user takes care to put return this; at the end of the initializer, no
    # instance will come out.
    if _parser.previous.lexeme == "init":
        type = FunctionType.TYPE_INITIALIZER
    _function(type)
    _emit_bytes(OpCode.OP_METHOD, constant)


def _class_declaration() -> None:
    """static void classDeclaration()"""
    _consume(TokenType.TOKEN_IDENTIFIER, "Expect a class name.")
    class_name = _parser.previous
    name_constant = _identifier_constant(_parser.previous)
    _declare_variable()

    _emit_bytes(OpCode.OP_CLASS, name_constant)
    _define_variable(name_constant)

    # If we aren't inside any class declaration at all, the module variable
    # currentClass is NULL.  When the compiler begins compiling a class, it
    # pushes a new ClassCompiler onto that implicit linked stack.
    global _current_class
    class_compiler = ClassCompiler(_current_class)
    class_compiler.has_superclass = False
    _current_class = class_compiler

    # Inheritance:
    #   class Doughnut { cook() { print "Dunk in the fryer."; } }
    #   class Cruller < Doughnut { finish() { print "Glaze with icing."; } }
    if _match(TokenType.TOKEN_LESS):
        _consume(TokenType.TOKEN_IDENTIFIER, "Expect superclass name.")
        # It looks up the superclass by name and pushes it onto the stack.
        _variable(False)
        if _identifiers_equal(class_name, _parser.previous):
            _error("A class can't inherit from itself.")

        _begin_scope()
        # We name the variable "super" for the same reason we use "this" as the
        # name of the hidden local variable that this expressions resolve to:
        # "super" is a reserved word, which guarantees the compiler's hidden
        # variable won't collide with a user-defined one.
        _add_local(_synthetic_token("super"))
        _define_variable(0)

        _named_variable(class_name, False)
        _emit_byte(OpCode.OP_INHERIT)
        class_compiler.has_superclass = True

    # That helper function generates code to load a variable with the given name
    # onto the stack.
    _named_variable(class_name, False)
    _consume(TokenType.TOKEN_LEFT_BRACE, "Expect '{' before class body.")
    while not _check(TokenType.TOKEN_RIGHT_BRACE) and not _check(TokenType.TOKEN_EOF):
        _method()
    _consume(TokenType.TOKEN_RIGHT_BRACE, "Expect '}' after class body.")
    # This means that when we execute each OP_METHOD instruction, the stack has
    # the method's closure on top with the class right under it.  Once we've
    # reached the end of the methods, we no longer need the class and tell the
    # VM to pop it off the stack.
    _emit_byte(OpCode.OP_POP)
    if class_compiler.has_superclass:
        _end_scope()
    _current_class = _current_class.enclosing


def _fun_declaration() -> None:
    """static void funDeclaration()

    A function declaration at the top level will bind the function to a global
    variable.  Inside a block or other function, a function declaration creates
    a local variable.
    """
    global_idx = _parse_variable("Expect function name")
    # It's safe for a function to refer to its own name inside its body.  You
    # can't call the function and execute the body until after it's fully
    # defined, so you'll never see the variable in an uninitialized state.
    # Practically speaking, it's useful to allow this in order to support
    # recursive local functions.
    _mark_initialized()
    _function(FunctionType.TYPE_FUNCTION)
    _define_variable(global_idx)


def _statement() -> None:
    """static void statement()"""
    if _match(TokenType.TOKEN_PRINT):
        _print_statement()
    elif _match(TokenType.TOKEN_FOR):
        _for_statement()
    elif _match(TokenType.TOKEN_IF):
        _if_statement()
    elif _match(TokenType.TOKEN_RETURN):
        _return_statement()
    elif _match(TokenType.TOKEN_WHILE):
        _while_statement()
    # Blocks are a kind of statement, so the rule for them goes in the statement
    # production.
    elif _match(TokenType.TOKEN_LEFT_BRACE):
        _begin_scope()
        _block()
        _end_scope()
    else:
        _expression_statement()


# --------------------------------------------------------------------------- #
# New function helper (mirrors newFunction() from object.c, but local to avoid
# circular import issues)
# --------------------------------------------------------------------------- #

def _new_function() -> ObjFunction:
    from pyvm.object import new_function
    return new_function()


# --------------------------------------------------------------------------- #
# compile() — public entry point
# --------------------------------------------------------------------------- #

def compile(source: str) -> Optional[ObjFunction]:
    """ObjFunction* compile(const char* source)

    Usually the compilation is a two (a minimum of two) step process:
      parser -> generates AST
      code generator -> reads AST -> generates machine code
    For LOX, we will build a one-pass compiler.
    """
    global _parser, _current, _current_class, _rules
    _rules = _build_rules()

    init_scanner(source)
    compiler = Compiler(None, FunctionType.TYPE_SCRIPT)
    _init_compiler(compiler, FunctionType.TYPE_SCRIPT)

    _parser = Parser()
    _parser.panic_mode = False
    _parser.had_error = False

    # Start scanner.
    _advance()
    # Then we parse declarations until EOF.
    while not _match(TokenType.TOKEN_EOF):
        _declaration()
    function = _end_compiler()
    return None if _parser.had_error else function


def mark_compiler_roots() -> None:
    """void markCompilerRoots()"""
    from pyvm.memory import mark_object
    compiler = _current
    while compiler is not None:
        mark_object(compiler.function)
        compiler = compiler.enclosing