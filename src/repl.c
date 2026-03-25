/* ═══════════════════════════════════════════════════════════════
 * REPL — command line interface
 *
 * The screen IS the command buffer.  Press RETURN on any line
 * to execute it.  AAAA:cmd [args] for addressed commands,
 * cmd [args] for bare commands.  ';' ends parsing.
 * ═══════════════════════════════════════════════════════════════ */

#include <c64.h>
#include <cbm.h>
#include <string.h>
#include <stdint.h>
#include "cse.h"
#include "cse_io.h"
#include "repl.h"
#include "editor.h"

/* ── REPL state ─────────────────────────────────────────── */
uint16_t cur_addr = 0x1000;
static uint8_t  last_cmd = 0;
static uint8_t  last_args[16];
static uint16_t block_size = 0x10;
static uint8_t  *sym_top = 0;
static uint8_t  *sym_bot = 0;
char cur_filename[FILENAME_MAX_LEN + 1] = "";

/* ── Common patterns factored out ──────────────────────── */

/* newline + fresh prompt — used by most commands on exit */
static void nl_prompt(void) { newline(); show_prompt(); }

/* error message on next line + prompt */
static void err_prompt(const char *msg) {
    newline(); io_puts(msg); clear_eol(); nl_prompt();
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

/* ═══════════════════════════════════════════════════════════════
 * Screen line I/O
 * ═══════════════════════════════════════════════════════════════ */

static uint8_t line_buf[42];

void read_line(void) {
    uint8_t *src = SCREEN + io_cy * SCREEN_WIDTH;
    uint8_t  i, sc;
    for (i = 0; i < SCREEN_WIDTH; ++i) {
        sc = src[i] & 0x7F;
        /* if/else instead of ternary — cc65 -O miscompiles the ternary
         * (uses wrong stack offset for the identity branch) */
        if (sc < 0x20)
            line_buf[i] = sc + 0x40;
        else
            line_buf[i] = sc;
    }
    i = SCREEN_WIDTH;
    while (i > 0 && line_buf[i - 1] == ' ') --i;
    line_buf[i] = 0;
    /* ';' handling moved to exec_line — first char = command, else = EOL */
}

void show_prompt(void) {
    io_cx = 0;
    io_puthex4(cur_addr);
    io_putc(':');
    clear_eol();
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
    io_cx = 0;
    olen = dasm_insn(addr);             /* disassemble first to get length */
    io_puthex4(addr); io_putc(':'); io_putc('.');
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
    io_cx = 0;
    io_puthex4(addr); io_putc(':'); io_putc('m');
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
    static const char flag_ch[] = "nv-bdizc";
    uint8_t i, p;
    io_cx = 0;
    io_puts("r a:"); io_puthex2(reg_a);
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
 * Command handlers
 * ═══════════════════════════════════════════════════════════════ */

static void cmd_dot(uint16_t addr, uint8_t *args)
{
    uint8_t  bytes[3], nbytes, olen, i, changed;
    uint8_t *q = args, *mne;

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
            nbytes = asm_line(addr, (char *)mne);
            if (nbytes == 0) {
                err_prompt("?asm"); return;
            }
        }
    }

    olen = emit_dot(addr);
    cur_addr = addr + olen;
    newline();
    show_prompt();
}

static void cmd_disasm(uint16_t addr, uint8_t *args)
{
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
    show_prompt();
}

static void cmd_mem(uint16_t addr, uint8_t *args)
{
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
        show_prompt();
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
    show_prompt();
}

