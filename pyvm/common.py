"""
common.h — shared configuration constants and macros for pyvm.

In the C version, this header defines debug flags, the UINT8_COUNT constant,
and includes standard headers. In Python, we use module-level constants.
"""

from __future__ import annotations

import sys
from typing import Final

# --- Debug flags (mirrors the #defines in common.h) --------------------------

# When defined, the compiler disassembles the bytecode it generates.
DEBUG_PRINT_CODE: bool = False

# When defined, the VM prints the stack and disassembles each instruction before
# executing it.
DEBUG_TRACE_EXECUTION: bool = False

# When defined, the GC runs on every allocation. This is a stress-test mode to
# flush out GC bugs.
DEBUG_STRESS_GC: bool = False

# When defined, the GC logs details about what it collects.
DEBUG_LOG_GC: bool = False

# The number of distinct values a single byte can represent (0..255 inclusive).
UINT8_COUNT: Final[int] = 256