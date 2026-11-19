; zp.s — Central zero-page layout definition
; Owner: doc/modules/zp.md
;
; Single source of truth for the entire ZP allocation.  Every ZP variable
; in the project is defined here and exported.  Modules .importzp what they
; need.  The linker places this segment at $02 (per c64_trial.cfg).
;
; Total: 120 bytes ($02–$79).  First free: $7A (see the tail below).
; Allocation table and user-ZP rules: doc/modules/zp.md.

        .setcpu "6502"
ZP_S = 1                        ; platform.inc: the m65 cells are defined here
        .include "platform.inc"

.segment "ZEROPAGE"

.ifdef PLATFORM_M65
; ── the bank state and the stub's targets (m65; mem.md § Interface) ── $00
; hyppo_get_mapping writes at a page start, so um_map is the base page's
; first six bytes.  The resident stub writes the port image under the
; user map (absolute, 0.1Fxx); its CSE entries jump through the targets
; once the CSE map is back.
        .exportzp um_map, userland_zp_buf, um_d030
        .exportzp stub_brk_target, stub_nmi_target, stub_cold_target
um_map:         .res 6          ; MAP's X A Z Y operands, the two megabytes
userland_zp_buf: .res ZP_SAVE_LEN ; the user's CPU port: $00, $01
um_d030:        .res 1          ; the user's $D030
stub_brk_target: .res 2         ; where the stub's entries jump, by X:
stub_nmi_target: .res 2         ;   0 BRK, 2 NMI, 4 cold
stub_cold_target: .res 2
        .assert um_map = 0, error, "hyppo_get_mapping writes at the page start"

