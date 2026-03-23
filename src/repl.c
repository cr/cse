/* ═══════════════════════════════════════════════════════════════
 * REPL — command line interface
 *
 * The screen IS the command buffer.  Press RETURN on any line
 * to execute it.  AAAA:cmd [args] for addressed commands,
 * cmd [args] for bare commands.  ';' ends parsing.
 * ═══════════════════════════════════════════════════════════════ */

#include <c64.h>
#include <conio.h>
#include <string.h>
#include <stdio.h>
#include <stdint.h>
#include "cse.h"
#include "repl.h"
#include "editor.h"

#define CURSOR_ROW (*(uint8_t *)0xD6)
#define CURSOR_COL (*(uint8_t *)0xD3)

/* ── REPL state ─────────────────────────────────────────── */
static uint16_t cur_addr = 0x1000;
static uint8_t  last_cmd = 0;
static uint8_t  last_args[16];
static uint16_t block_size = 0x10;
static uint8_t  *sym_top = 0;
static uint8_t  *sym_bot = 0;
char cur_filename[FILENAME_MAX_LEN + 1] = "";

/* ═══════════════════════════════════════════════════════════════
 * Screen line I/O
 * ═══════════════════════════════════════════════════════════════ */

static uint8_t line_buf[42];

void read_line(void) {
    uint8_t *src = SCREEN + CURSOR_ROW * SCREEN_WIDTH;
    uint8_t  i, sc;
    for (i = 0; i < SCREEN_WIDTH; ++i) {
        sc = src[i] & 0x7F;
        line_buf[i] = (sc < 0x20) ? (sc + 0x40) : sc;
    }
    i = SCREEN_WIDTH;
    while (i > 0 && line_buf[i - 1] == ' ') --i;
    line_buf[i] = 0;
    for (i = 0; line_buf[i]; ++i) {
        if (line_buf[i] == ';') { line_buf[i] = 0; break; }
    }
}

void show_prompt(void) {
    gotox(0);
    cprintf("%04x:", cur_addr);
    clear_eol();
}

/* ═══════════════════════════════════════════════════════════════
 * Stub disassembler
 * ═══════════════════════════════════════════════════════════════ */

static const char *disasm(uint16_t addr) {
    (void)addr;
    return "---";
}

/* ═══════════════════════════════════════════════════════════════
 * Line emitters
 * ═══════════════════════════════════════════════════════════════ */

static void emit_dot(uint16_t addr) {
    uint8_t olen, i;
    gotox(0);
    olen = t_opcode_len[*(uint8_t *)addr];
    cprintf("%04x:.", addr);
    for (i = 0; i < 3; ++i) {
        if (i < olen)
            cprintf(" %02x", ((uint8_t *)addr)[i]);
        else
            cputs("   ");
    }
    cputc(' ');
    cputs(disasm(addr));
    clear_eol();
}

static void emit_mem(uint16_t addr, uint8_t cols) {
    uint8_t *base = (uint8_t *)addr;
    uint8_t  i, b;
    if (cols == 0) cols = 8;
    if (cols > 8)  cols = 8;
    gotox(0);
    cprintf("%04x:m", addr);
    for (i = 0; i < 8; ++i) {
        if (i < cols)
            cprintf(" %02x", base[i]);
        else
            cputs("   ");
    }
    cputc(' ');
    for (i = 0; i < cols; ++i) {
        b = base[i];
        cputc((b >= 0x20 && b <= 0x7E) ? b : '.');
    }
    clear_eol();
}

