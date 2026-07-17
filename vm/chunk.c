#include "chunk.h"

#include <stdlib.h>

#include "memory.h"
#include "vm.h"

// This reduction is a key reason why our new interpreter will be faster than jlox.
// You can think of bytecode as a sort of compact serialization of the AST
// highly optimized for how the interpreter will deserialize it in the order it needs as it
// executes.
void initChunk(Chunk* chunk) {
    // how many are there
    chunk->count = 0;
    // how many it can hold
    chunk->capacity = 0;
    // line number support
    // Every time we touch the code array
    // we make a corresponding change to the line number array
    // starting with initialization.
    // In the chunk, we store a separate array of integers that parallels the bytecode
    // When a runtime error occurs, we look up the line number at the same index as
    // the current instruction’s offset in the code array.
    chunk->lines = NULL;
    // code
    chunk->code = NULL;
    // value array
    initValueArray(&chunk->constants);
}

void freeChunk(Chunk* chunk) {
    FREE_ARRAY(uint8_t, chunk->code, chunk->capacity);
    FREE_ARRAY(int, chunk->lines, chunk->capacity);
    freeValueArray(&chunk->constants);
    initChunk(chunk);
}

void writeChunk(Chunk* chunk, uint8_t byte, int line) {
    // can it hold one more?
    if (chunk->capacity < chunk->count + 1) {
        // nope
        int oldCapacity = chunk->capacity;
        chunk->capacity = GROW_CAPACITY(oldCapacity);
        chunk->code = GROW_ARRAY(uint8_t, chunk->code, oldCapacity, chunk->capacity);
        chunk->lines = GROW_ARRAY(int, chunk->lines, oldCapacity, chunk->capacity);
    }

    // get over here!
    chunk->code[chunk->count] = byte;
    chunk->lines[chunk->count] = line;
    chunk->count++;
}

int addConstant(Chunk* chunk, Value value) {
    /**
     * This quote from *[Crafting
     Interpreters](https://craftinginterpreters.com/garbage-collection.html#tracing-object-references)*
     describes a classic and nasty **garbage collection bug** where a newly created object is
     prematurely destroyed ("swept") because the virtual machine doesn't realize it is still being
     used.

     Here is a step-by-step breakdown of how this crash happens:

     ### 1. The Vulnerable State (The C Stack)

     When a new constant object (like a string literal or a number) is created during compilation,
     it is passed as an argument to the function `addConstant()`. At this exact moment:

     * The object exists in memory, but it has **not** been added to the constant table yet.
     * The *only* reference to this object is a local variable/parameter sitting on the **C stack**
     (the native execution stack of the interpreter itself, not the VM's custom values stack).

     ### 2. Triggering the Allocation

     Inside `addConstant()`, the VM tries to append this new object to its table of constants.
     However, if the table is currently full, it needs to dynamically resize (grow its capacity). To
     do this, it calls a memory management function like `reallocate()`.

     ### 3. The Trap: A Forced GC Run

     Because you are using a "stress testing" mode or have hit a memory threshold, calling
     `reallocate()` immediately triggers a garbage collection (`collectGarbage()`) to clear up space
     *before* allocating new memory.

     ### 4. The GC Blind Spot

     The garbage collector starts its **Mark Phase** to find all reachable objects. It scans the
     VM's roots: global variables, the VM value stack, active call frames, etc.

     * **The Problem:** The GC does not automatically know how to scan the native C stack
     parameters.
     * Because the new object is *only* living in that `addConstant()` function parameter on the C
     stack, the GC's wavefront completely misses it. It leaves the object unmarked (**White**).

     ### 5. The Sweep and Crash

     After marking, the GC enters the **Sweep Phase**. It looks at our brand-new constant object,
     sees that its `isMarked` flag is `false`, concludes that it is unreachable garbage, and **frees
     its memory**.

     When the GC finishes and control returns to `addConstant()`, the function tries to insert the
     object into the newly resized table. But the pointer now points to freed, unallocated, or
     corrupted memory.

     **Result:** The VM attempts to read or write to a dead object and immediately **crashes**.

     ---

     ### How to Fix It

     To fix this kind of bug, the VM developer must ensure the object is "hidden" somewhere the GC
     *does* look before any resizing happens. Usually, this means temporarily pushing the new object
     onto the VM's own stack (which the GC actively marks as a root) before calling `addConstant()`,
     and popping it off once it is safely inside the table.
     */
    // The new object being added to the constant table is passed to addConstant(). At that moment,
    // the object can be found only in the parameter to that function on the C stack. That function
    // appends the object to the constant table. If the table doesn’t have enough capacity and needs
    // to grow, it calls reallocate(). That in turn triggers a GC, which fails to mark the new
    // constant object and thus sweeps it right before we have a chance to add it to the table.
    // Crash.
    push(value);
    writeValueArray(&chunk->constants, value);
    pop();
    return chunk->constants.count - 1;
}