; ── the terminal and the geometry (m65; platform_layer.md § Display) ──
; CSE's own cursor (no KERNAL cell on m65), the key lookahead, and the
; run-time geometry io_geometry (cse_io.s) sets; named at inline sites
; through platform.inc's IO_CX / IO_CY and WIDTH / HEIGHT defines.
; The hot ones only (every character's clamp); the rest of the
; geometry is cse_io.s's BSS — the base page has no room for it.
        .exportzp io_cx, io_cy, io_key, scr_width, scr_last_col
io_cx:          .res 1          ; the cursor column
io_cy:          .res 1          ;   and row
io_key:         .res 1          ; io_kbhit's lookahead (0: none)
scr_width:      .res 1
scr_last_col:   .res 1          ; width - 1

; ── disk.s (m65; disk.md § On m65) ───────────────────────────────────
; The filename pointer DISK_LOCAL_PTR (c64: $FD): it reads only CSE's
; own view, so a plain pointer, no bank.
        .exportzp disk_local_ptr
disk_local_ptr: .res 2
.endif

; ── main.s: runtime scratch ───────────────────────────────────────────── $02
        .exportzp rp_ptr, rp_ptr2, rp_tmp, rp_tmp2
        FAR_PTR rp_ptr          ; scratch pointer (repl.s, debugger.s, mem.s)
        FAR_PTR rp_ptr2         ; scratch pointer (repl.s)
rp_tmp:         .res 1          ; scratch byte (repl.s)
rp_tmp2:        .res 1          ; scratch byte (repl.s)

; ── asm_line.s: error recovery ────────────────────────────────────────── $08
        .exportzp _asm_saved_sp
_asm_saved_sp:  .res 1          ; saved 6502 SP for asm_error recovery

; ── asm_vars: assembler I/O + symbol table + expression parser ────────── $09
        .exportzp asm_pc, asm_out, asm_cpu, asm_len
        .exportzp asm_slot, asm_prof, asm_pidx, asm_base, asm_mode
        .exportzp asm_tmp, asm_tmp2
        .exportzp sym_name, sym_val, sym_wide
        .exportzp expr_ptr, expr_val, expr_wide
        FAR_PTR asm_pc          ; current PC (lo, hi)
        FAR_PTR asm_out         ; output buffer pointer (lo, hi)
asm_cpu:        .res 1          ; CPU target: 0=6502, 1=6510, 2=65C02, 3=4510, 4=45GS02
asm_len:        .res 1          ; bytes asm_line emitted for the instruction
asm_slot:       .res 1          ; hash slot from mn_classify
asm_prof:       .res 1          ; raw packed profile byte
asm_pidx:       .res 1          ; effective profile index
asm_base:       .res 1          ; base opcode from mn7_base_op
                .res 1          ; $13 unallocated (held so later addresses stay put)
asm_mode:       .res 1          ; addressing-mode index (0–15; m65 0–19)
asm_tmp:        .res 1          ; scratch; in asm_line the digit suffix
asm_tmp2:       .res 1          ; scratch; mode_parse's ZPREL zero-page byte
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

; ── mn_classify: mnemonic classifier inputs ──────────────────────────── $24
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

; ── unallocated ───────────────────────────────────────────────────────── $2C
; One free byte, held so every later address stays put; recompaction is
; TODO § M65 A3b (it moves the user ZP, a userland-contract change).
                .res 1

; ── cse_io.s: screen I/O scratch ──────────────────────────────────────── $2D
        .exportzp _io_tmp, _io_scr
        FAR_PTR _io_tmp         ; string pointer / putdec dividend
        FAR_PTR _io_scr         ; screen row pointer for io_putc (m65: far, the screen's bank)

; ── disk.s: filename pointer ──────────────────────────────────────────── $31
        .exportzp disk_ptr
        FAR_PTR disk_ptr        ; filename pointer for disk functions

; ── expr.s: expression parser scratch ─────────────────────────────────── $33
        .exportzp _ex_tmp, _ex_digits
_ex_tmp:        .res 2          ; scratch for expression evaluation
_ex_digits:     .res 1          ; digit counter
                .res 1          ; $36 unallocated (held so later addresses stay put)

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
        FAR_PTR _dasm_ptr       ; instruction address
_dasm_opc:      .res 1          ; saved opcode byte
_dasm_mne:      .res 2          ; packed mnemonic (2 bytes)
_dasm_wptr:     .res 1          ; write index into dasm_buf
_dasm_midx:     .res 1          ; mnemonic index
_dasm_mode:     .res 1          ; mode index

; ── editor.s: gap-buffer state ────────────────────────────────────────── $49
        .exportzp gap_lo, gap_hi, buf_base, ed_top_ptr
        .exportzp read_ptr, ed_tmp, ed_scr
        FAR_PTR gap_lo          ; first byte of gap (insert point)
        FAR_PTR gap_hi          ; first byte after gap (read point)
        FAR_PTR buf_base        ; lowest address of buffer
        FAR_PTR ed_top_ptr      ; cached buffer pos for first visible line
        FAR_PTR read_ptr        ; sequential reader/save position (overlaps save_ptr)
        FAR_PTR ed_tmp          ; scratch (16-bit)
        FAR_PTR ed_scr          ; screen pointer for rendering

; ── Cross-module flags ───────────────────────────────────────────────── $57
; Shared 1-byte state bytes read across module boundaries — typically by
; a lower-layer module than the writer.  Hosting them here eliminates
; back-edges that would otherwise arise.  See doc/modules/zp.md for the
; writer/reader table.
        .exportzp in_userland, state, warm_cont, kernal_out
        .exportzp ed_dirty, dbg_reason, cur_device
in_userland:    .res 1          ; $80 = user code running (bit 7: bit/bmi), 0 = kernel
state:          .res 1          ; 0=STOP, 1=REPL, 2=EDIT
warm_cont:      .res 1          ; 0=fresh prompt, 1=replay line_buf
kernal_out:     .res 1          ; nonzero = KERNAL banked out (batch flag)
ed_dirty:       .res 1          ; buffer modified flag
dbg_reason:     .res 1          ; DBG_NONE/RTS/BRK/NMI = 0-3 (dbg_reason.inc)
cur_device:     .res 1          ; floppy device number (default 8)

; ── Current project name ─────────────────────────────────────────────── $5E
; 17-byte filename stem (FILENAME_MAX + NUL).  Written by repl.s's
; parse_ls_args; read by editor.s (status bar), asm_src.s (;asm "PROJ"
; log line + save-suggestion emitter), and repl.s (logging).  Hosting
; here eliminates asm_src→repl and editor→repl back-edges.
;
; NOTE: ZP promotion is partially effective for this 17-byte buffer —
; ~40% of access sites use `(rp_ptr2),y` indirect iteration that
; forces `abs,y` form regardless of zp placement.  See TODO.md for
; a reconsideration item if ZP space becomes tight.
        .exportzp cur_project_name
cur_project_name:       .res 17         ; FILENAME_MAX + 1

; ── Shared output-formatter scratch ──────────────────────────────────── $6F
; General repl/log working registers.  Used by:
;   - repl.s's command handlers (cmd_memory, cmd_disasm, etc.) as
;     general 16-bit address/count scratch;
;   - log.s's range-line formatters (seg_line / prg_line / free_line /
;     info_line_head / info_line_tail / _range_core) as the calling
;     convention for "range start / range end / highlight flag";
;   - log.s's range-line internals (rp_next_lo = saved screen row
;     pointer for the highlight pass).
;
; Hosting here keeps asm_src and log free of a back-edge to repl, and
; ZP addressing makes each of the ~190 access sites 1 byte shorter
; than BSS would.
        .exportzp rp_addr, rp_cnt, rp_save, rp_save2
        .exportzp rp_next_lo, _info_mode
rp_addr:        .res 2          ; working address / range start
rp_cnt:         .res 2          ; loop counter / range end
rp_save:        .res 1          ; general scratch byte
rp_save2:       .res 1          ; secondary scratch / highlight flag
rp_next_lo:     .res 2          ; 16-bit scratch (save/load ptr, range row ptr)
_info_mode:     .res 1          ; cmd_info / free_line mode flag

; ── screen ─────────────────────────────────────────────────────────── $78
; scroll_up's source-row pointer (its destination pointer reuses
; cse_io's transient _io_scr).  Here, not at the C64's free $FB–$FE:
; CSE never writes the user's ZP $80–$FF (userland_contract.md § 2).
        .exportzp scr_src
        FAR_PTR scr_src         ; scroll_up source row pointer (m65: far)

; ── First free byte ($7A) ─────────────────────────────────────────────
; User programs may use $7A–$7F (6 bytes).  __ZP_LAST__ is auto-
; generated by the linker (define=yes in cfg).
