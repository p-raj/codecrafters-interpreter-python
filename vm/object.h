#ifndef clox_object_h
#define clox_object_h

#include "common.h"
#include "value.h"

typedef enum {
    OBJ_STRING,
} ObjType;

// extract the type of object
#define OBJ_TYPE(value) (AS_OBJ(value)->type)

#define IS_STRING(value) isObjType(value, OBJ_STRING)
#define AS_STRING(value) ((ObjString*)AS_OBJ(value))
#define AS_CSTRING(value) (((ObjString*)AS_OBJ(value))->chars)

// C specifies that struct fields are arranged in memory in the order that they are declared. Also,
// when you nest structs, the inner struct’s fields are expanded right in place.
struct Obj {
    ObjType type;
    struct Obj* next;
};

struct ObjString {
    // You can take a pointer to a struct and safely convert it to a pointer to its first field and
    // back.
    Obj obj;
    int length;
    char* chars;
    uint32_t hash;
};

ObjString* takeString(char* chars, int length);
ObjString* copyString(const char* chars, int length);
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
