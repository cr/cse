; platform.inc — the platform driver layer's constants and macros.
; Owner: doc/platform_layer.md
;
; Every platform fact of CSE — a KERNAL entry or cell, a register, a
; memory home, a size, a banking value — is a constant or a macro here,
; selected by the build's one platform define (PLATFORM_C64,
; PLATFORM_M65), or code inside a `.ifdef PLATFORM_*` block in the
; module that hosts a seam.  The contract of every name is
; doc/platform_layer.md § Seam contracts; each c64 expansion is the
; instruction sequence the C64 code has at that site, so the C64
; builds stay byte-identical (tests/fixtures/golden/c64_prg_sha256.json).

.ifndef PLATFORM_INC
PLATFORM_INC = 1

.ifndef PLATFORM_C64
  .ifndef PLATFORM_M65
    .error "platform.inc: no platform define (PLATFORM_C64 or PLATFORM_M65)"
  .endif
.endif

.endif ; PLATFORM_INC
