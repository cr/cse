/* ═══════════════════════════════════════════════════════════════
 * REPL — command line interface
 *
 * The screen IS the command buffer.  Press RETURN on any line
 * to execute it.  AAAA:cmd [args] for addressed commands,
 * cmd [args] for bare commands.  ';' ends parsing.
 * ═══════════════════════════════════════════════════════════════ */

#include <c64.h>
#include <string.h>
#include <stdint.h>
#include "cse.h"
#include "cse_io.h"
#include "screen.h"
#include "disk.h"
#include "repl.h"
#include "editor.h"
#include "asm_src.h"
#include "expr.h"
#include "symtab.h"

/* row * 40 via shifts — avoids pulling in cc65 tosumula0 runtime */
#define ROW_OFFSET(r) (((uint16_t)(r) << 5) + ((uint16_t)(r) << 3))

/* ── REPL state ─────────────────────────────────────────── */
uint16_t cur_addr = 0x1000;
uint8_t  cur_device = 8;
static uint8_t  last_cmd = 0;
static uint16_t block_size = 0x10;
char cur_filename[FILENAME_MAX_LEN + 1] = "";

/* ── Decimal digit extraction via subtraction ─────────── */

static const uint16_t _dec_pow[] = { 10000, 1000, 100, 10, 1 };

/* Write up to 5 decimal digits of val, space-padded on left.
 * Suitable for right-aligned 5-digit display. */
static void put_dec5_sp(uint16_t val)
{
    uint8_t i, started = 0;
    for (i = 0; i < 5; ++i) {
        uint8_t d = 0;
        while (val >= _dec_pow[i]) { val -= _dec_pow[i]; ++d; }
        if (d || started || i == 4) { io_putc('0' + d); started = 1; }
        else io_putc(' ');
    }
}

/* Convert uint16_t to decimal string (NUL-terminated, up to 5 digits).
 * Returns length. */
static uint8_t utoa_sub(uint16_t n, char *buf)
{
    uint8_t pos = 0, i, started = 0;
    for (i = 0; i < 5; ++i) {
        uint8_t d = 0;
        while (n >= _dec_pow[i]) { n -= _dec_pow[i]; ++d; }
        if (d || started || i == 4) { buf[pos++] = '0' + d; started = 1; }
    }
    buf[pos] = 0;
    return pos;
}

static const char flag_ch[] = "nv-bdizc";
static const char bp_pfx[]  = "; bp ";

/* ── Common patterns factored out ──────────────────────── */

/* newline + clear — advance to next line and clear it for the main loop */
static void nl_clear(void) { newline(); clear_eol(); }

/* Print XXXX:C (address, colon, command char) at column 0 */
static void io_addr_cmd(uint16_t addr, char ch) {
    io_cx = 0;
    io_puthex4(addr); io_putc(':'); io_putc(ch);
}

/* error message on next line — caller handles nl_clear */
static void err_msg(const char *msg) {
    newline(); io_puts(msg); clear_eol();
}

/* parse 2 or 4 hex digits from *q, return value.
 * Returns 0 if no hex found. Advances *q. */
static uint16_t parse_hex_flex(uint8_t **q) {
    if (is_hex((*q)[0]) && is_hex((*q)[1])) {
        if (is_hex((*q)[2]) && is_hex((*q)[3]))
            return parse_hex4(q);
        return parse_hex2(q);
    }
    return 0;
}

/* Evaluate an expression at *q.  Returns 1 on success (result in
 * *result, *q advanced).  Returns 0 if *q is empty or on error
 * (error message printed).  Caller can distinguish "no arg" from
 * "error" by checking whether *q pointed at a non-empty string. */
static uint8_t try_expr(uint8_t **q, uint16_t *result) {
    uint8_t rc;
    skip_sp(q);
    if (!**q || **q == ';') return 0;
    *(uint16_t *)expr_ptr = (uint16_t)*q;
    rc = expr_eval();
    *q = *(uint8_t **)expr_ptr;
    if (rc <= 1) { *result = expr_val; return 1; }
    newline(); io_puts(";?"); io_puts(expr_error_str()); clear_eol();
    return 0;
}

/* ═══════════════════════════════════════════════════════════════
 * Screen line I/O
 * ═══════════════════════════════════════════════════════════════ */

static uint8_t line_buf[42];

