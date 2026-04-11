; asm_vars.s — zero-page variables shared by asm_line.s and opcode_lookup.s
;
; All assembler I/O passes through these ZP cells.  Keeping everything in
; ZP lets the calling convention change without touching the asm modules.
;
; Usage contract
; --------------
;   Caller sets:   asm_pc, asm_out, asm_cpu   before calling line_asm.
;   asm_line sets: asm_slot, asm_prof, asm_pidx, asm_base, asm_mode, asm_bit.
;   line_asm returns: asm_len = number of bytes written; C=0 on success.
;   On error: jmp asm_error (imported by asm_line.s, not defined here).

        .exportzp asm_pc, asm_out, asm_len
        .exportzp asm_slot, asm_prof, asm_pidx, asm_base, asm_bit, asm_mode, asm_cpu
        .exportzp asm_tmp, asm_tmp2
        .exportzp sym_name, sym_val, sym_wide   ; symbol table I/O (symtab.s)
        .exportzp expr_ptr, expr_val, expr_wide ; expression parser I/O (expr.s)

.segment "ZEROPAGE"

; ── caller-set inputs ─────────────────────────────────────────────────────────

asm_pc:         .res 2  ; current PC (lo, hi) – used to compute REL/ZPREL offsets
asm_out:        .res 2  ; output buffer pointer (lo, hi)
asm_cpu:        .res 1  ; CPU target: 0 = 6502, 1 = 6510, 2 = 65C02
                        ;   controls CMOS mode upgrade and CMOS mode validation

; ── asm_line internal state (set during line_asm execution) ─────────────────

asm_len:        .res 1  ; bytes written to [asm_out] by line_asm (0 if error)
asm_slot:       .res 1  ; hash slot returned by mn_classify
asm_prof:       .res 1  ; raw packed profile byte from mn7_profile[asm_slot]
                        ;   bits 7:6 = cat  (00=legal-NMOS  01=legal+CMOS
                        ;                    10=illegal      11=CMOS-only)
                        ;   bit  5   = dir_bit (1 → direct_opcodes lookup)
                        ;   bits 4:0 = profile index (0–29)
asm_pidx:       .res 1  ; effective profile index – profile after CMOS upgrade
                        ;   (= (asm_prof&$1F)+1 if cat=01 and asm_cpu=2, else asm_prof&$1F)
asm_base:       .res 1  ; base opcode from mn7_base_op[asm_slot]
asm_bit:        .res 1  ; bit index 0–7 for Zone D/E mnemonics (RMB,SMB,BBR,BBS)
asm_mode:       .res 1  ; addressing-mode index returned by mode_parse (0–15)

; ── private scratch used by asm_line.s ───────────────────────────────────────
asm_tmp:        .res 1  ; general scratch byte
asm_tmp2:       .res 1  ; second scratch byte (REL offset calculation)

; ── symbol table I/O (shared with symtab.s, expr.s, asm_src.s) ──────────────
sym_name:       .res 2  ; pointer to NUL-terminated name string
sym_val:        .res 2  ; value: input for define, output for lookup
sym_wide:       .res 1  ; width flag: 0=ZP, nonzero=ABS (define input / lookup output)

; ── expression parser I/O (shared with expr.s) ─────────────────────────────
expr_ptr:       .res 2  ; input: pointer to PETSCII expression string (in/out)
expr_val:       .res 2  ; output: 16-bit result
expr_wide:      .res 1  ; output: 0=ZP-eligible, 1=force ABS
