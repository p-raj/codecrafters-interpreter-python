"""
table.h / table.c — the hash table for pyvm.

A hash table mapping interned ObjString keys to Values.  Used for global
variables, string interning, class method tables, and instance fields.

In the C version, the table uses open addressing with linear probing and
tombstones.  We preserve that structure here for fidelity and to carry over
all the comments about load factors, tombstones, and string interning.
"""

from __future__ import annotations

from typing import Optional, TYPE_CHECKING

from pyvm.value import Value, NIL_VAL, BOOL_VAL, IS_NIL

if TYPE_CHECKING:
    from pyvm.object import ObjString

# What if we collide with every bucket?  Fortunately, that can't happen thanks
# to our load factor.  Because we grow the array as soon as it gets close to
# being full, we know there will always be empty buckets.
TABLE_MAX_LOAD: float = 0.75


# --------------------------------------------------------------------------- #
# Entry / Table
# --------------------------------------------------------------------------- #

class Entry:
    __slots__ = ("key", "value")

    def __init__(self, key: Optional["ObjString"] = None, value: Value = NIL_VAL()) -> None:
        self.key: Optional["ObjString"] = key
        self.value: Value = value


class Table:
    """The ratio of count to capacity is exactly the load factor."""

    def __init__(self) -> None:
        self.count: int = 0
        self.capacity: int = 0
        self.entries: list[Entry] = []


def init_table() -> Table:
    """void initTable(Table* table)"""
    return Table()


def free_table(table: Table) -> None:
    """void freeTable(Table* table)"""
    table.count = 0
    table.capacity = 0
    table.entries = []


# --------------------------------------------------------------------------- #
# findEntry  (open addressing + linear probing + tombstones)
# --------------------------------------------------------------------------- #

def _find_entry(entries: list[Entry], capacity: int, key: "ObjString") -> Entry:
    """static Entry* findEntry(Entry* entries, int capacity, ObjString* key)"""
    tombstone: Optional[Entry] = None
    index = key.hash % capacity
    while True:
        entry = entries[index]
        if entry.key is None:
            if IS_NIL(entry.value):
                # Empty bucket.
                return tombstone if tombstone is not None else entry
            else:
                # We found a tombstone.
                if tombstone is None:
                    tombstone = entry
        # The reason the hash table doesn't totally work is that when findEntry()
        # checks to see if an existing key matches the one it's looking for, it
        # uses == to compare two strings for equality.  That only returns true
        # if the two keys are the exact same string in memory.  Two separate
        # strings with the same characters should be considered equal, but
        # aren't.
        # SOLUTION: string interning.
        # Instead, we'll use a technique called string interning.  The core
        # problem is that it's possible to have different strings in memory with
        # the same characters.  Those need to behave like equivalent values even
        # though they are distinct objects.  They're essentially duplicates, and
        # we have to compare all of their bytes to detect that.
        # String interning is a process of deduplication.  We create a collection
        # of "interned" strings.  Any string in that collection is guaranteed to
        # be textually distinct from all others.  When you intern a string, you
        # look for a matching string in the collection.  If found, you use that
        # original one.  Otherwise, the string you have is unique, so you add it
        # to the collection.
        elif entry.key is key:
            return entry
        index = (index + 1) % capacity


# --------------------------------------------------------------------------- #
# adjustCapacity
# --------------------------------------------------------------------------- #

def _adjust_capacity(table: Table, capacity: int) -> None:
    """static void adjustCapacity(Table* table, int capacity)"""
    # Don't copy over tombstones.
    entries: list[Entry] = [Entry() for _ in range(capacity)]
    table.count = 0

    # Those new buckets may have new collisions that we need to deal with.  So
    # the simplest way to get every entry where it belongs is to rebuild the
    # table from scratch by re-inserting every entry into the new empty array.
    for i in range(table.capacity):
        entry = table.entries[i]
        if entry.key is None:
            continue
        dest = _find_entry(entries, capacity, entry.key)
        dest.key = entry.key
        dest.value = entry.value
        table.count += 1

    table.entries = entries
    table.capacity = capacity


# --------------------------------------------------------------------------- #
# Public API
# --------------------------------------------------------------------------- #

def grow_capacity(capacity: int) -> int:
    """#define GROW_CAPACITY(capacity)"""
    return 8 if capacity < 8 else capacity * 2


def table_get(table: Table, key: "ObjString") -> tuple[bool, Value]:
    """bool tableGet(Table* table, ObjString* key, Value* value)

    Returns ``(found, value)``.  Mirrors the C function which writes to a
    ``Value*`` out-parameter and returns a bool.
    """
    if table.count == 0:
        return False, NIL_VAL()

    entry = _find_entry(table.entries, table.capacity, key)
    if entry.key is None:
        return False, NIL_VAL()

    return True, entry.value


def table_set(table: Table, key: "ObjString", value: Value) -> bool:
    """bool tableSet(Table* table, ObjString* key, Value value)"""
    if table.count + 1 > table.capacity * TABLE_MAX_LOAD:
        capacity = grow_capacity(table.capacity)
        _adjust_capacity(table, capacity)

    entry = _find_entry(table.entries, table.capacity, key)
    is_new_key = entry.key is None
    if is_new_key and IS_NIL(entry.value):
        table.count += 1

    entry.key = key
    entry.value = value
    return is_new_key


def table_delete(table: Table, key: "ObjString") -> bool:
    """bool tableDelete(Table* table, ObjString* key)"""
    if table.count == 0:
        return False

    # Find the entry.
    entry = _find_entry(table.entries, table.capacity, key)
    if entry.key is None:
        return False

    # Place a <<tombstone>> in the entry.
    # Need to update find to match the value.
    entry.key = None
    entry.value = BOOL_VAL(True)
    return True


def table_add_all(src: Table, dest: Table) -> None:
    """void tableAddAll(Table* from, Table* to)"""
    for i in range(src.capacity):
        entry = src.entries[i]
        if entry.key is None:
            continue
        table_set(dest, entry.key, entry.value)


def table_find_string(table: Table, chars: str, length: int, hash_val: int) -> Optional["ObjString"]:
    """ObjString* tableFindString(Table* table, const char* chars, int length, uint32_t hash)

    To look for a string in the table, we can't use the normal table_get()
    function because that calls findEntry(), which has the exact problem with
    duplicate strings that we're trying to fix right now.  Instead, we use this
    new function.
    """
    if table.count == 0:
        return None

    index = hash_val % table.capacity
    while True:
        entry = table.entries[index]
        if entry.key is None:
            # Stop if we find an empty non-tombstone entry.
            if IS_NIL(entry.value):
                return None
        elif entry.key.length == length and entry.key.hash == hash_val and entry.key.chars == chars:
            return entry.key
        index = (index + 1) % table.capacity


def table_remove_white(table: Table) -> None:
    """void tableRemoveWhite(Table* table)"""
    # GC: We walk every entry in the table.  The string intern table uses only
    # the key of each entry—it's basically a hash set not a hash map.  If the
    # key string object's mark bit is not set, then it is a white object that
    # is moments from being swept away.  We delete it from the hash table first
    # and thus ensure we won't see any dangling pointers.
    for i in range(table.capacity):
        entry = table.entries[i]
        if entry.key is not None and not entry.key.is_marked:
            table_delete(table, entry.key)


def mark_table(table: Table) -> None:
    """void markTable(Table* table)"""
    from pyvm.memory import mark_object, mark_value
    for i in range(table.capacity):
        entry = table.entries[i]
        mark_object(entry.key)
        mark_value(entry.value)