static void emit_reg(void) {
    static const char flag_ch[] = "nv-bdizc";
    uint8_t i, p;
    gotox(0);
    cprintf("r a:%02x x:%02x y:%02x s:%02x ",
            reg_a, reg_x, reg_y, reg_sp);
    p = reg_p;
    for (i = 0; i < 8; ++i) {
        cputc((p & 0x80) ? flag_ch[i] : '.');
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
    while (nbytes < 3 && is_hex(*q) && is_hex(*(q + 1))) {
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
                gotox(0);
                cputs("?asm");
                clear_eol();
                return;
            }
        }
    }

    emit_dot(addr);
    olen = t_opcode_len[*(uint8_t *)addr];
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
        emit_dot(addr);
        addr += t_opcode_len[*(uint8_t *)addr];
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

    if (is_hex(q[0]) && is_hex(q[1]) && is_hex(q[2])) {
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

    emit_reg();
    newline();
    show_prompt();
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

/* ── AAAA:l "filename" — load PRG file from disk ───────────
 * If addr != 0, load to addr.  Otherwise load to the file's
 * embedded PRG address (like LOAD"X",8,1). */
static void cmd_load(uint16_t addr, uint8_t *args)
{
    uint8_t *q = args;
    uint8_t *name;
    unsigned int result;
    void *target;

    name = parse_filename(&q);

    /* use remembered filename if none given */
    if (!name) {
        if (cur_filename[0])
            name = (uint8_t *)cur_filename;
        else {
            cputs("?name");
            clear_eol();
            newline();
            show_prompt();
            return;
        }
    } else {
        /* remember for next time */
        strncpy(cur_filename, (char *)name, FILENAME_MAX_LEN);
        cur_filename[FILENAME_MAX_LEN] = 0;
    }

    newline();
    if (is_seq_file(name)) {
        /* source file → load into editor gap buffer */
        uint8_t err = ed_load_source((char *)name);
        if (err) {
            cprintf("?load %s", (char *)name);
        } else {
            cprintf("%s: %u lines, %u bytes",
                    (char *)name, ed_save_lines, ed_save_bytes);
        }
        clear_eol();
        newline();
        floppy_status();
    } else {
        /* PRG → load into memory */
        target = (addr != 0) ? (void *)addr : (void *)0;
        result = cbm_load((char *)name, 8, target);
        if (result == 0) {
            cprintf("?load %s", (char *)name);
        } else {
            cprintf("%s: %u bytes at %04x", (char *)name, result,
                    (addr != 0) ? addr : (uint16_t)result);
        }
        clear_eol();
        newline();
        floppy_status();
    }
    show_prompt();
}

/* ── AAAA:w "filename" EEEE — save memory range to disk ────
 * Saves addr..EEEE-1 (EEEE = end address exclusive).
 * Uses block_size if no end address given. */
static void cmd_write(uint16_t addr, uint8_t *args)
{
    uint8_t *q = args;
    uint8_t *name;
    uint16_t end;
    uint16_t size;
    uint8_t err;

    name = parse_filename(&q);

    /* use remembered filename if none given */
    if (!name) {
        if (cur_filename[0])
            name = (uint8_t *)cur_filename;
        else {
            cputs("?name");
            clear_eol();
            newline();
            show_prompt();
            return;
        }
    } else {
        strncpy(cur_filename, (char *)name, FILENAME_MAX_LEN);
        cur_filename[FILENAME_MAX_LEN] = 0;
    }

    newline();
    if (is_seq_file(name)) {
        /* source file → save editor gap buffer */
        ed_ensure_init();
        err = ed_save_source((char *)name);
        if (err) {
            cprintf("?save %s", (char *)name);
        } else {
            cprintf("%s: %u lines, %u bytes",
                    (char *)name, ed_save_lines, ed_save_bytes);
        }
        clear_eol();
        newline();
        floppy_status();
    } else {
        /* PRG → save memory range */
        skip_sp(&q);
        if (is_hex(q[0]) && is_hex(q[1]) && is_hex(q[2]) && is_hex(q[3])) {
            end = parse_hex4(&q);
        } else {
            end = addr + block_size;
        }

        if (end <= addr) {
            cputs("?range");
            clear_eol();
            newline();
            show_prompt();
            return;
        }

        size = end - addr;
        err = cbm_save((char *)name, 8, (void *)addr, size);

        if (err) {
            cprintf("?save %s", (char *)name);
        } else {
            cprintf("%s: %u bytes %04x-%04x",
                    (char *)name, size, addr, end - 1);
        }
        clear_eol();
        newline();
        floppy_status();
    }
    show_prompt();
}

/* print one info line: "tag  AAAA-BBBB description" */
/* if inv is set, print in reverse video               */
static void info_line(uint8_t inv, const char *tag,
                      uint16_t lo, uint16_t hi, const char *desc)
{
    uint8_t *scr;
    uint8_t col;
    if (inv) revers(1);
    cprintf("%-4s %04x-%04x %s", tag, lo, hi, desc);
    /* fill rest of line — use 0xA0 (reversed space) when inverted */
    col = wherex();
    scr = SCREEN + wherey() * SCREEN_WIDTH;
    while (col < SCREEN_WIDTH) scr[col++] = inv ? 0xA0 : 0x20;
    if (inv) revers(0);
    newline();
}

static void free_line(uint16_t lo, uint16_t hi, char *fbuf)
{
    sprintf(fbuf, "%u bytes free", hi - lo + 1);
    info_line(1, "free", lo, hi, fbuf);
}

static void cmd_info(void)
{
    uint16_t cse_hi  = cse_end();
    uint16_t cstk_lo = 0xC800;
    uint16_t free_lo, free_hi;
    char fbuf[20];

    newline();

    /* $0000-$00FF: zero page */
    info_line(0, "cpu",  0x0000, 0x0001, "i/o port");
    info_line(0, "zp",   0x0002, 0x0038, "cse (saved on j)");
    free_line(0x0039, 0x007f, fbuf);
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
        free_line(free_lo, free_hi, fbuf);

    /* show allocations in address order (sym below src) */
    if (sym_bot)
        info_line(0, "sym", (uint16_t)sym_bot,
                  (uint16_t)sym_top - 1, "symbols");
    if (src_bot)
        info_line(0, "src", (uint16_t)src_bot,
                  (uint16_t)src_top - 1, "source");

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
        cmd = *q;

        /* empty after colon → repeat last command at this address */
        if (cmd == 0 || cmd == ' ') {
            if (last_cmd) {
                cmd = last_cmd;
                q = last_args;
            } else {
                newline();
                show_prompt();
                return;
            }
        } else {
            ++q;                          /* skip command letter */
            if (*q == ' ') ++q;           /* optional space */
        }

        /* seek: args override prefix address */
        if (cmd == 's') {
            skip_sp(&q);
            if (is_hex(q[0]) && is_hex(q[1]) && is_hex(q[2]) && is_hex(q[3]))
                cur_addr = parse_hex4(&q);
            else
                cur_addr = addr;
            newline();
            show_prompt();
            return;
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
        case 'j': cmd_jmp(addr);       break;
        case '+':
        {   uint16_t delta = block_size;
            if (is_hex(q[0]) && is_hex(q[1])) {
                if (is_hex(q[2]) && is_hex(q[3]))
                    delta = parse_hex4(&q);
                else
                    delta = parse_hex2(&q);
            }
            cur_addr = addr + delta;
            newline();
            show_prompt();
            break;
        }
        case '-':
        {   uint16_t delta = block_size;
            if (is_hex(q[0]) && is_hex(q[1])) {
                if (is_hex(q[2]) && is_hex(q[3]))
                    delta = parse_hex4(&q);
                else
                    delta = parse_hex2(&q);
            }
            cur_addr = addr - delta;
            newline();
            show_prompt();
            break;
        }
        case 'l': cmd_load(addr, q);   break;
        case 'w': cmd_write(addr, q);  break;
        case 'b':
            if (is_hex(q[0]) && is_hex(q[1])) {
                if (is_hex(q[2]) && is_hex(q[3]))
                    block_size = parse_hex4(&q);
                else
                    block_size = parse_hex2(&q);
                if (block_size == 0) block_size = 8;
            }
            cprintf("b=%04x", block_size);
            clear_eol();
            newline();
            show_prompt();
            break;
        case 'i': cmd_info();          break;
        case 'r': cmd_reg(q);          break;
        case 's':
            if (is_hex(q[0]) && is_hex(q[1]) && is_hex(q[2]) && is_hex(q[3]))
                cur_addr = parse_hex4(&q);
            newline();
            show_prompt();
            break;
        case 'q':
            cputs("quit? y/n ");
            while (kbhit());
            if (cgetc() == 'y') {
                state = ST_STOP;
            }
            newline();
            if (state != ST_STOP) show_prompt();
            break;
        case '$':
            newline();
            list_directory(8);
            show_prompt();
            break;
        default:
            cputs("?cmd");
            clear_eol();
            newline();
            show_prompt();
        }
        return;
    }

    /* ── No AAAA: prefix — bare input ────────────────────── */

    /* empty line */
    if (*q == 0) {
        newline();
        show_prompt();
        return;
    }

    /* multi-char: clr/cls */
    if (q[0] == 'c' && q[1] == 'l' && (q[2] == 'r' || q[2] == 's')) {
        reset_screen();
        show_prompt();
        return;
    }

    /* anything else without a prefix is unknown */
    cputs("?");
    clear_eol();
    newline();
    show_prompt();
}
