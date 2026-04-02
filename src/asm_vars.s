; asm_vars.s — zero-page variables shared by asm_line.s and opcode_lookup.s
;
; All assembler I/O passes through these ZP cells; no C ABI is used across
; the C/asm boundary.  The boundary may shift; keeping everything in ZP
; lets the caller language change without touching the asm modules.
;
; Usage contract
; --------------
;   Caller sets:   al_pc, al_out, al_cpu   before calling al_line_asm.
;   asm_line sets: al_slot, al_prof, al_pidx, al_base, al_mode, al_bit.
;   al_line_asm returns: al_len = number of bytes written; C=0 on success.
;   On error: jmp al_error (imported by asm_line.s, not defined here).

        .exportzp al_pc, al_out, al_len
        .exportzp al_slot, al_prof, al_pidx, al_base, al_bit, al_mode, al_cpu
        .exportzp _al_cpu := al_cpu     ; C-visible alias
        .exportzp _al_tmp, _al_tmp2
        .exportzp sym_name, sym_val, sym_wide   ; symbol table I/O (symtab.s)
        .exportzp _sym_name := sym_name         ; C-visible aliases
        .exportzp _sym_val  := sym_val
        .exportzp _sym_wide := sym_wide
        .exportzp _al_pc    := al_pc
        .exportzp _al_out   := al_out
        .exportzp expr_ptr, expr_val, expr_wide ; expression parser I/O (expr.s)
        .exportzp _expr_ptr := expr_ptr         ; C-visible aliases
        .exportzp _expr_val := expr_val
        .exportzp _expr_wide := expr_wide

.segment "ZEROPAGE"

; ── caller-set inputs ─────────────────────────────────────────────────────────

al_pc:          .res 2  ; current PC (lo, hi) – used to compute REL/ZPREL offsets
al_out:         .res 2  ; output buffer pointer (lo, hi)
al_cpu:         .res 1  ; CPU target: 0 = 6502, 1 = 6510, 2 = 65C02
                        ;   controls CMOS mode upgrade and CMOS mode validation

; ── asm_line internal state (set during al_line_asm execution) ────────────────

al_len:         .res 1  ; bytes written to [al_out] by al_line_asm (0 if error)
al_slot:        .res 1  ; hash slot returned by mn_classify
al_prof:        .res 1  ; raw packed profile byte from mn7_profile[al_slot]
                        ;   bits 7:6 = cat  (00=legal-NMOS  01=legal+CMOS
                        ;                    10=illegal      11=CMOS-only)
                        ;   bit  5   = dir_bit (1 → direct_opcodes lookup)
                        ;   bits 4:0 = profile index (0–29)
al_pidx:        .res 1  ; effective profile index – profile after CMOS upgrade
                        ;   (= (al_prof&$1F)+1 if cat=01 and al_cpu=2, else al_prof&$1F)
al_base:        .res 1  ; base opcode from mn7_base_op[al_slot]
al_bit:         .res 1  ; bit index 0–7 for Zone D/E mnemonics (RMB,SMB,BBR,BBS)
al_mode:        .res 1  ; addressing-mode index returned by au_parse_mode (0–15)

; ── private scratch used by asm_line.s ───────────────────────────────────────
_al_tmp:        .res 1  ; general scratch byte
_al_tmp2:       .res 1  ; second scratch byte (REL offset calculation)

; ── symbol table I/O (shared with symtab.s, expr.s, asm_src.s) ──────────────
sym_name:       .res 2  ; pointer to NUL-terminated name string
sym_val:        .res 2  ; value: input for define, output for lookup
sym_wide:       .res 1  ; width flag: 0=ZP, nonzero=ABS (define input / lookup output)

; ── expression parser I/O (shared with expr.s) ─────────────────────────────
expr_ptr:       .res 2  ; input: pointer to PETSCII expression string (in/out)
expr_val:       .res 2  ; output: 16-bit result
expr_wide:      .res 1  ; output: 0=ZP-eligible, 1=force ABS