void read_line(void) {
    uint8_t *src = SCREEN + ROW_OFFSET(io_cy);
    uint8_t  i, sc;
    for (i = 0; i < SCREEN_WIDTH; ++i) {
        sc = src[i] & 0x7F;
        /* CC65 -O BUG #1: if/else instead of ternary.  cc65 -O
         * miscompiles the ternary (uses wrong stack offset for the
         * identity branch).  NOT an asm-port concern.  See also
         * CC65 -O BUG #2 in cmd_step. */
        if (sc < 0x20)
            line_buf[i] = sc + 0x40;       /* lowercase screen → $41-$5A */
        else if (sc >= 0x41 && sc <= 0x5A)
            line_buf[i] = sc + 0x80;       /* uppercase screen → $C1-$DA */
        else
            line_buf[i] = sc;
    }
    i = SCREEN_WIDTH;
    while (i > 0 && line_buf[i - 1] == ' ') --i;
    line_buf[i] = 0;
    /* ';' is NOT cut here — it acts as a command if first char,
     * or as a natural wall for arg parsers (is_hex/skip_sp stop at it). */
}

void show_prompt(void) {
    io_cx = 0;
    io_puthex4(cur_addr);
    io_putc(':');
}

/* ═══════════════════════════════════════════════════════════════
 * Stub disassembler
 * ═══════════════════════════════════════════════════════════════ */

extern uint8_t __fastcall__ dasm_insn(uint16_t addr);
extern char dasm_buf[];

/* ═══════════════════════════════════════════════════════════════
 * Line emitters
 * ═══════════════════════════════════════════════════════════════ */

static uint8_t emit_dot(uint16_t addr) {
    uint8_t olen, i;
    olen = dasm_insn(addr);             /* disassemble first to get length */
    io_addr_cmd(addr, '.');
    io_putc(' ');                           /* 2 spaces before hex */
    for (i = 0; i < 3; ++i) {
        if (i < olen) {
            io_putc(' '); io_puthex2(((uint8_t *)addr)[i]);
        } else {
            io_puts("   ");
        }
    }
    io_puts("  ");                          /* 2 spaces before mnemonic */
    io_puts(dasm_buf);
    clear_eol();
    return olen;
}

static void emit_mem(uint16_t addr, uint8_t cols) {
    uint8_t *base = (uint8_t *)addr;
    uint8_t  i, b;
    if (cols == 0) cols = 8;
    if (cols > 8)  cols = 8;
    io_addr_cmd(addr, 'm');
    for (i = 0; i < 8; ++i) {
        if (i < cols) {
            io_putc(' '); io_puthex2(base[i]);
        } else {
            io_puts("   ");
        }
    }
    io_putc(' ');
    for (i = 0; i < cols; ++i) {
        b = base[i];
        io_putc((b >= 0x20 && b <= 0x7E) ? b : '.');
    }
    clear_eol();
}

static void emit_reg(void) {
    uint8_t i, p;
    io_cx = 0;
    io_puts("r pc:"); io_puthex4(brk_pc);
    io_puts(" a:"); io_puthex2(reg_a);
    io_puts(" x:"); io_puthex2(reg_x);
    io_puts(" y:"); io_puthex2(reg_y);
    io_puts(" s:"); io_puthex2(reg_sp);
    io_putc(' ');
    p = reg_p;
    for (i = 0; i < 8; ++i) {
        io_putc((p & 0x80) ? flag_ch[i] : '.');
        p <<= 1;
    }
    clear_eol();
}

/* ═══════════════════════════════════════════════════════════════
 * dot_assemble — assemble mnemonic+operand with expression support
 *
 * Evaluates the operand expression via expr_eval, formats the result
 * as a hex literal, and passes the formatted string to asm_line.
 * Prefix (#, () and suffix (,x ,y ),y etc.) are preserved.
 * Returns byte count from asm_line (0 = error).
 * ═══════════════════════════════════════════════════════════════ */
static uint8_t dot_assemble(uint16_t addr, uint8_t *text)
{
    static char buf[24];     /* "mne #($xxxx,x)" + NUL */
    uint8_t *p = text, *bp = (uint8_t *)buf;
    uint8_t rc;
    uint16_t val;

    /* Copy mnemonic (letters until space/NUL/;) */
    while (*p >= 'a' && *p <= 'z' && bp < (uint8_t *)buf + 8)
        *bp++ = *p++;
    /* Skip spaces between mnemonic and operand */
    skip_sp(&p);
    if (*p == 0 || *p == ';') {
        /* No operand — implied/accumulator */
        *bp = 0;
        return asm_line(addr, buf);
    }
    *bp++ = ' ';

    /* Copy prefix: # and/or ( */
    if (*p == '#') { *bp++ = *p++; skip_sp(&p); }
    if (*p == '(') { *bp++ = *p++; skip_sp(&p); }

    /* Evaluate expression */
    *(uint16_t *)expr_ptr = (uint16_t)p;
    rc = expr_eval();
    if (rc >= 2) return 0;
    val = expr_val;
    p = *(uint8_t **)expr_ptr;  /* advanced past expression */

    /* Format as $XX or $XXXX based on width */
    *bp++ = '$';
    if (rc == 1) { /* ABS — 4 hex digits */
        *bp++ = hex_val_to_char((val >> 12) & 0xF);
        *bp++ = hex_val_to_char((val >> 8) & 0xF);
    }
    *bp++ = hex_val_to_char((val >> 4) & 0xF);
    *bp++ = hex_val_to_char(val & 0xF);

    /* Copy suffix: ),y  ,x  ,y  ) etc. until NUL or ; */
    skip_sp(&p);
    while (*p && *p != ';' && bp < (uint8_t *)buf + 22)
        *bp++ = *p++;
    *bp = 0;

    return asm_line(addr, buf);
}

