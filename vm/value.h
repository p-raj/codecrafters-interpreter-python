#ifndef clox_value_h
#define clox_value_h

#include "common.h"

typedef struct Obj Obj;
typedef struct ObjString ObjString;

typedef enum {
    VAL_BOOL,
    VAL_NIL,
    VAL_NUMBER,
    // Lives on HEAP
    VAL_OBJ,
} ValueType;

// tagged union
typedef struct {
    ValueType type;
    union {
        bool boolean;
        double number;
        Obj* obj;
    } as;
} Value;

// clang-format off
// validations and checks
#define IS_BOOL(value)      ((value).type == VAL_BOOL)
#define IS_NIL(value)       ((value).type == VAL_NIL)
#define IS_NUMBER(value)    ((value).type == VAL_NUMBER)
#define IS_OBJ(value)    ((value).type == VAL_OBJ)
// helps us from disasters like
// Value value = BOOL_VAL(true); => double number = AS_NUMBER(value); !!!
// this is possible because of union-tags

// Conversation Macros
// to promote a clox values to native C:
#define AS_BOOL(value)      ((value).as.boolean)
#define AS_NUMBER(value)    ((value).as.number)
#define AS_OBJ(value)       ((value).as.obj)

// to promote a native C value to a clox Value:
#define BOOL_VAL(value)      ((Value){VAL_BOOL, {.boolean = value}})
#define NIL_VAL              ((Value){VAL_NIL, {.number = 0}})
#define NUMBER_VAL(value)    ((Value){VAL_NUMBER, {.number = value}})
#define OBJ_VAL(object)      ((Value){VAL_OBJ, {.obj = (Obj*)object}})
// clang-format on
// Previous value was just double
// now that we have a union-tag (tagged union)
// we need to have a way to convert the value to the real type
// typedef double Value;

// Each chunk will carry with it a list of the values that appear as literals in the program.
// To keep things simpler, we’ll put all constants in there, even simple integers.
// The constant pool is an array of values.
// The instruction to load a constant looks up the value by index in that array.
typedef struct {
    int capacity;
    int count;
    Value* values;
} ValueArray;

bool valuesEqual(Value a, Value b);
void initValueArray(ValueArray* array);
void writeValueArray(ValueArray* array, Value value);
void freeValueArray(ValueArray* array);
void printValue(Value value);

#endif
