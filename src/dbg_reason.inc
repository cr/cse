; dbg_reason.inc — the `dbg_reason` enum (one definition)
; Owner: doc/modules/debugger.md
;
; Included by every module that writes or tests dbg_reason (main.s's
; BRK/NMI handlers, repl.s's commands).  ca65 equates do not cross
; .import, so the values live here once instead of in each module.
;
; Ordered by liveness (higher = more alive): `cmp #DBG_BRK / bcs`
; identifies a resumable session in one compare.  See
; doc/modules/debugger.md § `dbg_reason` enum.

DBG_NONE = 0    ; no session (never started / ended)
DBG_RTS  = 1    ; alive-but-terminal: clean exit via brk_stub
DBG_BRK  = 2    ; resumable: breakpoint, step, cold preview, user BRK
DBG_NMI  = 3    ; resumable: NMI
