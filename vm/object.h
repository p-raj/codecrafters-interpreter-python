#ifndef clox_object_h
#define clox_object_h

#include "chunk.h"
#include "common.h"
#include "value.h"

typedef enum {
    OBJ_CLOSURE,
    OBJ_FUNCTION,
    OBJ_NATIVE,
    OBJ_STRING,
    OBJ_UPVALUE,
} ObjType;

// extract the type of object
#define OBJ_TYPE(value) (AS_OBJ(value)->type)

#define IS_CLOSURE(value) isObjType(value, OBJ_CLOSURE)
#define IS_FUNCTION(value) isObjType(value, OBJ_FUNCTION)
#define IS_NATIVE(value) isObjType(value, OBJ_NATIVE)
#define IS_STRING(value) isObjType(value, OBJ_STRING)

#define AS_CLOSURE(value) ((ObjClosure*)AS_OBJ(value))
#define AS_FUNCTION(value) ((ObjFunction*)AS_OBJ(value))
#define AS_NATIVE(value) (((ObjNative*)AS_OBJ(value))->function)
#define AS_STRING(value) ((ObjString*)AS_OBJ(value))
#define AS_CSTRING(value) (((ObjString*)AS_OBJ(value))->chars)

// C specifies that struct fields are arranged in memory in the order that they are declared. Also,
// when you nest structs, the inner struct’s fields are expanded right in place.
struct Obj {
    ObjType type;
    // GC - mark phase
    bool isMarked;
    struct Obj* next;
};

typedef Value (*NativeFn)(int argCount, Value* args);

typedef struct {
    Obj obj;
    // Obj header and a pointer to the C function that implements the native behavior.
    NativeFn function;
} ObjNative;

struct ObjString {
    // You can take a pointer to a struct and safely convert it to a pointer to its first field and
    // back.
    Obj obj;
    int length;
    char* chars;
    uint32_t hash;
};

// Each OP_CLOSURE instruction is now followed by the series of bytes that specify the upvalues the
// ObjClosure should own.
// We know upvalues must manage closed-over variables that no longer live on
// the stack, which implies some amount of dynamic allocation.
//
typedef struct ObjUpvalue {
    Obj obj;
    // Note that this is a pointer to a Value, not a Value itself. It’s a reference to a variable,
    // not a value.
    // This is important because it means that when we assign to the variable the upvalue captures,
    // we’re assigning to the actual variable, not a copy
    Value* location;
    Value closed;
    struct ObjUpvalue* next;
} ObjUpvalue;

// For the functions
typedef struct {
    Obj obj;
    int arity;
    Chunk chunk;
    int upvalueCount;
    ObjString* name;
} ObjFunction;

// For the closure
// wrap the <fn>
typedef struct {
    Obj obj;
    ObjFunction* function;
    // Different closures may have different numbers of upvalues, so we need a dynamic array.
    // The upvalues themselves are dynamically allocated too, so we end up with a double pointer—a
    // pointer to a dynamically allocated array of pointers to upvalues.
    ObjUpvalue** upvalues;
    // Storing the upvalue count in the closure is redundant because the ObjFunction that the
    // ObjClosure references also keeps that count. As usual, this weird code is to appease the GC.
    // The collector may need to know an ObjClosure’s upvalue array size after the closure’s
    // corresponding ObjFunction has already been freed.
    int upvalueCount;
} ObjClosure;

ObjClosure* newClosure(ObjFunction* function);
ObjFunction* newFunction();
ObjNative* newNative(NativeFn function);
ObjString* takeString(char* chars, int length);
ObjString* copyString(const char* chars, int length);
ObjUpvalue* newUpvalue(Value* slot);
void printObject(Value value);

// Pop quiz: Why not just put the body of this function right in the macro? What’s different about
// this one compared to the others? Right, it’s because the body uses value twice. A macro is
// expanded by inserting the argument expression every place the parameter name appears in the body.
// If a macro uses a parameter more than once, that expression gets evaluated multiple times.
// IS_STRING(POP()) -> would be POP() and then POP() again
static inline bool isObjType(Value value, ObjType type) {
    return IS_OBJ(value) && AS_OBJ(value)->type == type;
}

#endif