/* ═══════════════════════════════════════════════════════════════
 * Command handlers
 * ═══════════════════════════════════════════════════════════════ */

static void cmd_dot(uint8_t *args)
{
    uint16_t addr = cur_addr;
    uint8_t  bytes[3], nbytes, olen, i, changed;
    uint8_t *q = args, *mne;

    skip_sp(&q);
    nbytes = 0;
    while (nbytes < 3 && is_hex(*q) && is_hex(*(q + 1))
           && (*(q + 2) == ' ' || *(q + 2) == 0 || *(q + 2) == ';')) {
        bytes[nbytes++] = parse_hex2(&q);
        skip_sp(&q);
    }

    changed = 0;
    for (i = 0; i < nbytes; ++i) {
        if (bytes[i] != ((uint8_t *)addr)[i]) {
            changed = 1;
            break;
        }
    }

    if (changed) {
        for (i = 0; i < nbytes; ++i)
            ((uint8_t *)addr)[i] = bytes[i];
    } else {
        skip_sp(&q);
        mne = q;
        if (*mne >= 'a' && *mne <= 'z') {
            nbytes = dot_assemble(addr, mne);
            if (nbytes == 0) {
                err_msg(";?asm"); nl_clear(); return;
            }
        }
    }

    olen = emit_dot(addr);
    cur_addr = addr + olen;
    newline();
    if (!nbytes) clear_eol();
}

static void cmd_disasm(uint8_t *args)
{
    uint16_t addr = cur_addr;
    uint16_t end;
    (void)args;

    end = addr + block_size;
    if (end < addr) end = 0xFFFF;

    while (addr < end) {
        addr += emit_dot(addr);
        newline();
        if (addr == 0) break;
    }

    cur_addr = addr;
    clear_eol();
}

static void cmd_mem(uint8_t *args)
{
    uint16_t addr = cur_addr;
    uint8_t  *q = args;
    uint8_t  nbytes, cols;
    uint16_t remaining;

    skip_sp(&q);

    /* 4-digit hex = address override (not edit bytes) */
    if (is_hex(q[0]) && is_hex(q[1]) && is_hex(q[2]) && is_hex(q[3])
        && (q[4] == ' ' || q[4] == 0 || q[4] == ';')) {
        addr = parse_hex4(&q);
        skip_sp(&q);
    }

    /* 2+ hex digits followed by space/end = edit bytes */
    if (is_hex(q[0]) && is_hex(q[1])
        && (q[2] == ' ' || q[2] == 0 || q[2] == ';')) {
        nbytes = 0;
        while (nbytes < 8 && is_hex(*q) && is_hex(*(q + 1))) {
            uint8_t b = parse_hex2(&q);
            if (b != ((uint8_t *)addr)[nbytes])
                ((uint8_t *)addr)[nbytes] = b;
            ++nbytes;
            skip_sp(&q);
        }
        emit_mem(addr, nbytes);
        cur_addr = addr + nbytes;
        if (cur_addr < addr) cur_addr = 0;
        newline();
        return;
    }

    remaining = block_size;

    while (remaining > 0) {
        cols = (remaining >= 8) ? 8 : (uint8_t)remaining;
        emit_mem(addr, cols);
        addr += cols;
        remaining -= cols;
        newline();
        if (addr < cols) break;
    }

    cur_addr = addr;
    clear_eol();
}

/* Common tail: register dump + disassembly at brk_pc */
static void show_regs_at_pc(void)
{
    newline();
    emit_reg();
    newline();
    cur_addr = brk_pc;
    emit_dot(brk_pc);
    nl_clear();
}

/* Show break info (brk/nmi line) + register dump + disassembly */
static void show_break_result(void)
{
    restore_colors();
    newline();
    if (dbg_reason == 1) {
        io_puts("; brk");
        if (dbg_bp_hit != 0xFF) {
            io_putc(' ');
            io_putc('1' + dbg_bp_hit);
        }
        io_puts(" at $");
        io_puthex4(brk_pc);
    } else if (dbg_reason == 2) {
        io_puts("; nmi break at $");
        io_puthex4(brk_pc);
    }
    clear_eol();
    show_regs_at_pc();
}

static void cmd_jmp(void)
{
    brk_pc = cur_addr;
    if (dbg_bp_count()) {
        /* Breakpoints active: run via debugger, break on BRK/NMI */
        dbg_enter();
        show_break_result();
    } else {
        /* No breakpoints: simple JSR, show regs on RTS */
        jsr_addr(cur_addr);
        restore_colors();
        show_regs_at_pc();
    }
}

