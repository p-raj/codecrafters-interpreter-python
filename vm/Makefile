BUILD_DIR := build
TOOL_SOURCES := tool/pubspec.lock $(shell find tool -name '*.dart')
BUILD_SNAPSHOT := $(BUILD_DIR)/build.dart.snapshot
TEST_SNAPSHOT := $(BUILD_DIR)/test.dart.snapshot

default: clox

# Run dart pub get on tool directory.
get:
	@ cd ./tool; dart pub get

clean:
	@ rm -rf $(BUILD_DIR)
	@ rm -rf gen

# Run the tests for the final version of clox.
test_clox: debug $(TEST_SNAPSHOT)
	@ dart $(TEST_SNAPSHOT) clox

$(TEST_SNAPSHOT): $(TOOL_SOURCES)
	@ mkdir -p build
	@ echo "Compiling Dart snapshot..."
	@ dart --snapshot=$@ --snapshot-kind=app-jit tool/bin/test.dart clox >/dev/null

# Compile a debug build of clox.
debug:
	@ $(MAKE) -f util/c.make NAME=cloxd MODE=debug SOURCE_DIR=.

# Compile the C interpreter.
clox:
	@ $(MAKE) -f util/c.make NAME=clox MODE=release SOURCE_DIR=.
	@ cp build/clox clox # For convenience, copy the interpreter to the top level.


# Compile the C interpreter as ANSI standard C++.
cpplox:
	@ $(MAKE) -f util/c.make NAME=cpplox MODE=debug CPP=true SOURCE_DIR=.


.PHONY: clean clox debug default test_c