static void cmd_jmp(uint16_t addr)
{
    cur_addr = addr;
    jsr_addr(addr);
    restore_colors();
    newline();
    emit_reg();
    newline();
    show_prompt();
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
    static const char flag_ch[] = "nv-bdizc";
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
    nl_prompt();
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

/* Print "name: N lines, M bytes" for SEQ file result */
static void print_seq_stats(const char *name) {
    io_puts(name); io_puts(": ");
    io_putdec(ed_save_lines); io_puts(" lines, ");
    io_putdec(ed_save_bytes); io_puts(" bytes");
}

/* Common disk-op footer: clear_eol, newline, drive status, prompt */
static void disk_done(void) {
    clear_eol(); newline(); floppy_status(); show_prompt();
}

static void cmd_load(uint16_t addr, uint8_t *args)
{
    uint8_t *q = args;
    uint8_t *name = get_filename(&q);
    if (!name) { err_prompt("?name"); return; }

    newline();
    if (is_seq_file(name)) {
        uint8_t err = ed_load_source((char *)name);
        if (err) { io_puts("?load "); io_puts((char *)name); }
        else print_seq_stats((char *)name);
    } else {
        void *target = (addr != 0) ? (void *)addr : (void *)0;
        unsigned int result = cbm_load((char *)name, 8, target);
        if (result == 0) { io_puts("?load "); io_puts((char *)name); }
        else {
            io_puts((char *)name); io_puts(": ");
            io_putdec(result); io_puts(" bytes at ");
            io_puthex4((addr != 0) ? addr : (uint16_t)result);
        }
    }
    disk_done();
}

static void cmd_write(uint16_t addr, uint8_t *args)
{
    uint8_t *q = args;
    uint8_t *name = get_filename(&q);
    uint8_t err;
    if (!name) { err_prompt("?name"); return; }

    newline();
    if (is_seq_file(name)) {
        ed_ensure_init();
        err = ed_save_source((char *)name);
        if (err) { io_puts("?save "); io_puts((char *)name); }
        else print_seq_stats((char *)name);
    } else {
        uint16_t end = parse_hex_flex(&q);
        uint16_t size;
        if (!end) end = addr + block_size;
        if (end <= addr) { err_prompt("?range"); return; }
        size = end - addr;
        err = cbm_save((char *)name, 8, (void *)addr, size);
        if (err) { io_puts("?save "); io_puts((char *)name); }
        else {
            io_puts((char *)name); io_puts(": ");
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
    uint8_t *scr = SCREEN + io_cy * SCREEN_WIDTH;
    uint8_t col;
    io_cx = 0;
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
    /* manual utoa + " bytes free" — avoids sprintf */
    uint16_t n = hi - lo + 1;
    uint8_t pos = 0;
    char tmp[6];
    uint8_t tlen = 0;
    if (n == 0) { tmp[tlen++] = '0'; }
    else { while (n > 0) { tmp[tlen++] = '0' + (n % 10); n /= 10; } }
    while (tlen > 0) fbuf[pos++] = tmp[--tlen];
    fbuf[pos++] = ' '; fbuf[pos++] = 'b'; fbuf[pos++] = 'y';
    fbuf[pos++] = 't'; fbuf[pos++] = 'e'; fbuf[pos++] = 's';
    fbuf[pos++] = ' '; fbuf[pos++] = 'f'; fbuf[pos++] = 'r';
    fbuf[pos++] = 'e'; fbuf[pos++] = 'e'; fbuf[pos] = 0;
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
    info_line(0, "zp",   0x0002, 0x0038, "cse (saved on j)");
    free_line(0x0039, 0x007f);
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

    /* source and symbols eat into the top of the free region */
    if (sym_bot) free_hi = (uint16_t)sym_bot - 1;
    if (src_bot) free_hi = (uint16_t)src_bot - 1;

    if (free_lo <= free_hi)
        free_line(free_lo, free_hi);

    /* show allocations in address order (sym below src) */
    if (sym_bot)
        info_line(0, "sym", (uint16_t)sym_bot,
                  (uint16_t)sym_top - 1, "symbols");
    if (src_bot)
        info_line(0, "src", (uint16_t)src_bot,
                  (uint16_t)src_top - 1, "source code");

    /* c stack and I/O */
    info_line(0, "cstk", cstk_lo, 0xcfff, "c stack");
    info_line(0, "io",   0xd000, 0xdfff, "vic/sid/cia");
    info_line(0, "kern", 0xe000, 0xffff, "kernal rom");

    show_prompt();
}

/* ═══════════════════════════════════════════════════════════════
 * Command dispatcher
 * ═══════════════════════════════════════════════════════════════ */

void exec_line(void)
{
    uint8_t *q = line_buf;
    uint16_t addr;
    uint8_t  cmd;

    skip_sp(&q);

    /* ── Try AAAA:cmd format ─────────────────────────────── */
    if (is_hex(q[0]) && is_hex(q[1]) && is_hex(q[2]) && is_hex(q[3])
        && q[4] == ':')
    {
        addr = parse_hex4(&q);
        ++q;                              /* skip ':' */
        skip_sp(&q);                      /* tolerate spaces after ':' */
        cmd = *q;

        /* ';' as first char = command: clear repeat, fresh prompt */
        if (cmd == ';') {
            last_cmd = 0;
            nl_prompt(); return;
        }

        /* empty = repeat last command if prompt was truly blank */
        if (cmd == 0) {
            if (last_cmd) {
                cmd = last_cmd;
                q = last_args;
                io_cx = 5;
                io_putc(cmd);
                if (*q) { io_putc(' '); io_puts((const char *)q); }
                clear_eol();
            } else {
                nl_prompt(); return;
            }
        } else {
            ++q;                          /* skip command letter */
            if (*q == ' ') ++q;           /* optional space */
            /* cut at ';' in the rest (comment) */
            {   uint8_t *s;
                for (s = q; *s; ++s)
                    if (*s == ';') { *s = 0; break; }
            }
        }

        /* seek: args override prefix address */
        if (cmd == 's') {
            uint16_t v;
            skip_sp(&q);
            v = parse_hex_flex(&q);
            cur_addr = v ? v : addr;
            nl_prompt(); return;
        }

        cur_addr = addr;

        /* save for repeat */
        last_cmd = cmd;
        strncpy(last_args, q, sizeof(last_args) - 1);
        last_args[sizeof(last_args) - 1] = 0;

        switch (cmd) {
        case '.': cmd_dot(addr, q);    break;
        case 'd': cmd_disasm(addr, q); break;
        case 'm': cmd_mem(addr, q);    break;
        case 'j':
        {   uint16_t v = parse_hex_flex(&q);
            if (v) addr = v;
            cmd_jmp(addr); break;
        }
        case '+':
        {   uint16_t d = parse_hex_flex(&q);
            cur_addr = addr + (d ? d : block_size);
            nl_prompt(); break;
        }
        case '-':
        {   uint16_t d = parse_hex_flex(&q);
            cur_addr = addr - (d ? d : block_size);
            nl_prompt(); break;
        }
        case 'c':                             /* color theme */
        {   skip_sp(&q);                      /* c F, c BF, c DBF */
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
            io_puts("color: ");
            io_putc(hex_val_to_char(theme_border));
            io_putc(hex_val_to_char(theme_bg));
            io_putc(hex_val_to_char(theme_fg));
            clear_eol(); nl_prompt(); break;
        }
        case 'l': cmd_load(addr, q);   break;
        case 'w': cmd_write(addr, q);  break;
        case 'b':
        {   uint16_t v = parse_hex_flex(&q);
            if (v) block_size = v ? v : 8;
            newline();
            io_puts("b="); io_puthex4(block_size);
            clear_eol(); nl_prompt(); break;
        }
        case 'i': cmd_info();          break;
        case 'r': cmd_reg(q);          break;
        case 'u':                             /* CPU mode: u 6502|6510|65c02 */
        {   skip_sp(&q);
            if (*q == '6') {
                /* match "6502", "6510", "65c02" */
                uint8_t v = 0xFF;
                if (q[1]=='5' && q[2]=='0' && q[3]=='2') v = 0;
                else if (q[1]=='5' && q[2]=='1' && q[3]=='0') v = 1;
                else if (q[1]=='5' && q[2]=='c' && q[3]=='0') v = 2;
                /* 65C02 builds: only 0 and 2 valid (no 6510 illegals) */
                if (v != 0xFF && v <= CPU_CEIL
#if CPU_CEIL == 2
                    && v != 1
#endif
                   ) al_cpu = v;
            }
            newline();
            io_puts("cpu mode: 6502");
            io_putc(al_cpu == 0 ? '*' : ' ');
#if CPU_CEIL == 1
            io_puts(" 6510");
            io_putc(al_cpu == 1 ? '*' : ' ');
#elif CPU_CEIL == 2
            io_puts(" 65c02");
            io_putc(al_cpu == 2 ? '*' : ' ');
#endif
            clear_eol(); nl_prompt(); break;
        }
        case 's':
        {   uint16_t v = parse_hex_flex(&q);
            if (v) cur_addr = v;
            nl_prompt(); break;
        }
        case 'q':
            newline();
            io_puts("quit? y/n ");
            while (io_kbhit());
            if (io_getc() == 'y') state = ST_STOP;
            newline();
            if (state != ST_STOP) show_prompt();
            break;
        case '$':
            newline(); list_directory(8); show_prompt();
            break;
        default:
            err_prompt("?cmd");
        }
        return;
    }

    /* ── No AAAA: prefix — bare input ────────────────────── */

    if (*q == 0 || *q == ';') { last_cmd = 0; nl_prompt(); return; }

    /* cut at ';' for bare commands too */
    {   uint8_t *s;
        for (s = q; *s; ++s)
            if (*s == ';') { *s = 0; break; }
    }

    /* multi-char: clr/cls */
    if (q[0] == 'c' && q[1] == 'l' && (q[2] == 'r' || q[2] == 's')) {
        reset_screen(); show_prompt(); return;
    }

    err_prompt("?");
}
