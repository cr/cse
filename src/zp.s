; zp.s — Central zero-page layout definition
;
; Single source of truth for the entire ZP allocation.  Every ZP variable
; in the project is defined here and exported.  Modules .importzp what they
; need.  The linker places this segment at $02 (per c64_trial.cfg).
;
; Total: 85 bytes ($02–$56).  First free: $57.
; User programs may use $57–$7F (41 bytes) without conflict.

        .setcpu "6502"

.segment "ZEROPAGE"

; ── main.s: runtime scratch ───────────────────────────────────────────── $02
        .exportzp rp_ptr, rp_ptr2, rp_tmp, rp_tmp2
rp_ptr:         .res 2          ; scratch pointer (repl.s, debugger.s, mem.s)
rp_ptr2:        .res 2          ; scratch pointer (repl.s)
rp_tmp:         .res 1          ; scratch byte (repl.s)
rp_tmp2:        .res 1          ; scratch byte (repl.s)

; ── asm_line.s: error recovery ────────────────────────────────────────── $08
        .exportzp _asm_saved_sp
_asm_saved_sp:  .res 1          ; saved 6502 SP for asm_error recovery

; ── asm_vars: assembler I/O + symbol table + expression parser ────────── $09
        .exportzp asm_pc, asm_out, asm_cpu, asm_len
        .exportzp asm_slot, asm_prof, asm_pidx, asm_base, asm_bit, asm_mode
        .exportzp asm_tmp, asm_tmp2
        .exportzp sym_name, sym_val, sym_wide
        .exportzp expr_ptr, expr_val, expr_wide
asm_pc:         .res 2          ; current PC (lo, hi)
asm_out:        .res 2          ; output buffer pointer (lo, hi)
asm_cpu:        .res 1          ; CPU target: 0=6502, 1=6510, 2=65C02
asm_len:        .res 1          ; bytes written by _asm_line_core
asm_slot:       .res 1          ; hash slot from mn_classify
asm_prof:       .res 1          ; raw packed profile byte
asm_pidx:       .res 1          ; effective profile index
asm_base:       .res 1          ; base opcode from mn7_base_op
asm_bit:        .res 1          ; bit index 0–7 for Zone D/E
asm_mode:       .res 1          ; addressing-mode index (0–15)
asm_tmp:        .res 1          ; general scratch byte
asm_tmp2:       .res 1          ; second scratch byte (REL offset)
sym_name:       .res 2          ; pointer to NUL-terminated name string
sym_val:        .res 2          ; 16-bit symbol value
sym_wide:       .res 1          ; width flag: 0=ZP, nonzero=ABS
expr_ptr:       .res 2          ; pointer to PETSCII expression string (in/out)
expr_val:       .res 2          ; 16-bit expression result
expr_wide:      .res 1          ; 0=ZP-eligible, 1=force ABS

; ── asm_src.s: source assembler scratch ───────────────────────────────── $21
        .exportzp _as_ptr, _as_wsize
_as_ptr:        .res 2          ; active parse pointer into current line
_as_wsize:      .res 1          ; word size or general byte scratch

; ── mn_vars.s: mnemonic classifier inputs ─────────────────────────────── $24
        .exportzp mn_c1, mn_c2, mn_c3