/* ── t/n commands: single-step / step-over ─────────────── */

/* Read byte at 16-bit address */
#define RD8(a)  (*(uint8_t *)(a))
/* Read little-endian word at 16-bit address */
#define RD16(a) ((uint16_t)RD8(a) | ((uint16_t)RD8((uint16_t)(a) + 1) << 8))

static void cmd_step(uint8_t *args, uint8_t is_next)
{
    uint16_t count, i;
    uint8_t  opc;
    uint16_t next_lo, next_hi;

    /* Cold start: no break context yet — establish one at cur_addr */
    if (dbg_reason == 0) {
        brk_pc = cur_addr;
        dbg_reason = 1;
    }

    /* Parse count (hex); bare t/o defaults to block_size */
    {
        uint8_t *q = args;
        skip_sp(&q);
        if (is_hex(*q)) {
            /* Accept 1-4 hex digits (parse_hex_flex requires 2+) */
            uint16_t v;
            if (is_hex(q[1]))
                v = parse_hex_flex(&q);
            else
                { v = hex_val(*q); ++q; }
            count = v ? v : block_size;
        } else {
            count = block_size;
        }
    }

    opc = 0;

    for (i = 0; i < count; ++i) {
        opc = RD8(brk_pc);
        next_lo = 0;
        next_hi = 0;

        /* ── Compute next-PC(s) ── */
        if (opc == 0x00) {
            /* BRK: don't step into the vector */
            break;
        } else if (opc == 0x20) {
            /* JSR abs */
            if (is_next)
                next_lo = brk_pc + 3;               /* step over */
            else
                next_lo = RD16(brk_pc + 1);         /* step into */
        } else if (opc == 0x60 || opc == 0x40) {
            /* RTS/RTI: break before executing (handled below) */
        } else if (opc == 0x4C) {
            /* JMP abs */
            next_lo = RD16(brk_pc + 1);
        } else if (opc == 0x6C) {
            /* JMP (ind) */
            next_lo = RD16(RD16(brk_pc + 1));
#ifdef CMOS_SUPPORT
        } else if (opc == 0x7C && al_cpu >= 2) {
            /* JMP (abs,x) — 65C02 only */
            next_lo = RD16(RD16(brk_pc + 1) + reg_x);
        } else if (opc == 0x80 && al_cpu >= 2) {
            /* BRA — 65C02 unconditional relative */
            int8_t rel = (int8_t)RD8(brk_pc + 1);
            next_lo = brk_pc + 2 + rel;
#endif
        } else if ((opc & 0x1F) == 0x10) {
            /* Conditional branch Bxx */
            int8_t rel = (int8_t)RD8(brk_pc + 1);
            next_lo = brk_pc + 2 + rel;   /* taken */
            next_hi = brk_pc + 2;         /* not taken */
        } else {
            /* Linear: advance by instruction length.
             * CC65 -O BUG #2: cc65 -O fails to zero-extend the
             * uint8_t return of dasm_insn before 16-bit addition
             * (X register has garbage from dasm_insn internals,
             * tosaddax uses it as the high byte → wrong address).
             * Workaround: store to uint8_t local first, then add.
             * NOT an asm-port concern.  See also CC65 -O BUG #1
             * in read_line. */
            {   uint8_t len = dasm_insn(brk_pc);
                next_lo = brk_pc + len;
            }
        }

        /* Unknown target (including RTS/RTI) → stop before executing */
        if (next_lo == 0) break;

        /* ── Arm step BRKs ── */
        dbg_step_clear();
        step_bp[0] = (uint8_t)next_lo;
        step_bp[1] = (uint8_t)(next_lo >> 8);
        /* step_bp[2] = 0 (cleared); filled by step_patch */
        step_bp[3] = 1;  /* enabled */
        if (next_hi) {
            step_bp[4] = (uint8_t)next_hi;
            step_bp[5] = (uint8_t)(next_hi >> 8);
            /* step_bp[6] = 0 (cleared) */
            step_bp[7] = 1;
        }

        /* ── Enter user code for one instruction ── */
        dbg_enter();

        /* ── NMI or regular breakpoint interrupted the step sequence ── */
        if (dbg_reason == 2 || dbg_bp_hit != 0xFF) {
            dbg_step_clear();
            show_break_result();
            return;
        }
    }

    /* Normal completion: register dump + disassembly at brk_pc */
    show_regs_at_pc();

    /* RTS/RTI: clear repeat so RETURN doesn't step into garbage */
    if (opc == 0x60 || opc == 0x40) last_cmd = 0;
}

