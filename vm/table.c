#include "table.h"

#include <_stdlib.h>
#include <stdint.h>
#include <stdlib.h>
#include <string.h>

#include "memory.h"
#include "object.h"
#include "value.h"

// What if we collide with every bucket? Fortunately, that can’t happen thanks to our load factor.
// Because we grow the array as soon as it gets close to being full, we know there will always be
// empty buckets.
#define TABLE_MAX_LOAD 0.75

void initTable(Table* table) {
    table->count = 0;
    table->capacity = 0;
    table->entries = NULL;
}

void freeTable(Table* table) {
    FREE_ARRAY(Entry, table->entries, table->capacity);
    initTable(table);
}

static Entry* findEntry(Entry* entries, int capacity, ObjString* key) {
    Entry* tombstone = NULL;
    uint32_t index = key->hash % capacity;
    for (;;) {
        Entry* entry = &entries[index];
        if (entry->key == NULL) {
            if (IS_NIL(entry->value)) {
                return tombstone != NULL ? tombstone : entry;
            } else {
                if (tombstone == NULL) tombstone = entry;
            }
        }
        // The reason the hash table doesn’t totally work is that when findEntry() checks to see if
        // an existing key matches the one it’s looking for, it uses == to compare two strings for
        // equality. That only returns true if the two keys are the exact same string in memory. Two
        // separate strings with the same characters should be considered equal, but aren’t.
        // SOLUTION : string interning
        // Instead, we’ll use a technique called string interning. The core problem is that it’s
        // possible to have different strings in memory with the same characters. Those need to
        // behave like equivalent values even though they are distinct objects. They’re essentially
        // duplicates, and we have to compare all of their bytes to detect that.
        // String interning is a process of deduplication. We create a collection of “interned”
        // strings. Any string in that collection is guaranteed to be textually distinct from all
        // others. When you intern a string, you look for a matching string in the collection. If
        // found, you use that original one. Otherwise, the string you have is unique, so you add it
        // to the collection.
        else if (entry->key == key) {
            return entry;
        }
        index = (index + 1) % capacity;
    }
}

static void adjustCapacity(Table* table, int capacity) {
    // dont copy over tombstones
    Entry* entries = ALLOCATE(Entry, capacity);
    table->count = 0;
    for (int i = 0; i < capacity; i++) {
        entries[i].key = NULL;
        entries[i].value = NIL_VAL;
    }

    // Those new buckets may have new collisions that we need to deal with. So the simplest way to
    // get every entry where it belongs is to rebuild the table from scratch by re-inserting every
    // entry into the new empty array.
    for (int i = 0; i < table->capacity; i++) {
        Entry* entry = &table->entries[i];
        if (entry->key == NULL) continue;

        Entry* dest = findEntry(entries, capacity, entry->key);
        dest->key = entry->key;
        dest->value = entry->value;
        table->count++;
    }

    FREE_ARRAY(Entry, table->entries, table->capacity);
    table->entries = entries;
    table->capacity = capacity;
}

bool tableGet(Table* table, ObjString* key, Value* value) {
    if (table->count == 0) return false;

    Entry* entry = findEntry(table->entries, table->capacity, key);
    if (entry->key == NULL) return false;

    *value = entry->value;
    return true;
}

bool tableSet(Table* table, ObjString* key, Value value) {
    if (table->count + 1 > table->capacity * TABLE_MAX_LOAD) {
        int capacity = GROW_CAPACITY(table->capacity);
        adjustCapacity(table, capacity);
    }
    Entry* entry = findEntry(table->entries, table->capacity, key);
    bool isNewKey = entry->key == NULL;
    if (isNewKey && IS_NIL(entry->value)) table->count++;
    // if (isNewKey) table->count++;

    entry->key = key;
    entry->value = value;
    return isNewKey;
}

bool tableDelete(Table* table, ObjString* key) {
    if (table->count == 0) return false;

    // Find the entry.
    Entry* entry = findEntry(table->entries, table->capacity, key);
    if (entry->key == NULL) return false;

    // Place a <<tombstone>> in the entry.
    // need to update the find to match the value
    entry->key = NULL;
    entry->value = BOOL_VAL(true);
    return true;
}

void tableAddAll(Table* from, Table* to) {
    for (int i = 0; i < from->capacity; i++) {
        Entry* entry = &from->entries[i];
        if (entry->key == NULL) continue;
        tableSet(to, entry->key, entry->value);
    }
}

ObjString* tableFindString(Table* table, const char* chars, int length, uint32_t hash) {
    if (table->count == 0) return NULL;

    uint32_t index = hash % table->capacity;
    for (;;) {
        Entry* entry = &table->entries[index];
        if (entry->key == NULL) {
            // Stop if we find an empty non-tombstone entry.
            if (IS_NIL(entry->value)) return NULL;
        } else if (entry->key->length == length && entry->key->hash == hash &&
                   memcmp(entry->key->chars, chars, length) == 0) {
            return entry->key;
        }
        index = (index + 1) % table->capacity;
    }
}

void tableRemoveWhite(Table* table) {
    // GC: We walk every entry in the table. The string intern table uses only the key of each
    // entry—it’s basically a hash set not a hash map. If the key string object’s mark bit is not
    // set, then it is a white object that is moments from being swept away. We delete it from the
    // hash table first and thus ensure we won’t see any dangling pointers.
    for (int i = 0; i < table->capacity; i++) {
        Entry* entry = &table->entries[i];
        if (entry->key != NULL && !entry->key->obj.isMarked) {
            tableDelete(table, entry->key);
        }
    }
}

void markTable(Table* table) {
    for (int i = 0; i < table->capacity; i++) {
        Entry* entry = &table->entries[i];
        markObject((Obj*)entry->key);
        markValue(entry->value);
    }
}