mn_c1:          .res 1          ; first letter (AND #$1F normalized, 1–26)
mn_c2:          .res 1          ; middle letter
mn_c3:          .res 1          ; last letter

; ── mn6/mn7: hash classifier scratch (only one linked at a time) ──────── $27
        .exportzp mn7_h_tmp, mn6_h_tmp
mn7_h_tmp:                      ; mn7: c3>>2 during fingerprint check
mn6_h_tmp:      .res 1          ; mn6: c1*8 during hash computation

; ── addr_mode.s: mode parser I/O ──────────────────────────────────────── $28
        .exportzp asm_ptr, asm_opr
asm_ptr:        .res 2          ; pointer to argument string
asm_opr:        .res 2          ; output operand bytes (lo, hi)

; ── opcode_lookup.s: scratch ──────────────────────────────────────────── $2C
        .exportzp _asm_ok_tmp
_asm_ok_tmp:    .res 1          ; cat-bits cache / zone*16

; ── cse_io.s: screen I/O scratch ──────────────────────────────────────── $2D
        .exportzp _io_tmp, _io_scr
_io_tmp:        .res 2          ; string pointer / putdec dividend
_io_scr:        .res 2          ; screen row pointer for io_putc

; ── disk.s: filename pointer ──────────────────────────────────────────── $31
        .exportzp disk_ptr
disk_ptr:       .res 2          ; filename pointer for disk functions

; ── expr.s: expression parser scratch ─────────────────────────────────── $33
        .exportzp _ex_tmp, _ex_digits, _ex_wide_tmp
_ex_tmp:        .res 2          ; scratch for expression evaluation
_ex_digits:     .res 1          ; digit counter
_ex_wide_tmp:   .res 1          ; saved wide flag for left operand

; ── symtab.s: hash table state ────────────────────────────────────────── $37
        .exportzp _st_hash, _st_idx, _st_ptr, _st_nptr, _st_heap, _st_heap_base
_st_hash:       .res 1          ; computed hash
_st_idx:        .res 1          ; current probe index
_st_ptr:        .res 2          ; pointer to current entry
_st_nptr:       .res 2          ; pointer for name comparison
_st_heap:       .res 2          ; current heap write pointer
_st_heap_base:  .res 2          ; heap base (fixed at $E600)

; ── dasm.s: disassembler scratch ──────────────────────────────────────── $41
        .exportzp _dasm_ptr, _dasm_opc, _dasm_mne, _dasm_wptr, _dasm_midx, _dasm_mode
_dasm_ptr:      .res 2          ; instruction address
_dasm_opc:      .res 1          ; saved opcode byte
_dasm_mne:      .res 2          ; packed mnemonic (2 bytes)
_dasm_wptr:     .res 1          ; write index into dasm_buf
_dasm_midx:     .res 1          ; mnemonic index
_dasm_mode:     .res 1          ; mode index

; ── editor.s: gap-buffer state ────────────────────────────────────────── $49
        .exportzp gap_lo, gap_hi, buf_base, ed_top_ptr
        .exportzp read_ptr, ed_tmp, ed_scr
gap_lo:         .res 2          ; first byte of gap (insert point)
gap_hi:         .res 2          ; first byte after gap (read point)
buf_base:       .res 2          ; lowest address of buffer
ed_top_ptr:     .res 2          ; cached buffer pos for first visible line
read_ptr:       .res 2          ; sequential reader/save position (overlaps save_ptr)
ed_tmp:         .res 2          ; scratch (16-bit)
ed_scr:         .res 2          ; screen pointer for rendering

; ── Cross-module flags (Phase 21 Move 4) ─────────────────────────────── $57
; Shared 1-byte state bytes read across module boundaries — typically by
; a lower-layer module than the writer.  Hosting them here eliminates
; back-edges that would otherwise arise.  See doc/modules/zp.md for the
; writer/reader table.
        .exportzp in_userland, state, warm_cont, kernal_out
        .exportzp ed_dirty, dbg_reason, cur_device
in_userland:    .res 1          ; 1 = user code running, 0 = kernel
state:          .res 1          ; 0=STOP, 1=REPL, 2=EDIT
warm_cont:      .res 1          ; 0=fresh prompt, 1=replay line_buf
kernal_out:     .res 1          ; nonzero = KERNAL banked out (batch flag)
ed_dirty:       .res 1          ; buffer modified flag
dbg_reason:     .res 1          ; 0=clean RTS, 1=BRK, 2=NMI
cur_device:     .res 1          ; floppy device number (default 8)

; ── First free byte ($5E) ─────────────────────────────────────────────
; __ZP_LAST__ is auto-generated by the linker (define=yes in cfg).