/* ── x command: breakpoints ────────────────────────────── */
static void cmd_brk(uint8_t *args)
{
    uint8_t *q = args;
    uint8_t i, slot;

    skip_sp(&q);

    if (*q == 0) {
        /* x — list all breakpoints */
        newline();
        for (i = 0; i < 8; ++i) {
            uint16_t addr = bp_table[i*4] | ((uint16_t)bp_table[i*4+1] << 8);
            io_puts(bp_pfx);
            io_putc('1' + i);
            io_puts(": ");
            if (addr) {
                io_putc('$');
                io_puthex4(addr);
            } else {
                io_puts("----");
            }
            clear_eol();
            newline();
        }
        clear_eol();
        return;
    }

    if (*q == '*') {
        /* x * — delete all */
        dbg_bp_clear();
        newline();
        io_puts("; breakpoints cleared");
        clear_eol(); nl_clear();
        return;
    }

    if (*q == '-') {
        /* x -N — delete slot N (1-based display, 0-based internal) */
        ++q;
        if (*q >= '1' && *q <= '8') {
            slot = *q - '1';
            dbg_bp_del(slot);
            newline();
            io_puts(bp_pfx);
            io_putc(*q);
            io_puts(" deleted");
        } else {
            newline();
            io_puts(";?slot 1-8");
        }
        clear_eol(); nl_clear();
        return;
    }

    /* x ADDR — set breakpoint */
    {   uint16_t addr;
        if (try_expr(&q, &addr)) {
            slot = dbg_bp_set(addr);
            newline();
            if (slot != 0xFF) {
                io_puts(bp_pfx);
                io_putc('1' + slot);
                io_puts(": $");
                io_puthex4(addr);
            } else {
                io_puts(";?bp full");
            }
            clear_eol(); nl_clear();
            return;
        }
    }

    err_msg(";?b"); nl_clear();
}

static uint8_t parse_regval(uint8_t **pp)
{
    uint8_t *q = *pp;
    uint8_t v;
    q += 2;
    v = (hex_val(q[0]) << 4) | hex_val(q[1]);
    q += 2;
    *pp = q;
    return v;
}

static void cmd_reg(uint8_t *args)
{
    uint8_t *q = args, i, p;

    skip_sp(&q);

    if (*q) {
        reg_a  = parse_regval(&q); skip_sp(&q);
        reg_x  = parse_regval(&q); skip_sp(&q);
        reg_y  = parse_regval(&q); skip_sp(&q);
        reg_sp = parse_regval(&q); skip_sp(&q);

        p = 0;
        for (i = 0; i < 8; ++i) {
            p <<= 1;
            if (*q == (uint8_t)flag_ch[i]) p |= 1;
            if (*q) ++q;
        }
        reg_p = p;
    }

    newline();
    emit_reg();
    nl_clear();
}

/* Check if filename ends with ",s" (SEQ file type suffix).
 * Returns 1 if SEQ, 0 if PRG/default. */
static uint8_t is_seq_file(const uint8_t *name)
{
    uint8_t len = strlen((const char *)name);
    if (len >= 2 && name[len-2] == ',' && (name[len-1] == 's' || name[len-1] == 'S'))
        return 1;
    return 0;
}

/* ── Parse a quoted filename from args.  Returns pointer to the
 *    name (NUL-terminated in place), or NULL on error.
 *    Advances *pp past the closing quote and any trailing space. */
static uint8_t *parse_filename(uint8_t **pp)
{
    uint8_t *q = *pp;
    uint8_t *name;

    skip_sp(&q);

    /* accept with or without quotes */
    if (*q == '"') {
        ++q;
        name = q;
        while (*q && *q != '"') ++q;
        if (*q == '"') *q++ = 0;          /* NUL-terminate, skip quote */
    } else {
        name = q;
        while (*q && *q != ' ') ++q;      /* space-delimited */
        if (*q) *q++ = 0;
    }
    skip_sp(&q);
    *pp = q;
    return (*name) ? name : 0;
}

/* Parse and remember filename.  Returns name pointer or NULL. */
static uint8_t *get_filename(uint8_t **q) {
    uint8_t *name = parse_filename(q);
    if (!name) {
        if (cur_filename[0]) return (uint8_t *)cur_filename;
        return 0;
    }
    strncpy(cur_filename, (char *)name, FILENAME_MAX_LEN);
    cur_filename[FILENAME_MAX_LEN] = 0;
    return name;
}

/* Print "; "name": " prefix for file operations */
static void io_quoted_name(const char *name) {
    io_puts("; \""); io_puts(name); io_puts("\": ");
}

/* Print "name: N lines, M bytes" for SEQ file result */
static void print_seq_stats(const char *name) {
    io_quoted_name(name);
    io_putdec(ed_save_lines); io_puts(" lines, ");
    io_putdec(ed_save_bytes); io_puts(" bytes");
}

