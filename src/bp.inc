; bp.inc — the breakpoint slot's layout (breakpoints.md § Table layout)
; Owner: doc/modules/breakpoints.md
;
; Included after platform.inc by breakpoints.s and by every module that
; indexes bp_table (debugger.s, main.s, repl.s).  c64: [lo, hi, saved,
; flags]; m65: a flat address [offset lo, hi, bank, megabyte, saved,
; flags] — a breakpoint belongs to its physical byte (slice 3, F4).

.ifdef PLATFORM_M65
SLOT_SIZE = 6
BP_SAVED  = 4
BP_FLAGS  = 5
.else
SLOT_SIZE = 4
BP_SAVED  = 2
BP_FLAGS  = 3
.endif