/* Print ";?load name" or ";?save name" error */
static void io_err_load(const char *name) { io_puts(";?load "); io_puts(name); }
static void io_err_save(const char *name) { io_puts(";?save "); io_puts(name); }

/* Common disk-op footer: clear_eol, newline, drive status, prompt */
static void disk_done(void) {
    clear_eol(); newline(); floppy_status(); nl_clear();
}

static void cmd_load(uint8_t *args)
{
    uint16_t addr = cur_addr;
    uint8_t *q = args;
    uint8_t *name = get_filename(&q);
    if (!name) { err_msg(";?name"); nl_clear(); return; }

    newline();
    if (is_seq_file(name)) {
        uint8_t err = ed_load_source((char *)name);
        if (err) io_err_load((char *)name);
        else print_seq_stats((char *)name);
    } else {
        uint16_t result = disk_load_prg((char *)name, addr);
        if (result == 0) io_err_load((char *)name);
        else {
            io_quoted_name((char *)name);
            io_putdec(result); io_puts(" bytes at ");
            io_puthex4(addr ? addr : result);
        }
    }
    disk_done();
}

static void cmd_write(uint8_t *args)
{
    uint16_t addr = cur_addr;
    uint8_t *q = args;
    uint8_t *name = get_filename(&q);
    uint8_t err;
    if (!name) { err_msg(";?name"); nl_clear(); return; }

    newline();
    if (is_seq_file(name)) {
        ed_ensure_init();
        err = ed_save_source((char *)name);
        if (err) io_err_save((char *)name);
        else print_seq_stats((char *)name);
    } else {
        uint16_t end = 0;
        uint16_t size;
        try_expr(&q, &end);
        if (!end) end = addr + block_size;
        if (end <= addr) { err_msg(";?range"); nl_clear(); return; }
        size = end - addr;
        err = disk_save_prg((char *)name, addr, size);
        if (err) io_err_save((char *)name);
        else {
            io_quoted_name((char *)name);
            io_putdec(size); io_puts(" bytes ");
            io_puthex4(addr); io_putc('-'); io_puthex4(end - 1);
        }
    }
    disk_done();
}

/* print one info line: "tag  AAAA-BBBB description" */
/* if inv is set, print in reverse video               */
static void info_line(uint8_t inv, const char *tag,
                      uint16_t lo, uint16_t hi, const char *desc)
{
    uint8_t *scr = SCREEN + ROW_OFFSET(io_cy);
    uint8_t col;
    io_cx = 0;
    io_putc(';');
    io_puts(tag);
    { uint8_t pad = 4 - strlen(tag); while (pad--) io_putc(' '); }
    io_putc(' ');
    io_puthex4(lo); io_putc('-'); io_puthex4(hi);
    io_putc(' ');
    io_puts(desc);
    col = io_cx;
    /* pad + optional invert */
    if (inv) {
        uint8_t i;
        for (i = 0; i < col; ++i) scr[i] |= 0x80;
        while (col < SCREEN_WIDTH) scr[col++] = 0xA0;
    } else {
        while (col < SCREEN_WIDTH) scr[col++] = 0x20;
    }
    newline();
}

static void free_line(uint16_t lo, uint16_t hi)
{
    char fbuf[20];
    uint8_t pos;
    pos = utoa_sub(hi - lo + 1, fbuf);
    memcpy(fbuf + pos, " bytes free", 12);  /* 11 chars + NUL */
    info_line(1, "work", lo, hi, fbuf);
}

static void cmd_info(void)
{
    uint16_t cse_hi  = cse_end();
    uint16_t cstk_lo = 0xC800;
    uint16_t free_lo, free_hi;

    newline();

    /* $0000-$00FF: zero page */
    info_line(0, "cpu",  0x0000, 0x0001, "i/o port");
    info_line(0, "zp",   0x0002, cse_zp_end() - 1, "cse (saved on j)");
    free_line(cse_zp_end(), 0x007f);
    info_line(0, "zp",   0x0080, 0x00ff, "kernal");

    /* $0100-$07FF: stack, system, screen */
    info_line(0, "stk",  0x0100, 0x01ff, "6502 stack");
    info_line(0, "sys",  0x0200, 0x03ff, "kernal work");
    info_line(0, "scr",  0x0400, 0x07ff, "screen+sprites");

    /* $0800+: CSE code, then free, then allocations, then cstk */
    info_line(0, "cse",  cse_start(), cse_hi - 1, "code+data+bss");

    /* free region: from end of CSE to start of first allocation above */
    free_lo = cse_hi;
    free_hi = cstk_lo - 1;

    /* source eats into the top of the free region */
    if (src_bot) free_hi = (uint16_t)src_bot - 1;

    if (free_lo <= free_hi)
        free_line(free_lo, free_hi);

    /* show allocations */
    if (src_bot)
        info_line(0, "src", (uint16_t)src_bot,
                  (uint16_t)src_top - 1, "source code");

    /* c stack and I/O */
    info_line(0, "cstk", cstk_lo, 0xcfff, "c stack");
    info_line(0, "io",   0xd000, 0xdfff, "vic/sid/cia");
    info_line(0, "kern", 0xe000, 0xffff, "kernal rom");

    clear_eol();
}

/* ═══════════════════════════════════════════════════════════════
 * Command dispatcher
 * ═══════════════════════════════════════════════════════════════ */

void exec_line(void)
{
    uint8_t *q = line_buf;
    uint8_t  cmd;

    skip_sp(&q);

    /* ── Parse optional AAAA: prefix → sets cur_addr ─────── */
    if (is_hex(q[0]) && is_hex(q[1]) && is_hex(q[2]) && is_hex(q[3])
        && q[4] == ':')
    {
        cur_addr = parse_hex4(&q);
        ++q;                              /* skip ':' */
    }

    skip_sp(&q);
    cmd = *q;

    /* ── Empty / semicolon ───────────────────────────────── */
    if (cmd == 0 || cmd == ';') {
        if (cmd == 0 && last_cmd) {
            /* repeat last paging command at cur_addr, no args */
            cmd = last_cmd;
            q = (uint8_t *)"";
            io_addr_cmd(cur_addr, cmd);
            clear_eol();
        } else {
            /* ';' or empty with nothing to repeat */
            last_cmd = 0;
            nl_clear(); return;
        }
    } else {
        ++q;                              /* skip command letter */
        if (*q == ' ') ++q;              /* optional space */
    }

    /* ── Save for repeat (paging + step commands) ───────── */
    if (cmd == 'm' || cmd == 'd' || cmd == '.' || cmd == 't' || cmd == 'o') {
        last_cmd = cmd;
    }

    /* ── Dispatch ────────────────────────────────────────── */
    switch (cmd) {

    /* block commands */
    case '.': cmd_dot(q);    break;
    case 'd': cmd_disasm(q); break;
    case 'm': cmd_mem(q);    break;

    /* navigation */
    case '@':
    {   uint16_t v;
        if (try_expr(&q, &v)) cur_addr = v;
        nl_clear(); break;
    }
    case '+':
    {   uint16_t d;
        if (!try_expr(&q, &d)) d = 0;
        cur_addr += d ? d : block_size;
        nl_clear(); break;
    }
    case '-':
    {   uint16_t d;
        if (!try_expr(&q, &d)) d = 0;
        cur_addr -= d ? d : block_size;
        nl_clear(); break;
    }

    /* execution */
    case 'j':
    {   uint16_t v;
        if (try_expr(&q, &v)) cur_addr = v;
        cmd_jmp(); break;
    }
    case 'g':
    {   uint16_t main_addr;
        if (sym_lookup("main", &main_addr) == 0) cur_addr = main_addr;
        cmd_jmp(); break;
    }

    /* debugger — step */
    case 't': cmd_step(q, 0); break;
    case 'o': cmd_step(q, 1); break;

    /* debugger — breakpoints */
    case 'b': cmd_brk(q); break;

    /* registers */
    case 'r': cmd_reg(q); break;

    /* file I/O */
    case 'l': cmd_load(q); break;
    case 's': cmd_write(q); break;
    case 'k':
        newline();
        io_puts(";delete source. are you sure? y/n ");
        if (io_getc() == 'y') {
            ed_new();
            io_puts("ok");
        }
        clear_eol(); nl_clear(); break;

    /* info / settings */
    case 'i': cmd_info(); break;
    case 'B':
    {   skip_sp(&q);
        if (is_hex(*q)) { uint16_t v = parse_hex_flex(&q); if (v) block_size = v; }
        newline();
        io_puts(";B="); io_puthex4(block_size);
        clear_eol(); nl_clear(); break;
    }
    case 'T':
    {   skip_sp(&q);
        if (is_hex(*q)) {
            uint8_t v;
            if (is_hex(q[1]))
                v = parse_hex2(&q);
            else
                v = hex_val(*q);
            if (v <= 32 && v != tab_width) {
                tab_width = v;
            }
        }
        newline();
        io_puts(";t="); io_puthex2(tab_width);
        clear_eol(); nl_clear(); break;
    }
    case 'C':
    {   skip_sp(&q);
        if (is_hex(q[0])) {
            if (is_hex(q[1]) && is_hex(q[2])) {
                theme_border = hex_val(q[0]);
                theme_bg     = hex_val(q[1]);
                theme_fg     = hex_val(q[2]);
            } else if (is_hex(q[1])) {
                theme_bg     = hex_val(q[0]);
                theme_fg     = hex_val(q[1]);
            } else {
                theme_fg     = hex_val(q[0]);
            }
            restore_colors();
        }
        newline();
        io_puts(";color: ");
        io_putc(hex_val_to_char(theme_border));
        io_putc(hex_val_to_char(theme_bg));
        io_putc(hex_val_to_char(theme_fg));
        clear_eol(); nl_clear(); break;
    }
    case 'u':
    {   skip_sp(&q);
        if (*q == '6') {
            uint8_t v = 0xFF;
            if (q[1]=='5' && q[2]=='0' && q[3]=='2') v = 0;
            else if (q[1]=='5' && q[2]=='1' && q[3]=='0') v = 1;
            else if (q[1]=='5' && q[2]=='c' && q[3]=='0') v = 2;
            if (v != 0xFF && v <= CPU_CEIL
#if CPU_CEIL == 2
                && v != 1
#endif
               ) al_cpu = v;
        }
        newline();
        io_puts(";cpu: 6502");
        io_putc(al_cpu == 0 ? '*' : ' ');
#if CPU_CEIL == 1
        io_puts(" 6510");
        io_putc(al_cpu == 1 ? '*' : ' ');
#elif CPU_CEIL == 2
        io_puts(" 65c02");
        io_putc(al_cpu == 2 ? '*' : ' ');
#endif
        clear_eol(); nl_clear(); break;
    }

    /* assemble source */
    case 'a':
    {   uint16_t errs;
        uint16_t main_addr;
        newline();
        io_puts(";assembling...");
        newline();
        errs = asm_assemble();
        if (errs == 0) {
            io_puts("; ok: ");
            io_putdec(asm_size);
            io_puts(" bytes at $");
            io_puthex4(asm_org);
            if (sym_lookup("main", &main_addr) == 0) cur_addr = main_addr;
        } else {
            io_puts("; ");
            io_putdec(errs);
            io_puts(" error(s)");
        }
        clear_eol(); nl_clear(); break;
    }

    /* calculator */
    case '?':
    {   uint8_t rc;
        uint16_t val;
        /* Set expr_ptr to point at the argument string */
        *(uint16_t *)expr_ptr = (uint16_t)q;
        rc = expr_eval();
        val = expr_val;
        if (rc <= 1) {
            newline();
            /* hex: right-aligned in 6 cols ("  $ff" or "$ffff") */
            io_puts("; ");
            if (val < 256) {
                io_puts("  $"); io_puthex2((uint8_t)val);
            } else {
                io_putc('$'); io_puthex4(val);
            }

            /* decimal: right-aligned 5 digits, 2sp gap */
            io_puts("  ");
            put_dec5_sp(val);

            /* 8-bit extras: binary + signed */
            if (val < 256) {
                uint8_t b = (uint8_t)val;
                int8_t  sb = (int8_t)b;
                uint8_t i, av;

                io_puts("  %");
                for (i = 0; i < 8; ++i) {
                    io_putc((b & 0x80) ? '1' : '0');
                    b <<= 1;
                }

                av = (sb < 0) ? (uint8_t)(-sb) : (uint8_t)sb;
                io_putc(' '); io_putc(' ');
                io_putc(sb < 0 ? '-' : '+');
                {   uint8_t d;
                    if (av >= 100) { d = 0; while (av >= 100) { av -= 100; ++d; } io_putc('0' + d); }
                    if (av >= 10) { d = 0; while (av >= 10) { av -= 10; ++d; } io_putc('0' + d); }
                    io_putc('0' + av);
                }
            }
            clear_eol();
        } else {
            newline();
            io_puts(";?"); io_puts(expr_error_str());
            clear_eol();
        }
        nl_clear(); break;
    }

    /* system */
    case 'q':
        newline();
        io_puts(";quit? y/n ");
        while (io_kbhit()) io_getc();
        if (io_getc() == 'y') state = ST_STOP;
        newline();
        if (state != ST_STOP) clear_eol();
        break;
    case '$':
    {   uint8_t dev;
        skip_sp(&q);
        if (*q >= '0' && *q <= '9') {
            dev = 0;
            while (*q >= '0' && *q <= '9')
                dev = (dev << 3) + (dev << 1) + (*q++ - '0');
            if (dev >= 4 && dev <= 30)
                cur_device = dev;
        }
        newline(); list_directory(cur_device); nl_clear();
        break;
    }

    /* debugger — continue */
    case 'c':
        /* cls/clr detection: "c" followed by "lr" or "ls" */
        if (*q == 'l' && (*(q+1) == 'r' || *(q+1) == 's')) {
            reset_screen(); clear_eol();
        } else if (dbg_reason == 0) {
            err_msg(";?no break"); nl_clear();
        } else {
            /* Delete the hit breakpoint before continuing */
            if (dbg_bp_hit != 0xFF) {
                dbg_bp_del(dbg_bp_hit);
            }
            dbg_enter();
            show_break_result();
        }
        break;

    default:
        err_msg(";?cmd"); nl_clear();
    }
}
